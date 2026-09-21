"""Budget-scheduler orchestration (MP-agnostic).

For each of a tenant's budget schedules: match the rule that applies *now* (IST) →
compute the target budget (or `default_budget`) → read the current budget → route
through the write choke-point. Dry-run by default (reads happen, no writes).

The rule-matching (`target_for_now` / `_matches_rule`) is a **pure function** —
ported from `ad_campaigns/scheduler.py` (validated v1 logic) and unit-tested in
tests/test_budget_rules.py without Blinkit or the DB.
"""
import uuid
from datetime import datetime

from app.core.config import settings
from app.utils.time import now_ist
from campaign_manager import config, lifecycle, logs, repo, window, writes
from campaign_manager.marketplaces import get_adapter


# ── Pure rule matching (unit-tested) ────────────────────────────────────────
#
# WHEN a rule applies is answered by `campaign_manager.window`, shared with the bid engine,
# the reconciler and the API's status. `_matches_rule` is this engine's view of it: a rule
# in budget vocabulary (`end_time` / `end_date` / `time_slots`) in, translated once.

def _matches_rule(rule: dict, now: datetime) -> bool:
    """Does this rule apply at `now`? — `window.in_window`.

    Its exclusive end matters most HERE: when a 19:00–02:00 window still matched AT 02:00,
    the 02:00 fire computed "still running" and never stopped the campaign, and no later
    fire did either, because by 03:00 the window no longer counted as *just ended*."""
    return window.in_window(window.from_budget(rule), now)


_WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _day_words(days) -> str:
    """['sunday', 'friday', 'saturday'] → 'Fri, Sat, Sun' — in week order, because the
    stored order is whatever the form was clicked in and reads as noise."""
    chosen = {str(d).lower() for d in (days or [])}
    picked = [d for d in _WEEK if d in chosen]
    if not picked or len(picked) == 7:
        return "every day"
    return ", ".join(d[:3].capitalize() for d in picked)


def _day_word(date_str) -> str:
    """'2026-09-11' → '11 Sep'. Left alone if it isn't a date we can parse."""
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d")
    except (TypeError, ValueError):
        return str(date_str)
    return f"{d.day} {d:%b}"


def _reason(rule: dict) -> str:
    """Human-readable why-this-rule string (for logs + history).

    Read by clients in the History table, so it is written as English rather than as the
    stored shape: it used to render an open-ended rule as
    `sunday, friday, saturday (2026-09-11–None) / 19:30–02:00`, where `None` is a missing
    end date and the slash is a field separator nobody outside the code knows about.
    """
    start, end = rule.get("start_time"), rule.get("end_time")
    if start or end:
        when = f"{start or '00:00'}–{end or '23:59'}"
    else:
        when = ", ".join(rule.get("time_slots") or []) or "all day"

    if rule.get("type") == "once":
        date = rule.get("date")
        return f"one-time {_day_word(date)} {when}" if date else f"one-time {when}"

    first, last = rule.get("start_date"), rule.get("end_date")
    if first and last:
        span = f", {_day_word(first)}–{_day_word(last)}"
    elif first:
        span = f", from {_day_word(first)}"
    elif last:
        span = f", until {_day_word(last)}"
    else:
        span = ""
    return f"{_day_words(rule.get('days'))} {when}{span}"


def _schedule_summary(default_budget: float, rules: list[dict], *,
                      stop_after_window: bool) -> str:
    """The schedule's own configuration, for the line under its block header — the budget
    engine's answer to the bid engine's "target position · current bid · limits"."""
    parts = [f"default ₹{default_budget:g}"]
    if not rules:
        parts.append("no rules — this schedule only holds that default")
    else:
        parts += [f"₹{r['budget']:g} on {_reason(r)}" for r in rules[:2]]
        if len(rules) > 2:
            parts.append(f"+{len(rules) - 2} more rule" + ("s" if len(rules) > 3 else ""))
    if stop_after_window:
        parts.append("stops the campaign when a window ends")
    return " · ".join(parts)


