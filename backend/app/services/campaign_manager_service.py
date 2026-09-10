"""Business logic for the Campaign Manager v2 API — routes stay thin (§0 / D2).

Orchestrates the `campaign_manager` domain layer (`repo`) + the jobs queue. Every rule
mutation enqueues `cm.reconcile` (so the VM rewrites `job_schedules`); on-demand actions
enqueue a job and return its id to poll. **No Playwright** — only DB rows + enqueue.

Convention: functions return schema DTOs (or None for not-found / access-denied, which the
route maps to 404); a `DuplicateActiveJob` from the queue propagates for the route to 409.
"""
import uuid
from datetime import datetime, timedelta

from app.models.job import Job
from app.schemas.campaign_manager import (
    BidContextOut, KeywordBidRange, TargetedCity,
    BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn, BudgetRuleOut, BudgetRuleUpdate,
    BudgetScheduleIn, BudgetScheduleOut, BudgetScheduleUpdate, CmJobOut, RunLogOut,
)
from app.utils.time import now_ist
from campaign_manager import repo
# Pure window-matching from the engines — reused so the UI status is the SAME logic the
# engines act on (get_adapter is lazy, so this pulls no Playwright — the app-layer rule holds).
from campaign_manager.bid import _in_window, _rule_dict as _bid_dict
from campaign_manager.budget import _matches_rule, _rule_to_dict
from jobs.queue import enqueue

PLATFORM = "blinkit"


class EditError(ValueError):
    """A rejected edit (e.g. editing a spent one-time rule) — the route maps it to 400."""


class StateError(ValueError):
    """The action is fine, the automation is just not in a state where it makes sense —
    resuming one that is already running, pausing one that has ended, resetting one that
    the optimizer will bid straight back up. Mapped to 409, not 400: nothing about the
    REQUEST is wrong, and the same call may well succeed a minute later."""


# ── helpers ─────────────────────────────────────────────────────────────────

async def _reconcile(session, tenant_id: uuid.UUID) -> None:
    """Enqueue a live reconcile so the VM rewrites this tenant's job_schedules. A queued
    reconcile already covers later edits (it reads current rules at run time)."""
    from jobs.queue import DuplicateActiveJob
    try:
        await enqueue(session, job_type="cm.reconcile", tenant_id=tenant_id, params={"live": "true"})
    except DuplicateActiveJob:
        pass


async def _reapply(session, tenant_id: uuid.UUID, job_type: str) -> None:
    """After an edit, land the change on Blinkit NOW (not at the next scheduled fire) by
    enqueuing an engine run. Only when armed — a dry run writes nothing, so there'd be
    nothing to apply immediately."""
    if not await repo.get_armed(tenant_id, PLATFORM):
        return
    from jobs.queue import DuplicateActiveJob
    try:
        await enqueue(session, job_type=job_type, tenant_id=tenant_id, params={"live": "true"})
    except DuplicateActiveJob:
        pass


# ── Status (computed, so the UI shows Running / Scheduled / Ended, not raw state) ──

def _hhmm(value: str | None) -> tuple[int, int] | None:
    try:
        h, m = value.split(":")[:2]
        return int(h), int(m)
    except (AttributeError, TypeError, ValueError):
        return None


def _once_window_end(date_: str, start_time: str | None, end_time: str | None) -> datetime:
    """When a one-time rule's window actually closes (overnight-aware)."""
    base = datetime.strptime(date_, "%Y-%m-%d")
    eh, sh = _hhmm(end_time), _hhmm(start_time) or (0, 0)
    if eh is None:
        return base + timedelta(days=1)          # no end time → runs to midnight
    end = base.replace(hour=eh[0], minute=eh[1])
    return end + timedelta(days=1) if eh <= sh else end   # overnight tail


def _expired(*, type_: str, date: str | None, end_date: str | None,
             start_time: str | None = None, end_time: str | None = None) -> bool:
    """Has this rule finished for good?

    For a `once` rule that means its WINDOW has closed, not merely that its date has
    passed. Checking only `date < today` left a one-time automation reading "Scheduled"
    for the rest of the day after it had already run and reverted — which is exactly how
    a spent rule looked like an upcoming one in the Scheduled pane.
    """
    now = now_ist()
    if type_ == "once":
        if not date:
            return False
        try:
            return _once_window_end(date, start_time, end_time) <= now
        except ValueError:                       # unparseable date — don't claim it ended
            return False
    return bool(end_date and end_date < now.strftime("%Y-%m-%d"))


