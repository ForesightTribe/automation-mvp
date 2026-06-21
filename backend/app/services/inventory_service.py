"""Client-scoped inventory: stock-on-hand (blinkit_soh) and PO fill-rate
(blinkit_scorecard_facilities)."""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import BlinkitSOH, BlinkitScorecardFacility
from app.models.search import InventoryDepth
from app.schemas.common import Page
from app.schemas.inventory import AvailabilityRow, SohRow
from app.services import watchlist_service

SOH = BlinkitSOH
FAC = BlinkitScorecardFacility


async def get_soh(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    on_date: date | None = None,
) -> Page[SohRow]:
    target = on_date
    if target is None:
        target = (
            await session.execute(
                select(func.max(SOH.date)).where(SOH.tenant_id == tenant_id)
            )
        ).scalar()
    if target is None:
        return Page.build([], 0, pagination)

    cond = [SOH.tenant_id == tenant_id, SOH.date == target]
    total = (
        await session.execute(
            select(func.count(distinct(SOH.item_id))).where(*cond)
        )
    ).scalar_one()

    frontend = func.coalesce(func.sum(SOH.frontend_inv_qty), 0)
    rows = (
        await session.execute(
            select(
                SOH.item_id,
                func.max(SOH.item_name),
                func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                frontend,
                func.count(distinct(SOH.backend_facility_id)),
            )
            .where(*cond)
            .group_by(SOH.item_id)
            .order_by(frontend.asc())  # lowest frontend stock first
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).all()

    items = [
        SohRow(
            item_id=i,
            item_name=n,
            backend_qty=int(b),
            frontend_qty=int(f),
            facilities=int(fac),
            date=target,
        )
        for i, n, b, f, fac in rows
    ]
    return Page.build(items, total, pagination)


async def get_fill_rate(
    session: AsyncSession, *, tenant_id: uuid.UUID, from_date: date | None = None
) -> dict:
    target = from_date
    if target is None:
        target = (
            await session.execute(
                select(func.max(FAC.from_date_ist)).where(FAC.tenant_id == tenant_id)
            )
        ).scalar()
    if target is None:
        return {
            "from_date": None,
            "total_po_quantity": 0,
            "total_grn_quantity": 0,
            "fill_rate": 0.0,
            "potential_loss": 0.0,
            "facilities_count": 0,
        }

    cond = [FAC.tenant_id == tenant_id, FAC.from_date_ist == target]
    po, grn, loss, count = (
        await session.execute(
            select(
                func.coalesce(func.sum(FAC.total_po_quantity), 0),
                func.coalesce(func.sum(FAC.total_grn_quantity), 0),
                func.coalesce(func.sum(FAC.potential_loss), 0.0),
                func.count(),
            ).where(*cond)
        )
    ).one()

    return {
        "from_date": target,
        "total_po_quantity": int(po),
        "total_grn_quantity": int(grn),
        "fill_rate": round(grn / po, 4) if po else 0.0,
        "potential_loss": round(float(loss), 2),
        "facilities_count": int(count),
    }


async def get_availability(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 7,
    city: str | None = None,
    marketplace: str | None = None,
) -> Page[AvailabilityRow]:
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return Page.build([], 0, pagination)

    since = datetime.utcnow() - timedelta(days=days)
    cond = [InventoryDepth.brand_slug.in_(own), InventoryDepth.scraped_at >= since]
    if city:
        cond.append(InventoryDepth.city == city)
    if marketplace:
        cond.append(InventoryDepth.mp_slug == marketplace)

    # Latest row per (marketplace, city, sku).
    rows = (
        await session.execute(
            select(InventoryDepth)
            .where(*cond)
            .order_by(
                InventoryDepth.mp_slug,
                InventoryDepth.city,
                InventoryDepth.sku,
                InventoryDepth.scraped_at.desc(),
            )
            .distinct(InventoryDepth.mp_slug, InventoryDepth.city, InventoryDepth.sku)
        )
    ).scalars().all()

    rows.sort(key=lambda r: (r.in_stock, r.sku))  # out-of-stock first
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [AvailabilityRow.model_validate(r) for r in page], total, pagination
    )
