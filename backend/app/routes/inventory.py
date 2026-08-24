"""Client-scoped inventory. Mounted under /clients/{client_id}/inventory."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

# Combo/multipack filter shared by the public availability endpoints. Default is
# `main` (singular SKUs only) — combos are stocked selectively so they're analysed
# apart from main SKUs unless explicitly requested.
KindQuery = Literal["main", "combo", "all"]

from app.dependencies import ClientDep, MarketplacesDep, PaginationDep, PeriodDep, SessionDep
from app.schemas.common import Page
from app.schemas.inventory import (
    ActionRow,
    AvailabilityHistoryResponse,
    AvailabilityRow,
    CitiesResponse,
    DistributionResponse,
    FillRateSummary,
    SkuPricingResponse,
    SohRow,
    ProductDetailResponse,
    StoreDetailResponse,
    StoresResponse,
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
    period: PeriodDep,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """Public stock-out monitoring for the client's own brand (out-of-stock first),
    from sku_snapshots — latest row per (marketplace, city, product). `kind` splits
    main SKUs from combos/multipacks (default main)."""
    return await inventory_service.get_availability(
        session,
        tenant_id=client.id,
        pagination=pagination,
        start=period.start,
        end=period.end,
        city=city,
        marketplaces=marketplaces,
        kind=kind,
    )


@router.get("/distribution", response_model=DistributionResponse)
async def distribution(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """Per own SKU: % of covered stores it's actually in-stock in (widest gaps first).
    `kind` = main (default) | combo | all."""
    return await inventory_service.get_distribution(
        session, tenant_id=client.id, start=period.start, end=period.end, city=city, marketplaces=marketplaces, kind=kind
    )


@router.get("/availability-history", response_model=AvailabilityHistoryResponse)
async def availability_history(
    session: SessionDep,
    client: ClientDep,
    weeks: int = Query(12, ge=1, le=52),
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """Weekly on-shelf availability % trend for own SKUs.

    A trend is history, so it takes `weeks` of look-back and deliberately ignores the
    page's reporting window — otherwise a narrow window (e.g. a 2-day custom range)
    leaves nothing to plot. `kind` = main | combo | all."""
    return await inventory_service.get_availability_history(
        session, tenant_id=client.id, days=weeks * 7, city=city,
        marketplaces=marketplaces, kind=kind,
    )


@router.get("/pricing", response_model=SkuPricingResponse)
async def pricing(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """Per own SKU: price dispersion across stores (min/median/max) + avg discount.
    `kind` = main | combo | all."""
    return await inventory_service.get_pricing(
        session, tenant_id=client.id, start=period.start, end=period.end, city=city, marketplaces=marketplaces, kind=kind
    )


# ── Store-grain views (the dark-store model; see docs/darkstores.md) ─────────
# Percentages always ship with the counts behind them (`stores_scraped`,
# `active_range`) so the UI can render "X of N" rather than a bare number.


@router.get("/stores", response_model=StoresResponse)
async def stores(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
    tier: str | None = Query(None, description="express | longtail | super_longtail"),
):
    """Availability per dark store, worst first — which shops are letting you down.

    `tier` narrows to one fulfilment tier. Denominators are per tier too (`tiers`),
    since ~2,059 express stores and ~510 shared hubs are not comparable populations.
    """
    return await inventory_service.get_stores(
        session, tenant_id=client.id, start=period.start, end=period.end, city=city,
        marketplaces=marketplaces, kind=kind, tier=tier,
    )


@router.get("/cities", response_model=CitiesResponse)
async def cities(
    session: SessionDep,
    client: ClientDep,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """City rollup of store availability — the same numbers one level up."""
    return await inventory_service.get_cities(
        session, tenant_id=client.id, start=period.start, end=period.end, marketplaces=marketplaces, kind=kind
    )


@router.get("/actions", response_model=Page[ActionRow])
async def actions(
    session: SessionDep,
    client: ClientDep,
    pagination: PaginationDep,
    period: PeriodDep,
    action: Literal["oos", "not-listed"] = "oos",
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """The work queue: one row per problem, each naming a store and a product.

    `oos` = listed but out of stock (replenishment). `not-listed` = absent from the
    shelf (range). Two separate lists because they are two different teams' work.
    """
    return await inventory_service.get_actions(
        session, tenant_id=client.id, pagination=pagination, action=action,
        start=period.start, end=period.end, city=city, marketplaces=marketplaces, kind=kind,
    )


@router.get("/products/{product_id}/stores", response_model=ProductDetailResponse)
async def product_stores(
    session: SessionDep,
    client: ClientDep,
    product_id: str,
    period: PeriodDep,
    city: str | None = None,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """One product across every store — where it is out of stock, where it is not
    carried at all, where it is fine. The mirror of the store shelf, for the product
    drawer."""
    return await inventory_service.get_product_detail(
        session, tenant_id=client.id, product_id=product_id,
        start=period.start, end=period.end, city=city, marketplaces=marketplaces, kind=kind,
    )


@router.get("/stores/{merchant_id}", response_model=StoreDetailResponse)
async def store_detail(
    session: SessionDep,
    client: ClientDep,
    merchant_id: str,
    period: PeriodDep,
    marketplaces: MarketplacesDep = None,
    kind: KindQuery = "main",
):
    """One store's whole shelf — every own SKU, including the ones it does not
    carry (`listed=false`), so range gaps sit next to stockouts."""
    return await inventory_service.get_store_detail(
        session, tenant_id=client.id, merchant_id=merchant_id,
        start=period.start, end=period.end, marketplaces=marketplaces, kind=kind,
    )
