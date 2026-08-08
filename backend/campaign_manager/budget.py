"""Budget-scheduler orchestration (MP-agnostic).

For each of a tenant's budget schedules: match the rule that applies *now* (IST) →
compute the target budget (or `default_budget`) → read the current budget → route
through the write choke-point. Dry-run by default (reads happen, no writes).

The rule-matching (`target_for_now` / `_matches_rule`) is a **pure function** —
ported from `ad_campaigns/scheduler.py` (validated v1 logic) and unit-tested in
tests/test_budget_rules.py without Blinkit or the DB.
"""
import uuid
from datetime import datetime, timedelta

from app.core.config import settings
from app.utils.time import now_ist
from campaign_manager import config, logs, repo, writes
from campaign_manager.marketplaces import get_adapter


# ── Pure rule matching (unit-tested) ────────────────────────────────────────

def _current_slot(now: datetime) -> str:
    h = now.hour
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


def _matches_rule(rule: dict, now: datetime) -> bool:
    """Does this rule apply at `now`? (time-of-day gate → date/day against the window's
    START day). An overnight window's post-midnight tail belongs to the day it started,
    so a Sun 16:00–02:00 rule is active until Mon 02:00, and a Fri 00:00–02:00 moment is
    NOT active (that tail belongs to Thursday, which has no window)."""
    current_time = now.strftime("%H:%M")
    start_time = rule.get("start_time")
    end_time = rule.get("end_time")
    overnight = bool(start_time and end_time and end_time <= start_time)

    # ── time-of-day gate (overnight-aware) ──
    if start_time or end_time:
        if overnight:
            # `end_time` is EXCLUSIVE here, exactly as in the non-overnight branch below.
            # It used to be `> end_time`, which made a 19:00–02:00 window still match AT
            # 02:00 — a one-minute overrun that was invisible for budgets (the boundary
            # fire simply re-applied the same value a minute later) but breaks campaign
            # activation outright: the 02:00 fire would compute "still running", never
            # stop the campaign, and no later fire would either, because by 03:00 the
            # window no longer counts as *just ended*. Fixed 2026-08-07.
            if current_time < start_time and current_time >= end_time:
                return False
        else:
            if start_time and current_time < start_time:
                return False
            if end_time and current_time >= end_time:
                return False
    elif rule.get("time_slots") and _current_slot(now) not in rule["time_slots"]:
        return False

    # The overnight tail (past midnight, before the window end) belongs to yesterday.
    in_tail = overnight and current_time < end_time
    eff = (now - timedelta(days=1)) if in_tail else now
    eff_date = eff.strftime("%Y-%m-%d")

    if rule.get("type") == "once":
        return eff_date == (rule.get("date") or "")

    # recurring — date range + weekday, both against the effective (start) day.
    if rule.get("start_date") and eff_date < rule["start_date"]:
        return False
    if rule.get("end_date") and eff_date > rule["end_date"]:
        return False
    days = [d.lower() for d in (rule.get("days") or [])]   # empty = every day
    if not days:
        return True
    return eff.strftime("%A").lower() in days


def _reason(rule: dict) -> str:
    """Human-readable why-this-rule string (for logs + history)."""
    if rule.get("start_time") or rule.get("end_time"):
        time_desc = f"{rule.get('start_time', '00:00')}–{rule.get('end_time', '23:59')}"
    else:
        time_desc = ", ".join(rule.get("time_slots", [])) or "all day"
    if rule.get("type") == "once":
        return f"one-time {rule.get('date', '')} / {time_desc}"
    days_str = ", ".join(rule.get("days", [])) or "every day"
    date_range = ""
    if rule.get("start_date") or rule.get("end_date"):
        date_range = f" ({rule.get('start_date', '')}–{rule.get('end_date', '')})"
    return f"{days_str}{date_range} / {time_desc}"


def target_for_now(default_budget: float, rules: list[dict], now: datetime) -> tuple[float, str]:
    """The budget that should apply right now: the first matching rule's budget, else
    the default. Returns (target, reason)."""
    for rule in rules:
        if _matches_rule(rule, now):
            return rule["budget"], _reason(rule)
    return default_budget, "no active rule — default budget"


# ── Campaign activation (docs/campaign-activation.md) ───────────────────────

