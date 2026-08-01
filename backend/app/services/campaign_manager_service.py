"""Business logic for the Campaign Manager v2 API — routes stay thin (§0 / D2).

Orchestrates the `campaign_manager` domain layer (`repo`) + the jobs queue. Every rule
mutation enqueues `cm.reconcile` (so the VM rewrites `job_schedules`); on-demand actions
enqueue a job and return its id to poll. **No Playwright** — only DB rows + enqueue.

Convention: functions return schema DTOs (or None for not-found / access-denied, which the
route maps to 404); a `DuplicateActiveJob` from the queue propagates for the route to 409.
"""
import uuid

from app.models.job import Job
from app.schemas.campaign_manager import (
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

def _expired(*, type_: str, date: str | None, end_date: str | None) -> bool:
    today = now_ist().strftime("%Y-%m-%d")
    if type_ == "once":
        return bool(date and date < today)
    return bool(end_date and end_date < today)


def _budget_rule_status(r, now) -> str:
    if _matches_rule(_rule_to_dict(r), now):
        return "running"
    if _expired(type_=r.type, date=r.date, end_date=r.end_date):
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
    if r.state != "active":
        return r.state                            # paused / stopped
    if _in_window(_bid_dict(r), now):
        return "running"
    if _expired(type_=r.type, date=r.date, end_date=r.stop_date):
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
    params = {"campaign": str(s.campaign_id), "budget": str(s.default_budget)}
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
    await _reconcile(session, tenant_id)
    return job.id


# ── Bid rules + D19 lifecycle ───────────────────────────────────────────────

async def list_bid_rules(tenant_id: uuid.UUID) -> list[BidRuleOut]:
    now = now_ist()
    pairs = await repo.get_bid_rules(tenant_id, PLATFORM)
    return [_bid_out(r, now) for r, _rt in pairs]


async def create_bid_rule(session, tenant_id: uuid.UUID, body: BidRuleIn) -> BidRuleOut:
    d = body.model_dump()
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
    if _expired(type_=fields.get("type", r.type), date=fields.get("date", r.date),
                end_date=fields.get("stop_date", r.stop_date)):
        raise EditError("This one-time window has already ended — change its date to reschedule it.")
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


async def delete_bid_rule(session, tenant_id: uuid.UUID, rule_id: str) -> bool:
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return False
    await repo.delete_bid_rule(rule_id)
    await _reconcile(session, tenant_id)
    return True


async def set_bid_state(session, tenant_id: uuid.UUID, rule_id: str, state: str) -> BidRuleOut | None:
    r = await repo.get_bid_rule(rule_id)
    if not r or r.tenant_id != tenant_id:
        return None
    r = await repo.set_bid_state(rule_id, state)
    await _reconcile(session, tenant_id)
    return _bid_out(r)


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

async def set_budget_now(session, tenant_id: uuid.UUID, campaign_id: int, budget: float) -> uuid.UUID:
    params = {"campaign": str(campaign_id), "budget": str(budget)}
    if await repo.get_armed(tenant_id, PLATFORM):     # cutover: write live when armed
        params["live"] = "true"
    job = await enqueue(session, job_type="cm.set_budget", tenant_id=tenant_id, params=params)
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


async def history(tenant_id: uuid.UUID, *, kind: str | None, limit: int, offset: int):
    rows, total = await repo.list_run_log(tenant_id, PLATFORM, kind=kind, limit=limit, offset=offset)
    return [RunLogOut.model_validate(r) for r in rows], total


# ── Advertiser account (B3) ─────────────────────────────────────────────────

async def get_advertiser(tenant_id: uuid.UUID) -> int | None:
    return await repo.get_advertiser(tenant_id, PLATFORM)


async def set_advertiser(tenant_id: uuid.UUID, advertiser_id: int) -> None:
    await repo.set_advertiser(tenant_id, advertiser_id, PLATFORM)