def _plan_sentence(*, matched: bool, want_state: str | None, target: float,
                   reason: str) -> str:
    """What this run means to do, and why — the budget engine's `decided` line.

    Built from the same three facts `plan_for_now` decided on, rather than from its
    `reason` string alone, so a log line never has to be parsed back out of History text.
    """
    money = f"₹{target:g}"
    if matched:
        return f"the rule for {reason} applies now, so the budget should be {money}"
    if want_state == "paused":
        return (f"the window has just ended, so the budget goes back to its {money} default "
                f"and the campaign stops")
    return f"no rule applies right now, so the budget should be its {money} default"


def _history_reason(*, matched: bool, has_rules: bool, closing: bool,
                    target: float | None, reason: str) -> str:
    """Why this run acted, as the History row says it — what the client reads.

    `plan_for_now`'s own `reason` is a label, not an explanation: a rule summary ("Fri, Sat,
    Sun 19:30–02:00") or "window ended". Filed as-is, a row read as the schedule's
    configuration and never said what the engine made of it. This is the same decision in
    one sentence; a write that did not land gets its cause appended by `_verdict`.
    """
    if target is None:
        return reason
    money = f"₹{target:g}"
    if matched:
        return f"the {reason} window is open, so the budget goes to {money}"
    if not has_rules:
        return f"this automation keeps the campaign at its {money} default"
    if closing:
        return f"the window ended, so the budget goes back to its {money} default"
    return (f"a window closed and the budget was never put back, so it goes back to its "
            f"{money} default now")


def _verdict(ok: bool, outcome: dict, why: str, landed: str = "apply") -> tuple[str, bool, str]:
    """How one write is recorded: (action, success, reason) — the budget engine's twin of
    `bid._write_verdict`, without the exception branch (the choke point does not raise here).

    A write that was not NEEDED ("the budget is already ₹800") is a successful `no-op`; one
    that was REFUSED — the marketplace's rejection, a bound, the rate limit — is an
    unsuccessful `skip` carrying the refusal's own words. Both used to be a successful skip
    whose reason was the rule, which read as though the change had gone through.
    """
    if ok:
        return landed, True, why
    said = (outcome or {}).get("reason")
    if writes.not_needed(outcome):
        return "no-op", True, f"{why} — {said}, so nothing was changed"
    return "skip", False, f"{why} — not applied: {said or 'the marketplace did not accept it'}"


def target_for_now(default_budget: float, rules: list[dict], now: datetime) -> tuple[float, str]:
    """The budget that should apply right now: the first matching rule's budget, else
    the default. Returns (target, reason)."""
    for rule in rules:
        if _matches_rule(rule, now):
            return rule["budget"], _reason(rule)
    return default_budget, "no active rule — default budget"


# ── Campaign activation (docs/campaign-manager.md) ───────────────────────

def _window_just_ended(rules: list[dict], now: datetime,
                       grace_seconds: int | None = None) -> bool:
    """True when nothing matches now but something did within the last `grace` — i.e.
    this moment IS a window END, rather than merely some moment outside a window.

    That distinction is the whole of AD2. "Stop whenever nothing matches" would stop a
    campaign at times nobody asked for: a schedule created at 14:00 for a 19:00–02:00
    window would have its campaign stopped by the 15:00 safety poll, hours before the
    automation had ever run. Derived from the rules alone — nothing is remembered.

    The "nothing matches now" half is the caller's: `plan_for_now` returns before asking.
    The look-back is `window.was_open_within` — an interval probe, never a point, because a
    point probe misses every window shorter than the grace (campaign 574687, 2026-08-08).

    The grace is the scheduler's own misfire window, so the two agree on what counts as a
    late fire. Consequence, accepted deliberately: a window-end fire missed while the
    runner was down means no stop that night (R8) — the campaign runs on at its default
    budget until the next window.
    """
    grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS if grace_seconds is None else grace_seconds
    return window.was_open_within([window.from_budget(r) for r in rules], now, grace)


