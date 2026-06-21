"""Client-scoped advertising data. Mounted under /clients/{client_id}/ads."""
from fastapi import APIRouter, Query

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.ads import (
    AdPerformancePoint,
    CampaignRow,
    CollectionRow,
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
    pagination: PaginationDep,
    days: int = Query(30, ge=1, le=365),
    status: str | None = None,
):
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
