"""Overview-page composite endpoints. Mounted under /clients/{client_id}/overview,
so every handler gets `client: ClientDep` (access already enforced)."""
from datetime import date

from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.overview import (
    FreshnessChip,
    MarketplaceRow,
    MarketplaceTrend,
)
from app.schemas.insight import Insight
from app.services import insights_service, overview_service

router = APIRouter()


@router.get("/marketplaces", response_model=list[MarketplaceRow])
async def marketplaces(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    prev_start: date | None = Query(
        None, description="Compare against this window instead of the preceding one"
    ),
    prev_end: date | None = Query(None),
    market: bool = Query(
        True, description="false drops visibility/avg rank, the search_listings reads"
    ),
):
    """`prev_start`/`prev_end` override the window this is measured against, so a
    caller wanting the same day last week asks once rather than fetching that day
    as a second request."""
    return await overview_service.get_marketplace_breakdown(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=prev_start or period.prev_start,
        prev_end=prev_end or period.prev_end,
        include_market=market,
    )


@router.get("/marketplace-trends", response_model=list[MarketplaceTrend])
async def marketplace_trends(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated slugs; omitted = every connected one"
    ),
):
    return await overview_service.get_marketplace_trends(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=[m for m in marketplaces.split(",") if m] if marketplaces else None,
    )


@router.get("/freshness", response_model=list[FreshnessChip])
async def freshness(session: SessionDep, client: ClientDep):
    return await overview_service.get_freshness(session, tenant_id=client.id)


@router.get("/insights", response_model=list[Insight])
async def insights(session: SessionDep, client: ClientDep, period: PeriodDep):
    """The Action Center: what is worth acting on, ranked by what it is worth."""
    return await insights_service.get_insights(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
    )