def plan_for_now(default_budget: float, rules: list[dict], now: datetime, *,
                 stop_after_window: bool = False,
                 revert_owed: bool = False) -> tuple[float | None, str | None, str]:
    """What should be true for this campaign right now → (budget, state, reason).

    The budget has three answers, and the third is the one that keeps this engine out of the
    campaign's way:
      - a **rule's budget** while that rule's window is open;
      - the **default**, at the moment a window closes — or later, while `revert_owed` says
        that close's revert never landed (the failsafe, `lifecycle.revert_owed`);
      - **None — nothing to enforce.** Between windows the campaign's budget is not ours.
        It used to be the default here too, so every hourly poll re-asserted it and a budget
        someone had set by hand at 10:00 was gone by 11:00.

    A schedule with NO rules is the exception: enforcing its default is the whole of what it
    does, so it always answers the default.

    `state` also has three answers, and the third matters as much as the other two:
      - `"running"` — a rule is active. Starting is UNCONDITIONAL (AD7): a campaign with
        a budget window is meant to run during it, so finding it stopped and leaving it
        stopped would silently do nothing all evening.
      - `"paused"` — a window has ended and this schedule opted in.
      - `None` — the campaign's status is none of our business at this moment. With the
        toggle off this is the only non-`"running"` answer, so an existing schedule never
        has its status touched at all.

    Pure. `target_for_now` remains the budget-only view of "what does the calendar say",
    which is a different question from "what should this run do".
    """
    for rule in rules:
        if _matches_rule(rule, now):
            return rule["budget"], "running", _reason(rule)
    if not rules:
        return default_budget, None, "no rules — this schedule holds its default budget"
    closing = _window_just_ended(rules, now)
    if not (closing or revert_owed):
        return None, None, "outside every window — the budget is not this automation's to set"
    state = "paused" if stop_after_window else None
    reason = ("window ended" if closing else
              "a window closed and the budget was never put back — doing it now")
    return default_budget, state, reason


def _rule_to_dict(r) -> dict:
    """CmBudgetRule ORM row → the plain dict the matcher expects."""
    return {
        "type": r.type, "days": r.days or [], "time_slots": r.time_slots or [],
        "start_time": r.start_time, "end_time": r.end_time,
        "start_date": r.start_date, "end_date": r.end_date,
        "date": r.date, "budget": r.budget,
    }


# ── Orchestration ───────────────────────────────────────────────────────────

def _has_work(schedule, rules, now: datetime, grace_seconds: float) -> bool:
    """Is there anything for this run to do about this schedule at `now`?

    The engine acts on a window's EDGES and inside it, never between windows:

      - a window is open → the rule's budget is enforced (drift included);
      - a window has just closed → revert, and stop the campaign if the toggle is on;
      - a close is still owed its revert → the failsafe, `lifecycle.revert_owed`;
      - the automation has ENDED without its final teardown landing → the settle-once
        safety net, which also records the ending in History;
      - the schedule has no rules at all → its default is all it has, so it is always enforced.

    Answered BEFORE sign-in, so a tenant whose windows are all closed does not log in to do
    nothing. Between windows this is false, and that is the point: the hourly poll used to
    re-assert `default_budget` on every fire, which overwrote a budget set by hand (2026-09-09)
    and kept a browser session churning around the clock.
    """
    if not rules:
        return True
    windows = [window.from_budget(r) for r in rules]
    if any(window.in_window(w, now) for w in windows):
        return True
    if window.was_open_within(windows, now, grace_seconds):
        return True
    return (lifecycle.schedule_revert_owed(schedule, rules, now)
            or lifecycle.schedule_needs_settle(schedule, rules, now))


