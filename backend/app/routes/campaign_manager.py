"""Campaign Manager v2 API — mounted under /clients/{client_id}/campaign-manager.

Thin HTTP handlers (§0 / D2): all logic lives in `campaign_manager_service`; these map
requests to it and results to HTTP. No Playwright, no Blinkit — the service only writes DB
rows and enqueues jobs; browser work runs on the VM.
"""
import uuid

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.campaign_manager import (
    AdvertiserIn, AdvertiserOut, BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn,
    BudgetRuleOut, BudgetRuleUpdate, BudgetScheduleIn, BudgetScheduleOut,
    BudgetScheduleUpdate, CmJobOut, EnqueuedOut, RunLogOut, SetActivationIn, SetBudgetIn,
)
from app.schemas.common import Page
from app.services import campaign_manager_service as svc
from app.services.campaign_manager_service import EditError
from campaign_manager.repo import DuplicateSchedule
from jobs.queue import DuplicateActiveJob

router = APIRouter()

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


# ── Budget schedules + rules ────────────────────────────────────────────────

@router.get("/budget-schedules", response_model=list[BudgetScheduleOut])
async def list_budget_schedules(client: ClientDep):
    return await svc.list_budget_schedules(client.id)


@router.post("/budget-schedules", response_model=BudgetScheduleOut, status_code=201)
async def create_budget_schedule(client: ClientDep, session: SessionDep, body: BudgetScheduleIn):
    try:
        return await svc.create_budget_schedule(session, client.id, body)
    except DuplicateSchedule as e:
        # The UI has always had a message for this; without the mapping it never saw the
        # 409 and showed a generic failure instead.
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.patch("/budget-schedules/{schedule_id}", response_model=BudgetScheduleOut)
async def update_budget_schedule(client: ClientDep, session: SessionDep, schedule_id: int, body: BudgetScheduleUpdate):
    out = await svc.update_budget_schedule(session, client.id, schedule_id, body)
    if out is None:
        raise _NOT_FOUND
    return out


@router.delete("/budget-schedules/{schedule_id}", status_code=204)
async def delete_budget_schedule(client: ClientDep, session: SessionDep, schedule_id: int):
    if not await svc.delete_budget_schedule(session, client.id, schedule_id):
        raise _NOT_FOUND


@router.post("/budget-schedules/{schedule_id}/rules", response_model=BudgetRuleOut, status_code=201)
async def add_budget_rule(client: ClientDep, session: SessionDep, schedule_id: int, body: BudgetRuleIn):
    rule = await svc.add_budget_rule(session, client.id, schedule_id, body)
    if rule is None:
        raise _NOT_FOUND
    return rule


@router.patch("/budget-rules/{rule_id}", response_model=BudgetScheduleOut)
async def update_budget_rule(client: ClientDep, session: SessionDep, rule_id: int, body: BudgetRuleUpdate):
    try:
        out = await svc.update_budget_rule(session, client.id, rule_id, body)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if out is None:
        raise _NOT_FOUND
    return out


@router.delete("/budget-rules/{rule_id}", status_code=204)
async def delete_budget_rule(client: ClientDep, session: SessionDep, rule_id: int):
    if not await svc.delete_budget_rule(session, client.id, rule_id):
        raise _NOT_FOUND


@router.post("/budget-schedules/{schedule_id}/reset", response_model=EnqueuedOut)
async def reset_budget_schedule(client: ClientDep, session: SessionDep, schedule_id: int):
    try:
        job_id = await svc.reset_budget_schedule(session, client.id, schedule_id)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A set-budget job is already active")
    if job_id is None:
        raise _NOT_FOUND
    return EnqueuedOut(job_id=job_id)


# ── Bid rules + D19 buttons ─────────────────────────────────────────────────

@router.get("/bid-rules", response_model=list[BidRuleOut])
async def list_bid_rules(client: ClientDep):
    return await svc.list_bid_rules(client.id)


