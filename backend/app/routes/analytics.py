"""Client-scoped analytics. Mounted under /clients/{client_id}/analytics, so
every handler gets `client: ClientDep` (access already enforced)."""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.analytics import (
    AnalyticsOverview,
    CategoryBreakdown,
    CityBreakdown,
    RevenuePoint,
    TopSku,
    TrendPoint,
)
from app.services import analytics_service

router = APIRouter()


@router.get("/overview", response_model=AnalyticsOverview)
async def overview(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_overview(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
        marketplaces=mps,
    )


@router.get("/revenue", response_model=list[RevenuePoint])
async def revenue(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_revenue_series(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/trends", response_model=list[TrendPoint])
async def trends(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_trends(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/top-skus", response_model=list[TopSku])
async def top_skus(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
):
    return await analytics_service.get_top_skus(
        session, tenant_id=client.id, days=days, limit=limit
    )


@router.get("/sales-by-city", response_model=list[CityBreakdown])
async def sales_by_city(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
):
    return await analytics_service.get_sales_by_city(
        session, tenant_id=client.id, days=days
    )


@router.get("/sales-by-category", response_model=list[CategoryBreakdown])
async def sales_by_category(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
):
    return await analytics_service.get_sales_by_category(
        session, tenant_id=client.id, days=days
    )
