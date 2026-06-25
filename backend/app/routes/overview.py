"""Overview-page composite endpoints. Mounted under /clients/{client_id}/overview,
so every handler gets `client: ClientDep` (access already enforced)."""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PeriodDep, SessionDep
from app.schemas.overview import (
    AlertItem,
    FreshnessChip,
    MarketplaceRow,
    MonthlyTrendPoint,
)
from app.services import overview_service

router = APIRouter()


@router.get("/marketplaces", response_model=list[MarketplaceRow])
async def marketplaces(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
):
    return await overview_service.get_marketplace_breakdown(
        session,
        tenant_id=client.id,
        start=period.start,
        end=period.end,
        prev_start=period.prev_start,
        prev_end=period.prev_end,
    )


@router.get("/monthly-trends", response_model=list[MonthlyTrendPoint])
async def monthly_trends(
    session: SessionDep,
    client: ClientDep,
    months: int = Query(3, ge=1, le=24),
):
    return await overview_service.get_monthly_trends(
        session, tenant_id=client.id, months=months
    )


@router.get("/freshness", response_model=list[FreshnessChip])
async def freshness(session: SessionDep, client: ClientDep):
    return await overview_service.get_freshness(session, tenant_id=client.id)


@router.get("/alerts", response_model=list[AlertItem])
async def alerts(session: SessionDep, client: ClientDep):
    return await overview_service.get_alerts(session, tenant_id=client.id)
