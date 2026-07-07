"""Client-scoped advertising data. Mounted under /clients/{client_id}/ads."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.dependencies import ClientDep, Pagination, SessionDep
from app.schemas.ads import (
    AdPerformancePoint,
    BidOptimizerLogEntry,
    BidOptimizerRule,
    BudgetSchedule,
    CampaignKeyword,
    CampaignProduct,
    CampaignRow,
    CollectionRow,
    ReconnectBlinkitRequest,
    ReconnectBlinkitResponse,
    SchedulerLogEntry,
    SchedulerTriggerResponse,
    SetBudgetRequest,
    SetBudgetResponse,
    SponsoredSovRow,
    VisibilityPlanRow,
)
from app.schemas.common import Page
from app.services import ads_service

router = APIRouter()


@router.get("/campaigns", response_model=Page[CampaignRow])
async def campaigns(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
    status: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
):
    pagination = Pagination(page=page, limit=limit)
    return await ads_service.get_campaigns(
        session, tenant_id=client.id, pagination=pagination, days=days, status=status
    )


@router.get("/performance", response_model=list[AdPerformancePoint])
async def performance(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
):
    return await ads_service.get_performance(session, tenant_id=client.id, days=days)


@router.get("/sov", response_model=list[SponsoredSovRow])
async def sponsored_sov(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
):
    return await ads_service.get_sponsored_sov(session, tenant_id=client.id, days=days)


@router.get("/visibility-plans", response_model=list[VisibilityPlanRow])
async def visibility_plans(session: SessionDep, client: ClientDep):
    return await ads_service.get_visibility_plans(session, tenant_id=client.id)


@router.get("/collections", response_model=list[CollectionRow])
async def collections(session: SessionDep, client: ClientDep):
    return await ads_service.get_collections(session, tenant_id=client.id)


# ── Budget scheduling ─────────────────────────────────────────────────────────

@router.get("/budget-schedules/history", response_model=list[SchedulerLogEntry])
async def scheduler_history(session: SessionDep, client: ClientDep):
    return ads_service.get_scheduler_log()


@router.get("/budget-schedules", response_model=list[BudgetSchedule])
async def get_budget_schedules(session: SessionDep, client: ClientDep):
    return ads_service.get_budget_schedules()


@router.post("/budget-schedules", response_model=BudgetSchedule, status_code=201)
async def add_budget_schedule(body: BudgetSchedule, session: SessionDep, client: ClientDep):
    return ads_service.add_budget_schedule(body.model_dump())


@router.patch("/budget-schedules/{campaign_id}/toggle", response_model=BudgetSchedule)
async def toggle_budget_schedule(campaign_id: int, session: SessionDep, client: ClientDep):
    result = ads_service.toggle_budget_schedule(campaign_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return result


@router.delete("/budget-schedules/{campaign_id}", status_code=204)
async def delete_budget_schedule(campaign_id: int, session: SessionDep, client: ClientDep):
    if not ads_service.remove_budget_schedule(campaign_id):
        raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/budget-schedules/run", response_model=SchedulerTriggerResponse)
async def trigger_scheduler(background_tasks: BackgroundTasks, session: SessionDep, client: ClientDep):
    background_tasks.add_task(ads_service.run_scheduler_inprocess, client.id)
    return {"message": "Scheduler started. Check history in ~30 seconds."}


# ── Bid Optimizer ────────────────────────────────────────────────────────────

@router.get("/bid-optimizer/rules", response_model=list[BidOptimizerRule])
async def get_bid_optimizer_rules(session: SessionDep, client: ClientDep):
    return ads_service.get_bid_optimizer_rules()


@router.post("/bid-optimizer/rules", response_model=BidOptimizerRule, status_code=201)
async def add_bid_optimizer_rule(body: BidOptimizerRule, session: SessionDep, client: ClientDep):
    return ads_service.add_bid_optimizer_rule(body.model_dump())


@router.delete("/bid-optimizer/rules/{rule_id}", status_code=204)
async def delete_bid_optimizer_rule(rule_id: str, session: SessionDep, client: ClientDep):
    if not ads_service.remove_bid_optimizer_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")


@router.patch("/bid-optimizer/rules/{rule_id}/toggle", response_model=BidOptimizerRule)
async def toggle_bid_optimizer_rule(rule_id: str, session: SessionDep, client: ClientDep):
    result = ads_service.toggle_bid_optimizer_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return result


@router.get("/bid-optimizer/history", response_model=list[BidOptimizerLogEntry])
async def bid_optimizer_history(session: SessionDep, client: ClientDep):
    return ads_service.get_bid_optimizer_log()


@router.post("/bid-optimizer/run", response_model=SchedulerTriggerResponse)
async def run_bid_optimizer(background_tasks: BackgroundTasks, session: SessionDep, client: ClientDep):
    background_tasks.add_task(ads_service.run_bid_optimizer_inprocess, client.id)
    return {"message": "Bid optimizer started. Check history in ~30 seconds."}


# ── Direct budget update ──────────────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/products", response_model=list[CampaignProduct])
async def campaign_products(campaign_id: int, session: SessionDep, client: ClientDep):
    import traceback
    try:
        return await ads_service.get_campaign_products(client.id, campaign_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/campaigns/{campaign_id}/keywords", response_model=list[CampaignKeyword])
async def campaign_keywords(campaign_id: int, session: SessionDep, client: ClientDep):
    import traceback
    try:
        return await ads_service.get_campaign_keywords(client.id, campaign_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/campaigns/{campaign_id}/set-budget", response_model=SetBudgetResponse)
async def set_campaign_budget(campaign_id: int, body: SetBudgetRequest, session: SessionDep, client: ClientDep):
    import traceback
    try:
        await ads_service.set_campaign_budget(client.id, campaign_id, body.budget)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"Budget updated to ₹{body.budget:,.0f} successfully."}


@router.post("/reconnect-blinkit", response_model=ReconnectBlinkitResponse)
async def reconnect_blinkit(body: ReconnectBlinkitRequest, session: SessionDep, client: ClientDep):
    try:
        await ads_service.reconnect_blinkit(session, client.id, body.magic_link)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Blinkit session reconnected successfully."}
