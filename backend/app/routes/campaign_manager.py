"""Campaign Manager v2 API — mounted under /clients/{client_id}/campaign-manager.

Thin HTTP handlers (§0 / D2): all logic lives in `campaign_manager_service`; these map
requests to it and results to HTTP. No Playwright, no Blinkit — the service only writes DB
rows and enqueues jobs; browser work runs on the VM.
"""
from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.campaign_manager import (
    AdvertiserIn, AdvertiserOut, BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn,
    BudgetRuleOut, BudgetRuleUpdate, BudgetScheduleIn, BudgetScheduleOut,
    BudgetScheduleUpdate, BidContextOut, CmActionOut, CmActionsPage, CmJobOut, EnqueuedOut, RunLogOut, SetActivationIn,
    SetBudgetIn,
)
from app.schemas.common import Page
from app.services import campaign_manager_service as svc
from app.services.campaign_manager_service import EditError, StateError
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


@router.get("/campaigns/{campaign_id}/bid-context", response_model=BidContextOut)
async def get_bid_context(client: ClientDep, campaign_id: int):
    """What the bid-rule form needs about a campaign: Blinkit's minimum bid per keyword and
    the cities the campaign targets (V7.4). Served from the daily scrape — never 404s, since
    a campaign scraped after its creation is a normal state, not an error."""
    return await svc.get_bid_context(client.id, campaign_id)


@router.post("/bid-rules", response_model=BidRuleOut, status_code=201)
async def create_bid_rule(client: ClientDep, session: SessionDep, body: BidRuleIn):
    try:
        return await svc.create_bid_rule(session, client.id, body)
    except EditError as e:
        # A min_bid below Blinkit's published floor — same 400 mapping as an edit refusal.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


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
async def delete_bid_rule(client: ClientDep, session: SessionDep, rule_id: str,
                          reset: bool = False):
    """Delete an automation. `?reset=true` also puts its keyword back to the floor first —
    otherwise the bid stays wherever the optimizer left it, with no rule left to lower it."""
    try:
        deleted = await svc.delete_bid_rule(session, client.id, rule_id, reset=reset)
    except StateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if not deleted:
        raise _NOT_FOUND


async def _bid_lifecycle(action, client, session, rule_id: str) -> BidRuleOut:
    try:
        rule = await action(session, client.id, rule_id)
    except StateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if rule is None:
        raise _NOT_FOUND
    return rule


@router.post("/bid-rules/{rule_id}/pause", response_model=BidRuleOut)
async def pause_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    """Freeze the automation. The bid is left where it is — pair with `/reset` to lower it."""
    return await _bid_lifecycle(svc.pause_bid_rule, client, session, rule_id)


@router.post("/bid-rules/{rule_id}/resume", response_model=BidRuleOut)
async def resume_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    """Un-freeze, discarding everything the engine learned before the pause. If the window
    closed while it was paused, the end-of-window reset it missed is enqueued now."""
    return await _bid_lifecycle(svc.resume_bid_rule, client, session, rule_id)


@router.post("/bid-rules/{rule_id}/reset", response_model=EnqueuedOut)
async def reset_bid_rule(client: ClientDep, session: SessionDep, rule_id: str):
    """Put the keyword's bid back to the automation's `min_bid` → enqueues the write,
    returns `{job_id}` to poll. **409 while the automation is running** — the next check
    would bid it straight back up."""
    try:
        job_id = await svc.reset_bid_rule(session, client.id, rule_id)
    except StateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if job_id is None:
        raise _NOT_FOUND
    return EnqueuedOut(job_id=job_id)


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

@router.post("/set-budget", response_model=EnqueuedOut)
async def set_budget_now(client: ClientDep, session: SessionDep, body: SetBudgetIn,
                         source: str | None = None):
    try:
        job_id = await svc.set_budget_now(session, client.id, body.campaign_id, body.budget,
                                          source=source)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A set-budget job is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/campaigns/{campaign_id}/activation", response_model=EnqueuedOut)
async def set_activation_now(client: ClientDep, session: SessionDep, campaign_id: int,
                             body: SetActivationIn, source: str | None = None):
    """Start or stop a campaign now. Enqueues a VM job and returns its id to poll.

    `source` (all three on-demand endpoints) names the dashboard surface that asked, so that
    surface can list only its own actions — see `svc.ACTION_SOURCES`.

    The transition guardrails (terminal states, budget bounds, rate limit) run on the VM
    against the campaign's live status — not here — so this endpoint accepts any pair and
    the job reports the refusal.
    """
    try:
        job_id = await svc.set_activation_now(session, client.id, campaign_id,
                                              body.status, body.budget, source=source)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "An activation job is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/campaigns/refresh", response_model=EnqueuedOut)
