"""Client-scoped analytics. Mounted under /clients/{client_id}/analytics, so
every handler gets `client: ClientDep` (access already enforced)."""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.analytics import (
    AnalyticsOverview,
    CategoryBreakdown,
    CategoryTrendPoint,
    CityBreakdown,
    CityCategoryCell,
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
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
    limit: int = Query(10, ge=1, le=100),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_top_skus(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
        limit=limit,
    )


@router.get("/sales-by-city", response_model=list[CityBreakdown])
async def sales_by_city(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_sales_by_city(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/sales-by-category", response_model=list[CategoryBreakdown])
async def sales_by_category(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_sales_by_category(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/category-trend", response_model=list[CategoryTrendPoint])
async def category_trend(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_category_trend(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
    )


@router.get("/city-category", response_model=list[CityCategoryCell])
async def city_category(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: str | None = Query(
        None, description="Comma-separated marketplace slugs; omit for all."
    ),
    limit: int = Query(15, ge=1, le=100, description="Top N cities by revenue."),
):
    mps = [m for m in marketplaces.split(",") if m] if marketplaces else None
    return await analytics_service.get_city_category(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        marketplaces=mps,
        limit=limit,
    )
