"""Client-scoped advertising data. Mounted under /clients/{client_id}/ads."""
from fastapi import APIRouter, HTTPException, Query

from app.dependencies import ClientDep, Pagination, PaginationDep, PeriodDep, SessionDep
from app.schemas.ads import (
    AdMarketplaceRow,
    AdPerformancePoint,
    AdsSummary,
    BudgetSplitRow,
    CampaignDayRow,
    CampaignRow,
    CollectionRow,
    KeywordRow,
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


@router.get("/campaigns/daily", response_model=list[CampaignDayRow])
async def campaigns_daily(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    """Each campaign's spend per day over the window, for days it spent — the budget-
    utilisation views' data in one request (they made one `/campaigns` call per day)."""
    return await ads_service.get_campaigns_daily(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=_mps(marketplaces),
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
    recent_only: bool = Query(
        False,
        description="Only campaigns the latest catalogue scrape returned (hides the "
        "pre-migration account's).",
    ),
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
        recent_only=recent_only,
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
