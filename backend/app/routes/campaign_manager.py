"""Campaign Manager v2 API — mounted under /clients/{client_id}/campaign-manager.

Thin HTTP handlers (§0 / D2): all logic lives in `campaign_manager_service`; these map
requests to it and results to HTTP. No Playwright, no marketplace calls — the service only
writes DB rows and enqueues jobs; browser work runs on the VM.

## The marketplace is part of the address, and has no default (ZC-D1)

Every endpoint is `/campaign-manager/{marketplace}/…` — `blinkit` or `zepto`. There is no
un-prefixed form and nothing falls back to Blinkit (Deepansh, 2026-09-24: "only the intended
marketplace performs ops"). It binds, too: an automation or schedule id that belongs to the
other marketplace is not found under this one, so `…/zepto/…` can never act on a Blinkit
rule. The one exception is `GET /jobs/{job_id}`, a status read Settings polls for jobs that
belong to no marketplace. An old un-prefixed address answers 400 with the new form.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.campaign_manager import (
    AdvertiserIn, AdvertiserOut, BidRuleIn, BidRuleOut, BidRuleUpdate, BudgetRuleIn,
    BudgetRuleOut, BudgetRuleUpdate, BudgetScheduleIn, BudgetScheduleOut,
    BudgetScheduleUpdate, BidContextOut, CmActionOut, CmJobOut, EnqueuedOut, LiveOut,
    RunLogOut, SetActivationIn, SetBudgetIn,
)
from app.schemas.common import Page
from app.services import campaign_manager_service as svc
from app.services.campaign_manager_service import EditError, StateError
from campaign_manager.marketplaces import supported
from campaign_manager.repo import DuplicateBidRule, DuplicateSchedule
from jobs.queue import DuplicateActiveJob

router = APIRouter()


def _marketplace(marketplace: str = Path(
        ..., description="Which marketplace this call acts on: blinkit | zepto. Required.")) -> str:
    slug = marketplace.strip().lower()
    if slug not in supported():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown marketplace {marketplace!r}. Campaign-manager addresses are "
            f"/campaign-manager/<marketplace>/…, where <marketplace> is one of: "
            f"{', '.join(supported())}.")
    return slug


Marketplace = Annotated[str, Depends(_marketplace)]


def _not_found(marketplace: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND,
                         f"Not found among this client's {marketplace.title()} automations.")


# ── Budget schedules + rules ────────────────────────────────────────────────

@router.get("/{marketplace}/budget-schedules", response_model=list[BudgetScheduleOut])
async def list_budget_schedules(client: ClientDep, marketplace: Marketplace):
    return await svc.list_budget_schedules(client.id, marketplace)


@router.post("/{marketplace}/budget-schedules", response_model=BudgetScheduleOut,
             status_code=201)
async def create_budget_schedule(client: ClientDep, session: SessionDep,
                                 marketplace: Marketplace, body: BudgetScheduleIn):
    try:
        return await svc.create_budget_schedule(session, client.id, marketplace, body)
    except DuplicateSchedule as e:
        # The UI has always had a message for this; without the mapping it never saw the
        # 409 and showed a generic failure instead.
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except EditError as e:
        # Wrong marketplace for the campaign, not automatable, or below the minimum budget.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.patch("/{marketplace}/budget-schedules/{schedule_id}", response_model=BudgetScheduleOut)
async def update_budget_schedule(client: ClientDep, session: SessionDep,
                                 marketplace: Marketplace, schedule_id: int,
                                 body: BudgetScheduleUpdate):
    try:
        out = await svc.update_budget_schedule(session, client.id, marketplace, schedule_id,
                                               body)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if out is None:
        raise _not_found(marketplace)
    return out


@router.delete("/{marketplace}/budget-schedules/{schedule_id}", status_code=204)
async def delete_budget_schedule(client: ClientDep, session: SessionDep,
                                 marketplace: Marketplace, schedule_id: int):
    if not await svc.delete_budget_schedule(session, client.id, marketplace, schedule_id):
        raise _not_found(marketplace)


@router.post("/{marketplace}/budget-schedules/{schedule_id}/rules",
             response_model=BudgetRuleOut, status_code=201)
async def add_budget_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                          schedule_id: int, body: BudgetRuleIn):
    try:
        rule = await svc.add_budget_rule(session, client.id, marketplace, schedule_id, body)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if rule is None:
        raise _not_found(marketplace)
    return rule


@router.patch("/{marketplace}/budget-rules/{rule_id}", response_model=BudgetScheduleOut)
async def update_budget_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                             rule_id: int, body: BudgetRuleUpdate):
    try:
        out = await svc.update_budget_rule(session, client.id, marketplace, rule_id, body)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if out is None:
        raise _not_found(marketplace)
    return out


@router.delete("/{marketplace}/budget-rules/{rule_id}", status_code=204)
async def delete_budget_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                             rule_id: int):
    if not await svc.delete_budget_rule(session, client.id, marketplace, rule_id):
        raise _not_found(marketplace)


@router.post("/{marketplace}/budget-schedules/{schedule_id}/reset", response_model=EnqueuedOut)
async def reset_budget_schedule(client: ClientDep, session: SessionDep,
                                marketplace: Marketplace, schedule_id: int):
    try:
        job_id = await svc.reset_budget_schedule(session, client.id, marketplace, schedule_id)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A set-budget job is already active")
    if job_id is None:
        raise _not_found(marketplace)
    return EnqueuedOut(job_id=job_id)


# ── Bid rules + D19 buttons ─────────────────────────────────────────────────

@router.get("/{marketplace}/bid-rules", response_model=list[BidRuleOut])
async def list_bid_rules(client: ClientDep, marketplace: Marketplace):
    return await svc.list_bid_rules(client.id, marketplace)


@router.get("/{marketplace}/campaigns/{campaign_id}/bid-context", response_model=BidContextOut)
async def get_bid_context(client: ClientDep, marketplace: Marketplace, campaign_id: int):
    """What the bid-rule form needs about a campaign: the marketplace's minimum bid per
    keyword, the cities the campaign targets, and whether bids are CPM or CPC (V7.4, D4).
    Served from the daily scrape — never 404s, since a campaign scraped after its creation
    is a normal state, not an error."""
    return await svc.get_bid_context(client.id, marketplace, campaign_id)


@router.post("/{marketplace}/bid-rules", response_model=BidRuleOut, status_code=201)
async def create_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                          body: BidRuleIn):
    try:
        return await svc.create_bid_rule(session, client.id, marketplace, body)
    except DuplicateBidRule as e:
        # A live rule already chases this keyword — same 409 as a duplicate budget schedule,
        # and the message names the rule to edit instead (ZC-C9).
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except EditError as e:
        # Below the published floor, a match type this marketplace lacks, wrong marketplace,
        # not automatable, or nowhere to measure.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.patch("/{marketplace}/bid-rules/{rule_id}", response_model=BidRuleOut)
async def update_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                          rule_id: str, body: BidRuleUpdate):
    try:
        rule = await svc.update_bid_rule(session, client.id, marketplace, rule_id, body)
    except DuplicateBidRule as e:
        # Renamed onto a keyword another live automation already chases (ZC-C9).
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if rule is None:
        raise _not_found(marketplace)
    return rule


@router.delete("/{marketplace}/bid-rules/{rule_id}", status_code=204)
async def delete_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                          rule_id: str, reset: bool = False):
    """Delete an automation. `?reset=true` also puts its keyword back to the floor first —
    otherwise the bid stays wherever the optimizer left it, with no rule left to lower it."""
    try:
        deleted = await svc.delete_bid_rule(session, client.id, marketplace, rule_id,
                                            reset=reset)
    except StateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if not deleted:
        raise _not_found(marketplace)


async def _bid_lifecycle(action, client, session, marketplace: str,
                         rule_id: str) -> BidRuleOut:
    try:
        rule = await action(session, client.id, marketplace, rule_id)
    except (StateError, DuplicateBidRule) as e:
        # DuplicateBidRule: something took this keyword while the automation was paused, so
        # resuming would start a bid fight (ZC-C9).
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if rule is None:
        raise _not_found(marketplace)
    return rule


@router.post("/{marketplace}/bid-rules/{rule_id}/pause", response_model=BidRuleOut)
async def pause_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                         rule_id: str):
    """Freeze the automation. The bid is left where it is — pair with `/reset` to lower it."""
    return await _bid_lifecycle(svc.pause_bid_rule, client, session, marketplace, rule_id)


@router.post("/{marketplace}/bid-rules/{rule_id}/resume", response_model=BidRuleOut)
async def resume_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                          rule_id: str):
    """Un-freeze, discarding everything the engine learned before the pause. If the window
    closed while it was paused, the end-of-window reset it missed is enqueued now."""
    return await _bid_lifecycle(svc.resume_bid_rule, client, session, marketplace, rule_id)


@router.post("/{marketplace}/bid-rules/{rule_id}/reset", response_model=EnqueuedOut)
async def reset_bid_rule(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                         rule_id: str):
    """Put the keyword's bid back to the automation's `min_bid` → enqueues the write,
    returns `{job_id}` to poll. **409 while the automation is running** — the next check
    would bid it straight back up."""
    try:
        job_id = await svc.reset_bid_rule(session, client.id, marketplace, rule_id)
    except StateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    if job_id is None:
        raise _not_found(marketplace)
    return EnqueuedOut(job_id=job_id)


# ── On-demand actions (enqueue → poll) ──────────────────────────────────────

@router.post("/{marketplace}/set-budget", response_model=EnqueuedOut)
async def set_budget_now(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                         body: SetBudgetIn):
    try:
        job_id = await svc.set_budget_now(session, client.id, marketplace, body.campaign_id,
                                          body.budget)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A set-budget job is already active")
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return EnqueuedOut(job_id=job_id)


@router.post("/{marketplace}/campaigns/{campaign_id}/activation", response_model=EnqueuedOut)
async def set_activation_now(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                             campaign_id: int, body: SetActivationIn):
    """Start or stop a campaign now. Enqueues a VM job and returns its id to poll.

    The transition guardrails (terminal states, budget bounds, rate limit) run on the VM
    against the campaign's live status — not here — so this endpoint accepts any pair and
    the job reports the refusal.
    """
    try:
        job_id = await svc.set_activation_now(session, client.id, marketplace, campaign_id,
                                              body.status, body.budget)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "An activation job is already active")
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return EnqueuedOut(job_id=job_id)


@router.post("/{marketplace}/campaigns/refresh", response_model=EnqueuedOut)
async def refresh_campaigns(client: ClientDep, session: SessionDep, marketplace: Marketplace):
    """Re-read the account's campaigns + statuses from the marketplace into the catalogue.

    A read-only VM job (the campaign list, not a full scrape). The campaign pickers show
    only campaigns present in the latest sync, so this is also how a campaign created since
    last night's scrape becomes selectable.
    """
    try:
        job_id = await svc.refresh_campaigns(session, client.id, marketplace)
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A campaign refresh is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/{marketplace}/run/budget-scheduler", response_model=EnqueuedOut)
async def run_budget_scheduler(client: ClientDep, session: SessionDep, marketplace: Marketplace):
    try:
        job_id = await svc.run_engine(session, client.id, marketplace, "cm.budget_scheduler")
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A budget-scheduler run is already active")
    return EnqueuedOut(job_id=job_id)


@router.post("/{marketplace}/run/bid-optimizer", response_model=EnqueuedOut)
async def run_bid_optimizer(client: ClientDep, session: SessionDep, marketplace: Marketplace):
    try:
        job_id = await svc.run_engine(session, client.id, marketplace, "cm.bid_optimizer")
    except DuplicateActiveJob:
        raise HTTPException(status.HTTP_409_CONFLICT, "A bid-optimizer run is already active")
    return EnqueuedOut(job_id=job_id)


# ── Job status (poll) + history ─────────────────────────────────────────────

@router.get("/{marketplace}/actions", response_model=list[CmActionOut])
async def recent_actions(client: ClientDep, session: SessionDep, marketplace: Marketplace):
    """What this client has recently ASKED FOR on this marketplace — the activity list.

    Distinct from `/history`, and the difference is the point. History is `cm_run_log`:
    what the engines DID, written when a run ends, background work included. This is the
    job queue: what a person triggered, visible from the moment it is queued and therefore
    able to say "queued" and "running" — states no history row can ever describe, because
    the rows do not exist until the run is over.

    Person-triggered only: a job type people perform AND no schedule behind this run. The
    hourly engines and the reconciler are excluded — see `svc.recent_actions`.
    """
    return await svc.recent_actions(session, client.id, marketplace)


@router.get("/{marketplace}/jobs/{job_id}", response_model=CmJobOut)
async def get_job(client: ClientDep, session: SessionDep, marketplace: Marketplace,
                  job_id: uuid.UUID):
    """A job this marketplace's actions queued. A job of the other marketplace is not
    found here."""
    job = await svc.get_job(session, client.id, job_id, marketplace=marketplace)
    if job is None:
        raise _not_found(marketplace)
    return job


@router.get("/jobs/{job_id}", response_model=CmJobOut)
async def get_job_any(client: ClientDep, session: SessionDep, job_id: uuid.UUID):
    """Marketplace-free status poll — a READ that changes nothing, kept for Settings, which
    polls jobs that belong to no marketplace. Every action lives under a marketplace."""
    job = await svc.get_job(session, client.id, job_id, marketplace=None)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return job


@router.get("/{marketplace}/history", response_model=Page[RunLogOut])
async def history(client: ClientDep, marketplace: Marketplace, pagination: PaginationDep,
                  kind: str | None = None, campaign_id: int | None = None,
                  rule_id: str | None = None, run_id: str | None = None,
                  include_unchanged: bool = False, keyword: str | None = None,
                  success: bool | None = None):
    """What the automations did on this marketplace. **Changes only by default** — the
    engine now records every tick, including the ones where it deliberately did nothing, and
    a "held at ₹201" row every 15 minutes would bury the real changes.

    `include_unchanged=true` returns the full per-tick record: that is the per-automation
    drill-down, where "why has my bid not moved for six hours" is exactly the question, and
    the held ticks carry the answer in `reason` with the `position`/`target` behind it.
    Narrow with `campaign_id` or `rule_id` — or with `run_id` for everything ONE job did,
    which is how a caller finds out whether the change it asked for actually happened (a
    job's `status` only reports that the process exited).

    `kind` may list several (`budget,activation` = one campaign automation's own record);
    `campaign_id` + `keyword` is one keyword automation's; `success=false` is every row that
    did not do what it meant to — refused, failed, or blocked. `kind=wallet` is the ad-wallet
    warning (Zepto).
    """
    rows, total = await svc.history(
        client.id, marketplace, kind=kind, limit=pagination.limit, offset=pagination.offset,
        campaign_id=campaign_id, rule_id=rule_id, run_id=run_id,
        include_unchanged=include_unchanged, keyword=keyword, success=success)
    return Page.build(rows, total, pagination)


# ── Advertiser account (B3) + live switch ───────────────────────────────────

@router.get("/{marketplace}/advertiser", response_model=AdvertiserOut)
async def get_advertiser(client: ClientDep, marketplace: Marketplace):
    return AdvertiserOut(advertiser_id=await svc.get_advertiser(client.id, marketplace))


@router.put("/{marketplace}/advertiser", response_model=AdvertiserOut)
async def set_advertiser(client: ClientDep, marketplace: Marketplace, body: AdvertiserIn):
    try:
        await svc.set_advertiser(client.id, marketplace, body.advertiser_id)
    except EditError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return AdvertiserOut(advertiser_id=body.advertiser_id)


@router.get("/{marketplace}/live", response_model=LiveOut)
async def get_live(client: ClientDep, marketplace: Marketplace):
    """Whether this marketplace's automations write for real (ZC-D9). Read-only: arming is
    `cm arm -m <marketplace>` on the CLI, deliberately not a button."""
    return LiveOut(marketplace=marketplace, live=await svc.get_live(client.id, marketplace))


# ── An old, un-prefixed address → say what it should be ─────────────────────
#
# Registered LAST so it only catches what nothing above matched. Before ZC-D1 every path
# here had no marketplace; a stale caller would otherwise get a bare 404 and no hint.

@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def _missing_marketplace(rest: str, request: Request):
    first = rest.split("/", 1)[0].lower()
    if first in supported():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No {request.method} /{rest} in the campaign-manager API.")
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"Campaign-manager addresses name their marketplace: /campaign-manager/<marketplace>/"
        f"{rest} with <marketplace> one of {', '.join(supported())}. There is no default.")