def _budget_rule_status(r, now) -> str:
    if _matches_rule(_rule_to_dict(r), now):
        return "running"
    if _expired(type_=r.type, date=r.date, end_date=r.end_date,
                start_time=r.start_time, end_time=r.end_time):
        return "ended"
    return "scheduled"


def _budget_status(schedule, rules, now) -> str:
    if schedule.state != "active":
        return schedule.state                    # stopped
    if not rules:
        return "scheduled"                        # default-only, always enforcing
    st = [_budget_rule_status(r, now) for r in rules]
    if "running" in st:
        return "running"
    return "ended" if all(s == "ended" for s in st) else "scheduled"


def _bid_status(r, now) -> str:
    # A paused rule reports `paused` even if its window has since ended — the state the
    # user chose outranks the calendar. The lifecycle gates in pause/resume/reset read
    # `state` and `_bid_ended()` directly and never this, precisely because of that.
    if r.state != "active":
        return r.state                            # paused (the raw value, whatever it is)
    if _in_window(_bid_dict(r), now):
        return "running"
    if _expired(type_=r.type, date=r.date, end_date=r.stop_date,
                start_time=r.start_time, end_time=r.stop_time):
        return "ended"
    return "scheduled"


def _schedule_out(schedule, rules, now=None) -> BudgetScheduleOut:
    now = now or now_ist()
    rule_outs = []
    for r in rules:
        ro = BudgetRuleOut.model_validate(r)
        ro.status = _budget_rule_status(r, now)
        rule_outs.append(ro)
    return BudgetScheduleOut(
        id=schedule.id, campaign_id=schedule.campaign_id, campaign_name=schedule.campaign_name,
        name=schedule.name, default_budget=schedule.default_budget, state=schedule.state,
        stop_after_window=schedule.stop_after_window,
        status=_budget_status(schedule, rules, now), platform=schedule.platform, rules=rule_outs,
    )


def _bid_out(r, now=None) -> BidRuleOut:
    o = BidRuleOut.model_validate(r)
    o.status = _bid_status(r, now or now_ist())
    return o


# ── Budget schedules + rules ────────────────────────────────────────────────

async def list_budget_schedules(tenant_id: uuid.UUID) -> list[BudgetScheduleOut]:
    pairs = await repo.get_budget_schedules(tenant_id, PLATFORM)
    return [_schedule_out(s, rules) for s, rules in pairs]


async def create_budget_schedule(session, tenant_id: uuid.UUID, body: BudgetScheduleIn) -> BudgetScheduleOut:
    s = await repo.create_budget_schedule(
        tenant_id, PLATFORM, body.campaign_id,
        body.campaign_name or f"campaign {body.campaign_id}", body.default_budget, body.name,
        stop_after_window=body.stop_after_window,
    )
    rules = [await repo.add_budget_rule(s.id, **body.rule.model_dump())] if body.rule else []
    await _reconcile(session, tenant_id)
    return _schedule_out(s, rules)


async def delete_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int) -> bool:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return False
    await repo.delete_budget_schedule(schedule_id)
    await _reconcile(session, tenant_id)
    return True


async def add_budget_rule(session, tenant_id: uuid.UUID, schedule_id: int,
                          body: BudgetRuleIn) -> BudgetRuleOut | None:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    r = await repo.add_budget_rule(schedule_id, **body.model_dump())
    await _reconcile(session, tenant_id)
    return BudgetRuleOut.model_validate(r)


async def _fresh_schedule(tenant_id: uuid.UUID, schedule_id: int) -> BudgetScheduleOut | None:
    now = now_ist()
    for s, rules in await repo.get_budget_schedules(tenant_id, PLATFORM):
        if s.id == schedule_id:
            return _schedule_out(s, rules, now)
    return None


async def update_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int,
                                 body: BudgetScheduleUpdate) -> BudgetScheduleOut | None:
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    if fields:
        await repo.update_budget_schedule(schedule_id, fields)
    await _reconcile(session, tenant_id)
    await _reapply(session, tenant_id, "cm.budget_scheduler")     # new default/amount applies now
    return await _fresh_schedule(tenant_id, schedule_id)