async def refresh_campaigns(client: ClientDep, session: SessionDep,
                            source: str | None = None):
    """Re-read the account's campaigns + statuses from Blinkit into the catalogue.

    A read-only VM job (one list call, not a marketing scrape). The campaign pickers show
    only campaigns present in the latest sync, so this is also how a campaign created since
    last night's scrape becomes selectable.
    """
    try:
        job_id = await svc.refresh_campaigns(session, client.id, source=source)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A campaign refresh is already active")
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

@router.get("/actions", response_model=CmActionsPage)
async def recent_actions(client: ClientDep, session: SessionDep, source: str | None = None,
                         before: datetime | None = None, limit: int = 20):
    """What this client has recently ASKED FOR — the dashboard's activity list.

    Distinct from `/history`, and the difference is the point. History is `cm_run_log`:
    what the engines DID, written when a run ends, background work included. This is the
    job queue: what a person triggered, visible from the moment it is queued and therefore
    able to say "queued" and "running" — states no history row can ever describe, because
    the rows do not exist until the run is over.

    Person-triggered only: a job type people perform AND no schedule behind this run. The
    hourly engines and the reconciler are excluded — see `svc.recent_actions`.

    `source` narrows it to one surface's own actions (One-time Ops lists only what was
    started from it). Omitted, it returns every person-triggered action — which is what the
    per-row busy state wants, since a clash on a campaign is a clash whichever page caused it.

    Paged by keyset: pass `before` (the `created_at` of the oldest row already shown) for the
    next page. No time window — see `svc.recent_actions`.
    """
    items, has_more = await svc.recent_actions(
        session, client.id, limit=limit, source=source, before=before)
    return CmActionsPage(items=items, has_more=has_more)


@router.get("/jobs/{job_id}", response_model=CmJobOut)
async def get_job(client: ClientDep, session: SessionDep, job_id: uuid.UUID):
    job = await svc.get_job(session, client.id, job_id)
    if job is None:
        raise _NOT_FOUND
    return job


@router.get("/history", response_model=Page[RunLogOut])
async def history(client: ClientDep, pagination: PaginationDep, kind: str | None = None,
                  campaign_id: int | None = None, rule_id: str | None = None,
                  run_id: str | None = None, include_unchanged: bool = False,
                  keyword: str | None = None, success: bool | None = None):
    """What the automations did. **Changes only by default** — the engine now records every
    tick, including the ones where it deliberately did nothing, and a "held at ₹201" row
    every 15 minutes would bury the real changes.

    `include_unchanged=true` returns the full per-tick record: that is the per-automation
    drill-down, where "why has my bid not moved for six hours" is exactly the question, and
    the held ticks carry the answer in `reason` with the `position`/`target` behind it.
    Narrow with `campaign_id` or `rule_id` — or with `run_id` for everything ONE job did,
    which is how a caller finds out whether the change it asked for actually happened (a
    job's `status` only reports that the process exited).

    `kind` may list several (`budget,activation` = one campaign automation's own record);
    `campaign_id` + `keyword` is one keyword automation's; `success=false` is every row that
    did not do what it meant to — refused, failed, or blocked.
    """
    rows, total = await svc.history(
        client.id, kind=kind, limit=pagination.limit, offset=pagination.offset,
        campaign_id=campaign_id, rule_id=rule_id, run_id=run_id,
        include_unchanged=include_unchanged, keyword=keyword, success=success)
    return Page.build(rows, total, pagination)


# ── Advertiser account (B3) ─────────────────────────────────────────────────

@router.get("/advertiser", response_model=AdvertiserOut)
async def get_advertiser(client: ClientDep):
    return AdvertiserOut(advertiser_id=await svc.get_advertiser(client.id))


@router.put("/advertiser", response_model=AdvertiserOut)
async def set_advertiser(client: ClientDep, body: AdvertiserIn):
    await svc.set_advertiser(client.id, body.advertiser_id)
    return AdvertiserOut(advertiser_id=body.advertiser_id)
