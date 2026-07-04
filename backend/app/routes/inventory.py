"""Client-scoped inventory. Mounted under /clients/{client_id}/inventory."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

# Combo/multipack filter shared by the public availability endpoints. Default is
# `main` (singular SKUs only) — combos are stocked selectively so they're analysed
# apart from main SKUs unless explicitly requested.
KindQuery = Literal["main", "combo", "all"]

from app.dependencies import ClientDep, PaginationDep, SessionDep
from app.schemas.common import Page
from app.schemas.inventory import (
    AvailabilityHistoryResponse,
    AvailabilityRow,
    DistributionResponse,
    FillRateSummary,
    SkuPricingResponse,
    SohRow,
)
from app.services import inventory_service

router = APIRouter()


@router.get("/soh", response_model=Page[SohRow])
async def soh(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    on_date: date | None = Query(None, alias="date", description="Defaults to latest"),
):
    return await inventory_service.get_soh(
        session, tenant_id=client.id, pagination=pagination, on_date=on_date
    )


@router.get("/fill-rate", response_model=FillRateSummary)
async def fill_rate(
    session: SessionDep,
    client: ClientDep,
    from_date: date | None = Query(None, alias="from", description="Defaults to latest"),
):
    return await inventory_service.get_fill_rate(
        session, tenant_id=client.id, from_date=from_date
    )


@router.get("/availability", response_model=Page[AvailabilityRow])
async def availability(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    days: int = Query(30, ge=1, le=365),
    city: str | None = None,
    marketplace: str | None = None,
    kind: KindQuery = "main",
):
    """Public stock-out monitoring for the client's own brand (out-of-stock first),
    from sku_snapshots — latest row per (marketplace, city, product). `kind` splits
    main SKUs from combos/multipacks (default main)."""
    return await inventory_service.get_availability(
        session,
        tenant_id=client.id,
        pagination=pagination,
        days=days,
        city=city,
        marketplace=marketplace,
        kind=kind,
    )


@router.get("/distribution", response_model=DistributionResponse)
async def distribution(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
    city: str | None = None,
    marketplace: str | None = None,
    kind: KindQuery = "main",
):
    """Per own SKU: % of covered stores it's actually in-stock in (widest gaps first).
    `kind` = main (default) | combo | all."""
    return await inventory_service.get_distribution(
        session, tenant_id=client.id, days=days, city=city, marketplace=marketplace, kind=kind
    )


@router.get("/availability-history", response_model=AvailabilityHistoryResponse)
async def availability_history(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(84, ge=7, le=365),
    city: str | None = None,
    marketplace: str | None = None,
    kind: KindQuery = "main",
):
    """Weekly on-shelf availability % trend for own SKUs. `kind` = main | combo | all."""
    return await inventory_service.get_availability_history(
        session, tenant_id=client.id, days=days, city=city, marketplace=marketplace, kind=kind
    )


@router.get("/pricing", response_model=SkuPricingResponse)
async def pricing(
    session: SessionDep,
    client: ClientDep,
    days: int = Query(30, ge=1, le=365),
    city: str | None = None,
    marketplace: str | None = None,
    kind: KindQuery = "main",
):
    """Per own SKU: price dispersion across stores (min/median/max) + avg discount.
    `kind` = main | combo | all."""
    return await inventory_service.get_pricing(
        session, tenant_id=client.id, days=days, city=city, marketplace=marketplace, kind=kind
    )