async def update_budget_rule(session, tenant_id: uuid.UUID, rule_id: int,
                             body: BudgetRuleUpdate) -> BudgetScheduleOut | None:
    r = await repo.get_budget_rule(rule_id)
    if not r:
        return None
    s = await repo.get_budget_schedule(r.schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    # Deliberately WITHOUT start/end times: this guard is about the DATE. Passing the
    # times would block rescheduling a spent one-time rule to later the SAME day, which is
    # the most natural correction to make.
    if _expired(type_=fields.get("type", r.type), date=fields.get("date", r.date),
                end_date=fields.get("end_date", r.end_date)):
        raise EditError("This one-time window has already ended — change its date to reschedule it.")
    if fields:
        await repo.update_budget_rule(rule_id, fields)
    await _reconcile(session, tenant_id)
    await _reapply(session, tenant_id, "cm.budget_scheduler")
    return await _fresh_schedule(tenant_id, s.id)


async def delete_budget_rule(session, tenant_id: uuid.UUID, rule_id: int) -> bool:
    r = await repo.get_budget_rule(rule_id)
    if r:
        s = await repo.get_budget_schedule(r.schedule_id)
        if not s or s.tenant_id != tenant_id:
            return False
    await repo.delete_budget_rule(rule_id)
    await _reconcile(session, tenant_id)
    return True


async def reset_budget_schedule(session, tenant_id: uuid.UUID, schedule_id: int) -> uuid.UUID | None:
    """D19 Budget Reset: stop + set the campaign back to its default budget. Returns the
    reset job's id, or None if the schedule isn't the caller's."""
    s = await repo.get_budget_schedule(schedule_id)
    if not s or s.tenant_id != tenant_id:
        return None
    await repo.set_budget_state(schedule_id, "stopped")
    armed = await repo.get_armed(tenant_id, PLATFORM)      # cutover: write live when armed

    # AD10 — on a stop-after-window schedule, Reset must also bring the campaign BACK.
    # We may have stopped it at the last window end, and "undo the automation" that
    # silently leaves the campaign dark is the opposite of what anyone expects. The
    # restart carries the default budget, so it replaces the set-budget job rather than
    # running alongside it.
    if s.stop_after_window:
        params = {"campaign": str(s.campaign_id), "status": "running",
                  "budget": str(s.default_budget)}
        if armed:
            params["live"] = "true"
        job = await enqueue(session, job_type="cm.set_activation",
                            tenant_id=tenant_id, params=params)
    else:
        params = {"campaign": str(s.campaign_id), "budget": str(s.default_budget)}
        if armed:
            params["live"] = "true"
        job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
    await _reconcile(session, tenant_id)
    return job.id


# ── Bid rules + D19 lifecycle ───────────────────────────────────────────────

async def list_bid_rules(tenant_id: uuid.UUID) -> list[BidRuleOut]:
    now = now_ist()
    pairs = await repo.get_bid_rules(tenant_id, PLATFORM)
    return [_bid_out(r, now) for r, _rt in pairs]


async def get_bid_context(tenant_id: uuid.UUID, campaign_id: int) -> BidContextOut:
    """Everything the bid-rule form needs about one campaign (V7.4) — DB only, no Blinkit.

    An unscraped campaign returns an empty shell with `scraped_at=None` rather than a 404:
    the form then behaves exactly as it did before V7 (free city input, no bid prefill),
    which is the right answer for a campaign created since the last scrape. Blocking would
    make a brand-new campaign unautomatable for a day.
    """
    campaign, keywords = await repo.get_bid_context(tenant_id, campaign_id, PLATFORM)
    if campaign is None:
        return BidContextOut(campaign_id=campaign_id)

    cities: list[TargetedCity] = []
    for c in campaign.cities or []:
        name = c.get("name") if isinstance(c, dict) else None
        if not name:
            continue
        # Each targeted city is resolved to the store a rule would actually measure at, so
        # the form can say "no dark store in our catalog for X" up front instead of letting
        # someone save a rule that silently has no measurement point.
        store = await repo.resolve_store(PLATFORM, city=name)
        lat, lon, label = store if store else (None, None, None)
        cities.append(TargetedCity(id=c.get("id"), name=name,
                                   location_name=label, lat=lat, lon=lon))

    return BidContextOut(
        campaign_id=campaign_id,
        campaign_type=campaign.type,
        scraped_at=campaign.scraped_at,
        region_type=campaign.region_type,
        cities=cities,
        keywords=[KeywordBidRange.model_validate(k, from_attributes=True) for k in keywords],
        daily_budget=campaign.daily_budget,
        pacing_type=campaign.pacing_type,
        billed_amount=campaign.billed_amount,
    )


async def _check_bid_floor(tenant_id: uuid.UUID, campaign_id: int, keyword: str,
                           match_type: str, min_bid: int | None) -> None:
    """Refuse a rule whose `min_bid` sits below the floor Blinkit publishes (V7.5).

    This is the SAVE-time check and it reads the last scrape, so it is a convenience, not
    the authority — the engine re-checks live at write time, where the number cannot be
    stale. It exists to keep an unworkable rule out of the DB and to explain why at the
    moment someone types it, rather than in a job log the next morning.

    Silent when we have no scraped floor: "unknown" must never read as "rejected".
    """
    if min_bid is None:
        return
    floor = await repo.get_keyword_floor(tenant_id, campaign_id, keyword, match_type, PLATFORM)
    if floor is not None and min_bid < floor:
        raise EditError(
            f"Blinkit's minimum bid for “{keyword}” is ₹{floor} — a min bid of ₹{min_bid} "
            f"would be raised to ₹{floor} on the first write. Set ₹{floor} or more."
        )


async def create_bid_rule(session, tenant_id: uuid.UUID, body: BidRuleIn) -> BidRuleOut:
    d = body.model_dump()
    await _check_bid_floor(tenant_id, body.campaign_id, body.keyword,
                           body.match_type, body.min_bid)
    # Resolve the measurement location from a city / store id when lat/lon weren't given.
    city, location_id = d.pop("city", None), d.pop("location_id", None)
    if (d.get("lat") is None or d.get("lon") is None) and (city or location_id):
        store = await repo.resolve_store(PLATFORM, city=city, location_id=location_id)
        if store:
            d["lat"], d["lon"], label = store
            d["location_name"] = d.get("location_name") or label
    r = await repo.create_bid_rule(
        tenant_id, PLATFORM, d.pop("campaign_id"),
        d.pop("campaign_name") or f"campaign {body.campaign_id}",
        d.pop("keyword"), d.pop("target_position"), d.pop("min_bid"), d.pop("max_bid"), **d,
    )
    await _reconcile(session, tenant_id)
    return _bid_out(r)


async def update_bid_rule(session, tenant_id: uuid.UUID, rule_id: str,
                          body: BidRuleUpdate) -> BidRuleOut | None:
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    fields = body.model_dump(exclude_unset=True)
    # Reject editing a spent one-time rule unless the edit moves its date into the future.
    # Date-only on purpose — see the note in update_budget_rule.
    if _expired(type_=fields.get("type", r.type), date=fields.get("date", r.date),
                end_date=fields.get("stop_date", r.stop_date)):
        raise EditError("This one-time window has already ended — change its date to reschedule it.")
    # The floor applies to whatever the rule will BE after the edit, not to what was
    # sent — changing the keyword alone can drop an unchanged min_bid below its new floor.
    await _check_bid_floor(tenant_id, r.campaign_id,
                           fields.get("keyword", r.keyword),
                           fields.get("match_type", r.match_type),
                           fields.get("min_bid", r.min_bid))
    # `city`/`location_id` re-resolve the measurement lat/lon (same as create).
    city, location_id = fields.pop("city", None), fields.pop("location_id", None)
    if city or location_id:
        store = await repo.resolve_store(PLATFORM, city=city, location_id=location_id)
        if store:
            fields["lat"], fields["lon"], fields["location_name"] = store
    if fields:
        await repo.update_bid_rule(rule_id, fields)
    await _reconcile(session, tenant_id)
    r = await repo.get_bid_rule(rule_id)
    if _in_window(_bid_dict(r), now_ist()):          # editing a live window → apply now
        await _reapply(session, tenant_id, "cm.bid_optimizer")
    return _bid_out(r)


async def delete_bid_rule(session, tenant_id: uuid.UUID, rule_id: str, *,
                          reset: bool = False) -> bool:
    """Delete an automation, optionally putting its bid back to the floor first.

    Order matters. The reset is enqueued BEFORE the rule goes, so a refused enqueue leaves
    the rule (and its bid) exactly as they were rather than orphaning a high bid with no
    automation left to bring it down. The job itself carries plain values, so it does not
    care that the rule is gone by the time it runs.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return False
    if reset:
        await _enqueue_bid_reset(session, tenant_id, r)
    await repo.delete_bid_rule(rule_id)
    await _reconcile(session, tenant_id)
    return True


# ── Pause / Resume / Reset ──────────────────────────────────────────────────
#
# A bid rule is `active` or `paused` — there is no third state. Pause was always
# mechanically identical to the old `stopped` (every engine check is `state == "active"`),
# so keeping both meant two words for one behaviour and a Stop button that could not be
# undone. Removed 2026-09-07.

def _bid_ended(r) -> bool:
    """Has this automation's last window already passed? Nothing will fire for it again, so
    pause and resume are meaningless — but Reset is NOT: a rule paused across its window
    end never got its end-of-window de-escalation, and its bid is still sitting high."""
    return _expired(type_=r.type, date=r.date, end_date=r.stop_date,
                    start_time=r.start_time, end_time=r.stop_time)


async def pause_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> BidRuleOut | None:
    """Freeze the automation: no optimizer ticks, no end-of-window reset, no writes at all.

    The bid is deliberately left where it is — pausing is not a decision about price. Use
    Reset (allowed on a paused rule) to bring it back to the floor.

    Runtime is NOT cleared here. `updated_at` decides whether the window counts as opened,
    and Resume needs it intact; everything stale is cleared then, when we know what we are
    resuming into.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "paused":
        raise StateError("This automation is already paused.")
    if _bid_ended(r):
        raise StateError("This automation has already ended, so there is nothing to pause.")
    r = await repo.set_bid_state(rule_id, "paused")
    await _reconcile(session, tenant_id)
    return _bid_out(r)


async def resume_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> BidRuleOut | None:
    """Un-freeze, and make the engine decide from CURRENT facts rather than pre-pause ones.

    Two things happen:

    1. **Every learned value is cleared** (`repo.clear_bid_runtime`) — last bid, last
       position, the drift pause, the escalation step, a relaxed target. A rule paused for
       six hours knows nothing useful about the auction, and each of those is an input to a
       decision. `updated_at` is kept, which is what makes the window behaviour correct
       with no special-casing: resumed inside the same window → carry on from the live bid;
       resumed after a new window has started → the next tick re-opens at the floor.

    2. **A window that ended during the pause is repaired.** Pausing removes the
       end-of-window reset, so if the window has since closed the bid is still at whatever
       the optimizer climbed to. Resume enqueues that reset itself.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "active":
        raise StateError("This automation is already running.")
    if _bid_ended(r):
        raise StateError("This automation has already ended — change its dates to run it again.")
    await repo.clear_bid_runtime(rule_id)
    r = await repo.set_bid_state(rule_id, "active")
    await _reconcile(session, tenant_id)
    if not _in_window(_bid_dict(r), now_ist()):
        await _enqueue_bid_reset(session, tenant_id, r)
    return _bid_out(r)


async def reset_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> uuid.UUID | None:
    """Put this automation's keyword back to its floor now. Returns the job id to poll.

    Refused only while the rule is RUNNING (active and inside its window) — there the next
    tick would undo it within 15 minutes, so refusing says so instead of spending a write
    that gets reverted. Allowed while paused, before a window opens, and after a rule has
    ended: that last case is the one that matters, because a rule paused across its window
    end never got its de-escalation and Resume is not available to repair it.
    """
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    if r.state == "active" and _in_window(_bid_dict(r), now_ist()):
        raise StateError(
            "This automation is running right now — pause it first, or the next check "
            "will bid it straight back up.")
    return await _enqueue_bid_reset(session, tenant_id, r)


async def _enqueue_bid_reset(session, tenant_id: uuid.UUID, rule) -> uuid.UUID:
    """Queue the one write that Reset (and Delete-with-reset) performs.

    `priority=10` against a default of 100: the queue claims by `(priority, scheduled_for)`,
    so a reset a person is waiting on jumps any scheduled work already pending in the lane.
    The lane itself (`cm_ops`) is what keeps it from queueing behind a bid-optimizer tick —
    see the job registry.
    """
    from jobs.queue import DuplicateActiveJob
    # The rule's OWN marketplace, not this service's `PLATFORM` default. The rest of the
    # CM API is Blinkit-only, but `get_bid_rule` looks up by id and does not filter — so a
    # Zepto rule reaching here would otherwise be enqueued as a Blinkit job (the argv
    # builder defaults `marketplace` to blinkit) and armed against Blinkit's `live_armed`.
    # That means a Zepto campaign id, sent to the wrong ad account, with real writes on.
    marketplace = getattr(rule, "platform", None) or PLATFORM
    params = {"marketplace": marketplace,
              "campaign": str(rule.campaign_id), "keyword": rule.keyword,
              "cpm": str(rule.min_bid), "match_type": rule.match_type or "EXACT"}
    if await repo.get_armed(tenant_id, marketplace):
        params["live"] = "true"
    try:
        job = await enqueue(session, job_type="cm.set_bid", tenant_id=tenant_id,
                            params=params, priority=10)
    except DuplicateActiveJob:
        # One bid reset per client at a time (`uq_jobs_active`). It is a single write and
        # takes about a minute, so saying "wait" beats silently dropping the second one.
        raise StateError(
            "Another bid reset is already running for this client — try again in a minute.")
    return job.id


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

async def set_budget_now(session, tenant_id: uuid.UUID, campaign_id: int, budget: float) -> uuid.UUID:
    params = {"campaign": str(campaign_id), "budget": str(budget)}
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
    return job.id


async def set_activation_now(session, tenant_id: uuid.UUID, campaign_id: int, status: str,
                             budget: float | None = None) -> uuid.UUID:
    """Enqueue a start/stop of one campaign. Like set_budget_now, the API only queues —
    the VM opens the browser, reads the campaign's real state and runs the guardrails.

    `budget` is passed through only for a resume; leaving it out lets the engine reuse the
    campaign's current budget from a fresh read, which is better than anything the API
    could guess from stale scraped data.
    """
    params = {"campaign": str(campaign_id), "status": status}
    if status == "running" and budget is not None:
        params["budget"] = str(budget)
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_activation", tenant_id=tenant_id, params=params)
    return job.id


async def refresh_campaigns(session, tenant_id: uuid.UUID) -> uuid.UUID:
    """Enqueue a catalogue refresh from the live account. No `live` param — it is a read,
    so it runs the same whether or not the tenant is armed."""
    job = await enqueue(session, job_type="cm.sync_campaigns", tenant_id=tenant_id)
    return job.id


async def run_engine(session, tenant_id: uuid.UUID, job_type: str) -> uuid.UUID:
    """Enqueue a run-now of cm.budget_scheduler / cm.bid_optimizer (dry). Raises
    DuplicateActiveJob if one is already active."""
    job = await enqueue(session, job_type=job_type, tenant_id=tenant_id)
    return job.id


# ── Status + history ────────────────────────────────────────────────────────

async def get_job(session, tenant_id: uuid.UUID, job_id: uuid.UUID) -> CmJobOut | None:
    job = await session.get(Job, job_id)
    if not job or job.tenant_id != tenant_id or not job.job_type.startswith("cm."):
        return None
    return CmJobOut.model_validate(job)


async def history(tenant_id: uuid.UUID, *, kind: str | None, limit: int, offset: int,
                  campaign_id: int | None = None, rule_id: str | None = None,
                  include_unchanged: bool = False):
    """History for the UI. Changes only by default; `include_unchanged` returns every tick,
    which is what a per-automation view wants (see repo.list_run_log)."""
    rows, total = await repo.list_run_log(
        tenant_id, PLATFORM, kind=kind, limit=limit, offset=offset,
        campaign_id=campaign_id, rule_id=rule_id, include_unchanged=include_unchanged)
    return [RunLogOut.model_validate(r) for r in rows], total


# ── Advertiser account (B3) ─────────────────────────────────────────────────

async def get_advertiser(tenant_id: uuid.UUID) -> int | None:
    return await repo.get_advertiser(tenant_id, PLATFORM)


async def set_advertiser(tenant_id: uuid.UUID, advertiser_id: int) -> None:
    await repo.set_advertiser(tenant_id, advertiser_id, PLATFORM)