def _window_just_ended(rules: list[dict], now: datetime,
                       grace_seconds: int | None = None) -> bool:
    """True when nothing matches now but something did within the last `grace` — i.e.
    this moment IS a window END, rather than merely some moment outside a window.

    That distinction is the whole of AD2. "Stop whenever nothing matches" would stop a
    campaign at times nobody asked for: a schedule created at 14:00 for a 19:00–02:00
    window would have its campaign stopped by the 15:00 safety poll, hours before the
    automation had ever run. Derived from the rules alone — nothing is remembered.

    Probed as an INTERVAL, minute by minute — NOT as a single instant at `now - grace`.
    A point probe silently fails whenever the window is shorter than the grace: a
    15:46–15:49 window fired at 15:49 looks back to 15:44, lands before the window even
    opened, finds no match, and never stops the campaign. That is precisely how campaign
    574687 was left running on 2026-08-08, and a late fire breaks a point probe the same
    way even on a long window.

    The grace is the scheduler's own misfire window, so the two agree on what counts as a
    late fire. Consequence, accepted deliberately: a window-end fire missed while the
    runner was down means no stop that night (R8) — the campaign runs on at its default
    budget until the next window.
    """
    grace = settings.SCHEDULER_MISFIRE_GRACE_SECONDS if grace_seconds is None else grace_seconds
    for minutes_ago in range(1, max(1, int(grace // 60)) + 1):
        if any(_matches_rule(r, now - timedelta(minutes=minutes_ago)) for r in rules):
            return True
    return False


def plan_for_now(default_budget: float, rules: list[dict], now: datetime, *,
                 stop_after_window: bool = False) -> tuple[float, str | None, str]:
    """What should be true for this campaign right now → (budget, state, reason).

    `state` has three answers, and the third matters as much as the other two:
      - `"running"` — a rule is active. Starting is UNCONDITIONAL (AD7): a campaign with
        a budget window is meant to run during it, so finding it stopped and leaving it
        stopped would silently do nothing all evening.
      - `"paused"` — a window just ended and this schedule opted in.
      - `None` — the campaign's status is none of our business at this moment. With the
        toggle off this is the only non-`"running"` answer, so an existing schedule never
        has its status touched at all.

    Pure. `target_for_now` remains the budget-only view of the same decision.
    """
    for rule in rules:
        if _matches_rule(rule, now):
            return rule["budget"], "running", _reason(rule)
    state = "paused" if (stop_after_window and _window_just_ended(rules, now)) else None
    reason = "window ended" if state == "paused" else "no active rule — default budget"
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

async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "budget_scheduler", tenant_id, dry_run=dry_run, platform=platform)

    schedules = await repo.get_budget_schedules(tenant_id, platform)
    if not schedules:
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    processed = applied = skipped = errors = 0
    log_rows: list[dict] = []

    # A session/browser is only set up when there's work — reads happen even in dry-run.
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run)

    # Live runs must pass the account guardrail (B3) before any write.
    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    now = now_ist()  # captured after setup so the time is fresh at a boundary
    try:
        for schedule, rules in schedules:
            if schedule.state != "active":
                continue
            processed += 1
            cid, cname = schedule.campaign_id, schedule.campaign_name
            rule_dicts = [_rule_to_dict(r) for r in rules]
            target, want_state, reason = plan_for_now(
                schedule.default_budget, rule_dicts, now,
                stop_after_window=getattr(schedule, "stop_after_window", False),
            )

            if target is None or target <= 0:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                              verdict="skip", reason=f"non-positive target · {reason}")
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "skip", None, target, reason, dry_run, True))
                continue

            logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                          verdict=f"target ₹{target:g}" + (f" · {want_state}" if want_state else ""),
                          reason=reason)
            try:
                # One call gives status AND budget — Blinkit's campaign LIST is unusable
                # for status (it 400s when any campaign type is disabled for the
                # advertiser, and get_campaigns swallows that into an empty list).
                current_state, current, detail = await adapter.read_campaign(client, cid)
            except Exception as e:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                              verdict="error", reason=f"read failed: {e}")
                errors += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "error", None, target, str(e), dry_run, False))
                continue

            # ── The activation branch (docs/campaign-activation.md §5.2) ──
            # A stopped campaign that should be running is restarted, and the restart
            # CARRIES the budget — so it replaces the budget write rather than preceding
            # it. That is the whole reason activation lives in this engine.
            if want_state == "running" and current_state == "paused":
                ok = await _restart(adapter, client, run_id, cid, target, detail,
                                    dry_run, tenant_id, platform)
                applied += int(ok)
                skipped += int(not ok)
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "apply" if ok else "skip", None, target,
                                     f"restart · {reason}", dry_run, True, kind="activation"))
                continue

            # Blinkit rejects a budget UPDATE on a STOPPED campaign (it reports
            # `allowed_transitions: ['RESTART']`), so the budget write is gated on status.
            # `held` (ON_HOLD) explicitly DOES accept one and reports `['UPDATE']`: it means
            # Blinkit paused delivery because the budget ran out, so the campaign is live
            # and raising its budget is precisely what revives it. Skipping those was
            # backwards — it withheld the one write that would have helped.
            # The STOP is not gated at all — see below.
            can_write_budget = current_state in (None, "running", "held")

            if not can_write_budget and want_state != "paused":
                # Stopped (and not due to start), on hold, completed, draft… nothing useful
                # to do, and nothing at risk in doing nothing.
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, verdict="skip",
                              reason=f"campaign is {current_state} — no budget write")
                skipped += 1
                continue

            if can_write_budget:
                # recent_writes=0 in dry-run (nothing real is counted); real count is wired
                # for live mode (V5), where the rate-limit guardrail actually gates writes.
                ok = await writes.apply_budget(
                    adapter, client, run_id=run_id, campaign_id=cid,
                    target=target, current=current, dry_run=dry_run, recent_writes=0,
                )
                action = "apply" if ok else ("no-op" if current == target else "skip")
                applied += int(ok)
                skipped += int(not ok)
            else:
                ok, action = False, "skip"
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, verdict="skip",
                              reason=f"campaign is {current_state} — no budget write, "
                                     "stopping anyway")

            # Revert the budget FIRST, then stop (AD6): if the stop fails the campaign
            # runs on at its DEFAULT budget rather than the elevated one, which bounds
            # the overnight overspend. It also leaves a stopped campaign resting at its
            # default, so a manual restart from Blinkit's dashboard — which pre-fills
            # from the stored budget — doesn't bring it back hot.
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
                stopped_ok = await writes.apply_status(
                    adapter, client, run_id=run_id, campaign_id=cid, target="paused",
                    current=current_state, dry_run=dry_run,
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
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "apply" if stopped_ok else "skip", None, None,
                                     f"stop · {reason}", dry_run, stopped_ok,
                                     kind="activation"))
            # A no-op (budget already correct — the common case for the hourly poll) is
            # narrated to Cloud Logging via `logs.decision` above, but NOT written to the
            # History table: hundreds of "nothing changed" rows would bury the real changes
            # (D6 — verbose narration goes to logs, History holds actual actions only).
            if action != "no-op":
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     action, current, target, reason, dry_run, True))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_run_log(log_rows)
    logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


async def _restart(adapter, client, run_id, campaign_id, budget, detail, dry_run,
                   tenant_id, platform) -> bool:
    """Bring a stopped campaign back, at `budget`.

    Split out because a restart is the heavy direction: Blinkit re-submits the whole
    campaign, so `overwrites` (AD9) records what the call will rewrite — keywords, bids,
    pids — making a silently-reverted bid visible in the logs instead of discoverable
    weeks later in a report.
    """
    from campaign_manager.marketplaces.blinkit import restart as restart_mod

    return await writes.apply_status(
        adapter, client, run_id=run_id, campaign_id=campaign_id, target="running",
        current="paused", dry_run=dry_run, budget=budget,
        overwrites=restart_mod.overwrites(detail, budget=budget),
        recent_writes=0 if dry_run else await repo.recent_write_count(
            tenant_id, campaign_id, window_minutes=config.RATE_WINDOW_MINUTES,
            kind="activation"),
    )


def _row(tenant_id, platform, run_id, cid, cname, action, old, new, reason, dry_run,
         success, *, kind: str = "budget") -> dict:
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": kind,
        "campaign_id": cid, "campaign_name": cname, "keyword": None, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success,
    }