async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              platform: str = "blinkit", run_id: str | None = None) -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = run_id or logs.new_run_id()
    started = now_ist()
    logs.run_start(run_id, "budget_scheduler", tenant_id, dry_run=dry_run, platform=platform,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    # Only the schedules with something to do right now (`_has_work`), decided on `started`
    # and BEFORE sign-in. A schedule that reaches an edge between `started` and `now` is
    # picked up by the next run.
    grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS
    schedules = [(s, rules) for s, rules in await repo.get_budget_schedules(
                     tenant_id, platform, state="active", calendar=repo.ANY_CALENDAR)
                 if _has_work(s, rules, started, grace)]
    if not schedules:
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run, unit="campaigns",
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    processed = applied = skipped = errors = 0
    log_rows: list[dict] = []
    # Catalogue write-back, flushed once with `log_rows` below (campaign_manager/writes.py).
    patches: list[dict] = []
    # The final teardowns this run performed — schedule id → the close each one covers — and
    # the ones that did not land, which count against SETTLE_MAX_ATTEMPTS. `latched` is the
    # same stamp for an ordinary window close: the schedule has been put back to its default,
    # so nothing is owed until the next close (`lifecycle.revert_owed`).
    settled: dict[int, datetime] = {}
    latched: dict[int, datetime] = {}
    failed: list[int] = []

    # A session/browser is only set up when there's work — reads happen even in dry-run.
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError as e:
        logs.session_expired(run_id, dry_run=dry_run)
        await _record_run_blocked(
            tenant_id, platform, run_id, schedules,
            f"could not sign in to {platform.title()}, so the budget was not changed "
            f"({' '.join(str(e).split())[:110]})", dry_run)
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run, unit="campaigns",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run, platform=platform)

    # Live runs must pass the account guardrail (B3) before any write.
    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            await _record_run_blocked(
                tenant_id, platform, run_id, schedules,
                f"the ad account could not be confirmed, so the budget was not changed "
                f"({' '.join(str(e).split())[:110]})", dry_run)
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run, unit="campaigns",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    now = now_ist()  # captured after setup so the time is fresh at a boundary
    try:
        for schedule, rules in schedules:
            processed += 1
            cid, cname = schedule.campaign_id, schedule.campaign_name
            rule_dicts = [_rule_to_dict(r) for r in rules]
            # This run IS the schedule's final teardown once its last window has closed —
            # at that window's own end fire, or at a later settle pass.
            close = lifecycle.budget_schedule_close(rules)
            final = close is not None and close != datetime.min and close <= now
            landed = False
            stop_after = bool(getattr(schedule, "stop_after_window", False))
            # The edges this fire sits on, and the close a revert would be tearing down.
            open_now = any(_matches_rule(r, now) for r in rule_dicts)
            closing = bool(rule_dicts) and not open_now and _window_just_ended(rule_dicts, now)
            owed = lifecycle.schedule_revert_owed(schedule, rules, now)
            last_close = lifecycle.schedule_previous_close(rules, now)
            reverting = False
            # One block per campaign, exactly as the bid engine narrates one per keyword:
            # header → what the schedule says → what the marketplace says → what we did.
            logs.blank(run_id, dry_run=dry_run)
            logs.rule_header(run_id, dry_run=dry_run, index=processed, total=len(schedules),
                             campaign_name=cname, campaign_id=cid)
            logs.context(run_id, dry_run=dry_run, campaign_id=cid,
                         msg=_schedule_summary(schedule.default_budget, rule_dicts,
                                               stop_after_window=stop_after))
            try:
                if final and not open_now and not closing:
                    # A late settle: the run that should have torn this automation down at its
                    # last window's end never landed (the runner was down, or the write
                    # failed). Do exactly what that run would have done — revert, and stop
                    # if the schedule asks for it.
                    target = schedule.default_budget
                    want_state = "paused" if stop_after else None
                    reason = ("the automation ended and its final run never landed — "
                              "settling it now")
                    say = (f"this automation has ended and its last run never landed, so its "
                           f"budget goes back to its ₹{target:g} default now"
                           + (" and the campaign stops" if want_state else ""))
                    why = (f"this automation has ended and its last run never landed, so the "
                           f"budget goes back to its ₹{target:g} default now")
                else:
                    target, want_state, reason = plan_for_now(
                        schedule.default_budget, rule_dicts, now,
                        stop_after_window=stop_after, revert_owed=owed,
                    )
                    say = _plan_sentence(matched=open_now, want_state=want_state,
                                         target=target, reason=reason)
                    why = _history_reason(matched=open_now, has_rules=bool(rule_dicts),
                                          closing=closing, target=target, reason=reason)
                reverting = target is not None and not open_now and bool(rule_dicts)

                if target is None:
                    # Between windows with nothing owed: the campaign's budget is not ours to
                    # set, so this schedule is not read and not written. No History row — a
                    # row per campaign per hour saying "did nothing" is the noise D6 excludes.
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, msg=reason)
                    skipped += 1
                    continue

                if target <= 0:
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, level="warning",
                                 msg=f"skipping — ₹{target:g} is not a budget we will write")
                    skipped += 1
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                         "skip", None, target,
                                         f"₹{target:g} is not a budget this automation will "
                                         f"set, so nothing was changed", dry_run, True))
                    continue

                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, msg=say)
                try:
                    # One call gives status AND budget — Blinkit's campaign LIST is unusable
                    # for status (it 400s when any campaign type is disabled for the
                    # advertiser, and get_campaigns swallows that into an empty list).
                    current_state, current, detail = await adapter.read_campaign(client, cid)
                except Exception as e:
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, level="error",
                                  msg=f"could not read the campaign from {platform.title()} "
                                      f"— {' '.join(str(e).split())[:120]}")
                    errors += 1
                    detail = " ".join(str(e).split())[:120]
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                         "error", None, target,
                                         f"{why} — but the campaign could not be read from "
                                         f"{platform.title()}, so nothing was changed ({detail})",
                                         dry_run, False))
                    continue

                logs.observed(run_id, dry_run=dry_run, campaign_id=cid,
                              msg=f"the campaign is "
                                  f"{writes.STATE_WORDS.get(current_state, current_state or 'in an unknown state')}"
                                  f" · its budget is {writes.money(current)}")

                # ── The activation branch (docs/campaign-manager.md §6) ──
                # A stopped campaign that should be running is restarted, and the restart
                # CARRIES the budget — so it replaces the budget write rather than preceding
                # it. That is the whole reason activation lives in this engine.
                if want_state == "running" and current_state == "paused":
                    outcome: dict = {}
                    ok = await _restart(adapter, client, run_id, cid, target, detail,
                                        dry_run, tenant_id, platform, patches, outcome)
                    applied += int(ok)
                    skipped += int(not ok)
                    action, success, said = _verdict(
                        ok, outcome, f"{why} — the campaign was stopped, so it is started "
                                     f"again at that budget")
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                         action, None, target, said, dry_run, success,
                                         kind="activation"))
                    landed = ok
                    continue

                # Blinkit rejects a budget UPDATE on a STOPPED campaign (it reports
                # `allowed_transitions: ['RESTART']`), so the budget write is gated on status.
                # `held` (ON_HOLD) explicitly DOES accept one and reports `['UPDATE']`: it means
                # Blinkit paused delivery because the budget ran out, so the campaign is live
                # and raising its budget is precisely what revives it. Skipping those was
                # backwards — it withheld the one write that would have helped.
                # The STOP is not gated at all — see below.
                can_write_budget = current_state in (None, "running", "held")

                state_words = writes.STATE_WORDS.get(current_state, current_state)
                if not can_write_budget and want_state != "paused":
                    # Stopped (and not due to start), completed, draft… nothing useful to do,
                    # and nothing at risk in doing nothing. Recorded all the same: this is a
                    # decision a window EDGE made (a revert that could not happen), not an
                    # idle poll, so it fires once per window — and "why is my budget still at
                    # the window's value" has no other answer on the page.
                    unwritable = (f"{platform.title()} does not take a budget change on a "
                                  f"campaign that is {state_words}")
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, level="warning",
                                 msg=f"{unwritable}, so nothing is written")
                    skipped += 1
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname, "skip",
                                         current, target,
                                         f"{why} — but {unwritable}, so the budget stays at "
                                         f"{writes.money(current)}", dry_run, True))
                    landed = True              # nothing at risk, so nothing left to tear down
                    continue

                budget_landed = True
                budget_reason = why
                budget_success = True
                if can_write_budget and writes.is_noop(target, current):
                    # Said here, in the engine's own voice, because it is the most common
                    # outcome of all: the hourly poll finding everything already correct.
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid,
                                 msg=f"the budget is already {writes.money(current)}, so "
                                     f"there is nothing to change")
                if can_write_budget:
                    # recent_writes=0 in dry-run (nothing real is counted); real count is wired
                    # for live mode (V5), where the rate-limit guardrail actually gates writes.
                    outcome: dict = {}
                    ok = await writes.apply_budget(
                        adapter, client, run_id=run_id, campaign_id=cid,
                        target=target, current=current, dry_run=dry_run, recent_writes=0,
                        applied=patches, outcome=outcome,
                    )
                    action, budget_success, budget_reason = _verdict(ok, outcome, why)
                    applied += int(ok)
                    skipped += int(not ok)
                    budget_landed = ok or current == target
                else:
                    ok, action = False, "skip"
                    budget_reason = (f"{why} — but {platform.title()} does not take a budget "
                                     f"change on a campaign that is {state_words}, so the "
                                     f"budget stays at {writes.money(current)}")
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, level="warning",
                                 msg=f"the budget cannot be changed on a campaign that is "
                                     f"{state_words} — stopping it anyway")

                # Revert the budget FIRST, then stop (AD6): if the stop fails the campaign
                # runs on at its DEFAULT budget rather than the elevated one, which bounds
                # the overnight overspend. It also leaves a stopped campaign resting at its
                # default, so a manual restart from Blinkit's dashboard — which pre-fills
                # from the stored budget — doesn't bring it back hot.
                stop_landed = True
                if want_state == "paused":
                    # The stop is attempted whatever the status read said and even if the
                    # revert above failed. Skipping a stop because the status was unfamiliar is
                    # how campaign 574687 was left serving at its window budget on 2026-08-08:
                    # Blinkit reported the transient post-restart `SCHEDULED`, the engine
                    # didn't recognise it, and quietly did nothing. Failing to START a campaign
                    # is cheap; failing to STOP one costs money every hour. The transition
                    # table in writes.apply_status is the single place allowed to refuse
                    # (held / ended / already-stopped), and it logs when it does.
                    #
                    # AD6 is about the ORDER of revert-then-stop, not about making the stop
                    # conditional on the revert succeeding.
                    stop_outcome: dict = {}
                    stopped_ok = await writes.apply_status(
                        adapter, client, run_id=run_id, campaign_id=cid, target="paused",
                        current=current_state, dry_run=dry_run, applied=patches,
                        outcome=stop_outcome,
                        recent_writes=0 if dry_run else await repo.recent_write_count(
                            tenant_id, cid, window_minutes=config.RATE_WINDOW_MINUTES,
                            kind="activation"),
                    )
                    # Log BOTH outcomes and count them. A stop that was refused or failed used
                    # to write nothing and move no counter, so the run summary read clean while
                    # the campaign kept serving all night — the one failure that most needs to
                    # be visible was the one that was invisible.
                    applied += int(stopped_ok)
                    skipped += int(not stopped_ok)
                    stop_action, stop_success, stop_said = _verdict(
                        stopped_ok, stop_outcome,
                        "this automation has ended, so the campaign is stopped" if final
                        else "the window ended, so the campaign is stopped until the next one")
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                         stop_action, None, None, stop_said, dry_run,
                                         stop_success, kind="activation"))
                    # A campaign that is already stopped, or completed, is a stop that landed.
                    stop_landed = stopped_ok or current_state in ("paused", "ended")
                # A no-op (budget already correct — the common case for the hourly poll) is
                # narrated to Cloud Logging via `logs.decision` above, but NOT written to the
                # History table: hundreds of "nothing changed" rows would bury the real changes
                # (D6 — verbose narration goes to logs, History holds actual actions only).
                if action != "no-op":
                    log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                         action, current, target, budget_reason, dry_run,
                                         budget_success))
                landed = budget_landed and stop_landed
            finally:
                # Only a LIVE run can land a teardown — a dry run wrote nothing.
                if not dry_run:
                    if final:
                        if landed:
                            settled[schedule.id] = close
                        else:
                            failed.append(schedule.id)
                    elif reverting and landed and last_close is not None:
                        # The latch: this close has had its revert. Until the NEXT one, the
                        # schedule has nothing to do, so the poll stops touching the campaign.
                        latched[schedule.id] = last_close
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    # One stamp per schedule, final teardowns first: `settled_at` records the most recent
    # close this schedule has been torn down for, whichever kind of close it was.
    stamps = {sid: lifecycle.settle_stamp(c, now) for sid, c in latched.items()}
    stamps.update({sid: lifecycle.settle_stamp(c, now) for sid, c in settled.items()})
    await repo.mark_settled("budget", stamps)
    gave_up = set(await repo.bump_settle_attempts("budget", failed) or ())
    # The lifecycle in History, written with the run's own rows: an automation whose final run
    # landed says it is finished; one that has just run out of retries says it was left as is.
    for schedule, _rules in schedules:
        if schedule.id in settled:
            action, reason = lifecycle.SETTLED, lifecycle.settled_reason("budget")
        elif schedule.id in gave_up:
            action, reason = lifecycle.SETTLE_FAILED, lifecycle.settle_failed_reason("budget")
        else:
            continue
        log_rows.append(lifecycle.history_row(
            tenant_id=tenant_id, platform=platform, run_id=run_id, kind="budget",
            action=action, campaign_id=schedule.campaign_id,
            campaign_name=schedule.campaign_name, reason=reason, timestamp=now_ist(),
            success=action == lifecycle.SETTLED))
    await repo.write_run_log(log_rows)
    await repo.record_applied(tenant_id, platform, patches)
    logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run, unit="campaigns",
                     processed=processed, applied=applied, skipped=skipped, errors=errors,
                     seconds=(now_ist() - started).total_seconds())
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