@router.post("/bid-rules", response_model=BidRuleOut, status_code=201)
async def create_bid_rule(client: ClientDep, session: SessionDep, body: BidRuleIn):
    return await svc.create_bid_rule(session, client.id, body)


@router.patch("/bid-rules/{rule_id}", response_model=BidRuleOut)
async def update_bid_rule(client: ClientDep, session: SessionDep, rule_id: str, body: BidRuleUpdate):
    try:
        rule = await svc.update_bid_rule(session, client.id, rule_id, body)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if rule is None:
        raise _NOT_FOUND
    return rule


@router.delete("/bid-rules/{rule_id}", status_code=204)
async def delete_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    if not await svc.delete_bid_rule(session, client.id, rule_id):
        raise _NOT_FOUND


async def _set_bid_state(client, session, rule_id: str, state: str) -> BidRuleOut:
    rule = await svc.set_bid_state(session, client.id, rule_id, state)
    if rule is None:
        raise _NOT_FOUND
    return rule


@router.post("/bid-rules/{rule_id}/pause", response_model=BidRuleOut)
async def pause_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    return await _set_bid_state(client, session, rule_id, "paused")


@router.post("/bid-rules/{rule_id}/resume", response_model=BidRuleOut)
async def resume_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    return await _set_bid_state(client, session, rule_id, "active")


@router.post("/bid-rules/{rule_id}/stop", response_model=BidRuleOut)
async def stop_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    return await _set_bid_state(client, session, rule_id, "stopped")


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

@router.post("/set-budget", response_model=EnqueuedOut)
async def set_budget_now(client: ClientDep, session: SessionDep, body: SetBudgetIn):
    try:
        job_id = await svc.set_budget_now(session, client.id, body.campaign_id, body.budget)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A set-budget job is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/campaigns/{campaign_id}/activation", response_model=EnqueuedOut)
async def set_activation_now(client: ClientDep, session: SessionDep, campaign_id: int,
                             body: SetActivationIn):
    """Start or stop a campaign now. Enqueues a VM job and returns its id to poll.

    The transition guardrails (terminal states, budget bounds, rate limit) run on the VM
    against the campaign's live status — not here — so this endpoint accepts any pair and
    the job reports the refusal.
    """
    try:
        job_id = await svc.set_activation_now(session, client.id, campaign_id,
                                              body.status, body.budget)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "An activation job is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/run/budget-scheduler", response_model=EnqueuedOut)
async def run_budget_scheduler(client: ClientDep, session: SessionDep):
    try:
        job_id = await svc.run_engine(session, client.id, "cm.budget_scheduler")
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A budget-scheduler run is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/run/bid-optimizer", response_model=EnqueuedOut)
async def run_bid_optimizer(client: ClientDep, session: SessionDep):
    try:
        job_id = await svc.run_engine(session, client.id, "cm.bid_optimizer")
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A bid-optimizer run is already active")
    return EnqueuedOut(job_id=job_id)


# ── Job status (poll) + history ─────────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=CmJobOut)
async def get_job(client: ClientDep, session: SessionDep, job_id: uuid.UUID):
    job = await svc.get_job(session, client.id, job_id)
    if job is None:
        raise _NOT_FOUND
    return job


@router.get("/history", response_model=Page[RunLogOut])
async def history(client: ClientDep, pagination: PaginationDep, kind: str | None = None):
    rows, total = await svc.history(client.id, kind=kind, limit=pagination.limit, offset=pagination.offset)
    return Page.build(rows, total, pagination)


# ── Advertiser account (B3) ─────────────────────────────────────────────────

@router.get("/advertiser", response_model=AdvertiserOut)
async def get_advertiser(client: ClientDep):
    return AdvertiserOut(advertiser_id=await svc.get_advertiser(client.id))


@router.put("/advertiser", response_model=AdvertiserOut)
async def set_advertiser(client: ClientDep, body: AdvertiserIn):
    await svc.set_advertiser(client.id, body.advertiser_id)
    return AdvertiserOut(advertiser_id=body.advertiser_id)
