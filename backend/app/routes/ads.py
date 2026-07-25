"""Client-scoped advertising data. Mounted under /clients/{client_id}/ads."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.dependencies import ClientDep, Pagination, PaginationDep, PeriodDep, SessionDep
from app.schemas.ads import (
    AdMarketplaceRow,
    AdPerformancePoint,
    AdsSummary,
    BidOptimizerLogEntry,
    BidOptimizerRule,
    BudgetSchedule,
    BudgetSplitRow,
    CampaignKeyword,
    CampaignProduct,
    CampaignRow,
    CollectionRow,
    KeywordRow,
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


def _mps(marketplaces: str | None) -> list[str] | None:
    """Parse the comma-separated ?marketplaces= filter (None/empty = all)."""
    return [m for m in marketplaces.split(",") if m] if marketplaces else None


@router.get("/summary", response_model=AdsSummary)
async def summary(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    return await ads_service.get_summary(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
        marketplaces=_mps(marketplaces),
    )


@router.get("/performance", response_model=list[AdPerformancePoint])
async def performance(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    return await ads_service.get_performance(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=_mps(marketplaces),
    )


@router.get("/budget-split", response_model=list[BudgetSplitRow])
async def budget_split(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    return await ads_service.get_budget_split(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=_mps(marketplaces),
    )


@router.get("/campaigns", response_model=Page[CampaignRow])
async def campaigns(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    pagination: PaginationDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
    status: str | None = None,
    sort: str = Query("spend", pattern="^(spend|roas|sales|impressions)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    recent_only: bool = False,
):
    return await ads_service.get_campaigns(
        session,
        tenant_id=client.id,
        pagination=pagination,
        start=period.start,
        end=period.end,
        marketplaces=_mps(marketplaces),
        status=status,
        sort=sort,
        order=order,
        recent_only=recent_only,
    )


@router.get("/keywords", response_model=Page[KeywordRow])
async def keywords(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
    campaign_id: int | None = None,
    target_type: str | None = Query(
        None, description="Filter to 'keyword' or 'recommendation' rows."
    ),
    sort: str = Query("spend", pattern="^(spend|roas|sales|impressions)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    return await ads_service.get_keywords(
        session,
        tenant_id=client.id,
        pagination=pagination,
        campaign_id=campaign_id,
        marketplaces=_mps(marketplaces),
        target_type=target_type,
        sort=sort,
        order=order,
    )


@router.get("/sov", response_model=list[SponsoredSovRow])
async def sponsored_sov(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    return await ads_service.get_sponsored_sov(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=_mps(marketplaces),
    )


@router.get("/marketplaces", response_model=list[AdMarketplaceRow])
async def marketplaces_breakdown(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
):
    return await ads_service.get_marketplace_breakdown(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
    )


@router.get("/visibility-plans", response_model=list[VisibilityPlanRow])
async def visibility_plans(session: SessionDep, client: ClientDep):
    return await ads_service.get_visibility_plans(session, tenant_id=client.id)


@router.get("/collections", response_model=list[CollectionRow])
async def collections(session: SessionDep, client: ClientDep):
    return await ads_service.get_collections(session, tenant_id=client.id)


# ── Budget scheduling ─────────────────────────────────────────────────────────

@router.get("/budget-schedules/history", response_model=list[SchedulerLogEntry])
async def scheduler_history(session: SessionDep, client: ClientDep):
    return await ads_service.get_scheduler_log(session, client.id)


@router.get("/budget-schedules", response_model=list[BudgetSchedule])
async def get_budget_schedules(session: SessionDep, client: ClientDep):
    return await ads_service.get_budget_schedules(session, client.id)


@router.post("/budget-schedules", response_model=BudgetSchedule, status_code=201)
async def add_budget_schedule(body: BudgetSchedule, session: SessionDep, client: ClientDep):
    return await ads_service.add_budget_schedule(session, client.id, body.model_dump())


@router.patch("/budget-schedules/{campaign_id}/toggle", response_model=BudgetSchedule)
async def toggle_budget_schedule(campaign_id: int, session: SessionDep, client: ClientDep):
    result = await ads_service.toggle_budget_schedule(session, client.id, campaign_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return result


@router.delete("/budget-schedules/{campaign_id}", status_code=204)
async def delete_budget_schedule(campaign_id: int, session: SessionDep, client: ClientDep):
    if not await ads_service.remove_budget_schedule(session, client.id, campaign_id):
        raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/budget-schedules/run", response_model=SchedulerTriggerResponse)
async def trigger_scheduler(background_tasks: BackgroundTasks, session: SessionDep, client: ClientDep):
    background_tasks.add_task(ads_service.run_scheduler_inprocess, client.id)
    return {"message": "Scheduler started. Check history in ~30 seconds."}


# ── Bid Optimizer ────────────────────────────────────────────────────────────

@router.get("/bid-optimizer/rules", response_model=list[BidOptimizerRule])
async def get_bid_optimizer_rules(session: SessionDep, client: ClientDep):
    return await ads_service.get_bid_optimizer_rules(session, client.id)


@router.post("/bid-optimizer/rules", response_model=BidOptimizerRule, status_code=201)
async def add_bid_optimizer_rule(body: BidOptimizerRule, session: SessionDep, client: ClientDep):
    return await ads_service.add_bid_optimizer_rule(session, client.id, body.model_dump())


@router.delete("/bid-optimizer/rules/{rule_id}", status_code=204)
async def delete_bid_optimizer_rule(rule_id: str, session: SessionDep, client: ClientDep):
    if not await ads_service.remove_bid_optimizer_rule(session, client.id, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")


@router.patch("/bid-optimizer/rules/{rule_id}/toggle", response_model=BidOptimizerRule)
async def toggle_bid_optimizer_rule(rule_id: str, session: SessionDep, client: ClientDep):
    result = await ads_service.toggle_bid_optimizer_rule(session, client.id, rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return result


@router.get("/bid-optimizer/history", response_model=list[BidOptimizerLogEntry])
async def bid_optimizer_history(session: SessionDep, client: ClientDep):
    return await ads_service.get_bid_optimizer_log(session, client.id)


@router.post("/bid-optimizer/run", response_model=SchedulerTriggerResponse)
async def run_bid_optimizer(background_tasks: BackgroundTasks, session: SessionDep, client: ClientDep):
    background_tasks.add_task(ads_service.run_bid_optimizer_inprocess, client.id)
    return {"message": "Bid optimizer started. Check history in ~30 seconds."}


# ── Direct budget update ──────────────────────────────────────────────────────

@router.get("/live-position")
async def live_position(
    keyword: str,
    lat: float,
    lon: float,
    session: SessionDep,
    client: ClientDep,
):
    import traceback
    try:
        results = await ads_service.get_live_positions(keyword, lat=lat, lon=lon)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))
    return results


@router.get("/campaigns/{campaign_id}/live-budget")
async def live_campaign_budget(campaign_id: int, session: SessionDep, client: ClientDep):
    import traceback
    try:
        budget = await ads_service.get_live_campaign_budget(client.id, campaign_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))
    return {"campaign_budget": budget}


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