async def _restart(adapter, client, run_id, campaign_id, budget, detail, dry_run,
                   tenant_id, platform, patches: list | None = None,
                   outcome: dict | None = None) -> bool:
    """Bring a stopped campaign back, at `budget`.

    Split out because a restart is the heavy direction: Blinkit re-submits the whole
    campaign, so `overwrites` (AD9) records what the call will rewrite — keywords, bids,
    pids — making a silently-reverted bid visible in the logs instead of discoverable
    weeks later in a report.
    """
    from campaign_manager.marketplaces.blinkit import restart as restart_mod

    return await writes.apply_status(
        adapter, client, run_id=run_id, campaign_id=campaign_id, target="running",
        current="paused", dry_run=dry_run, budget=budget, applied=patches, outcome=outcome,
        overwrites=restart_mod.overwrites(detail, budget=budget),
        recent_writes=0 if dry_run else await repo.recent_write_count(
            tenant_id, campaign_id, window_minutes=config.RATE_WINDOW_MINUTES,
            kind="activation"),
    )


async def _record_run_blocked(tenant_id, platform: str, run_id: str, schedules,
                              reason: str, dry_run: bool) -> None:
    """A History row per campaign when a budget run cannot start at all.

    The same silent gap the bid engine had: the run dies at `setup()` having written
    nothing, so History shows the budget simply not changing, with no row saying why.
    """
    if not schedules:
        return
    rows = [_row(tenant_id, platform, run_id, sched.campaign_id, sched.campaign_name,
                 "error", None, None, reason, dry_run, False)
            for sched, _ in schedules if sched.state == "active"]
    try:
        await repo.write_run_log(rows)
    except Exception as e:                     # bookkeeping must never mask the real fault
        logs.note(run_id, f"could not record why the run was blocked: {e}", dry_run=dry_run)


def _row(tenant_id, platform, run_id, cid, cname, action, old, new, reason, dry_run,
         success, *, kind: str = "budget") -> dict:
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": kind,
        "campaign_id": cid, "campaign_name": cname, "keyword": None, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success,
    }
