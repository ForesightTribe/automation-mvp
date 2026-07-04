"""Client-scoped inventory: stock-on-hand (blinkit_soh) and PO fill-rate
(blinkit_scorecard_facilities)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import Integer, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.utils.time import now_ist
from app.models.blinkit_seller import BlinkitSOH, BlinkitScorecardFacility
from app.models.search import SkuSnapshot
from app.schemas.common import Page
from app.schemas.inventory import AvailabilityRow, SohRow
from app.services import watchlist_service

SOH = BlinkitSOH
FAC = BlinkitScorecardFacility


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _kind_cond(kind: str) -> list:
    """Combo/multipack filter. Combos are stocked selectively, so they're analysed
    apart from singular main SKUs. `main` (default) = singles only, `combo` = combos
    only, `all` = both."""
    if kind == "combo":
        return [SkuSnapshot.is_combo.is_(True)]
    if kind == "all":
        return []
    return [SkuSnapshot.is_combo.is_(False)]


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


def _latest_per_store(tenant_id, own, since, city, marketplace, kind="main"):
    """Subquery: the latest sku_snapshots row per (product, store) in the window."""
    cond = [
        SkuSnapshot.tenant_id == tenant_id,
        SkuSnapshot.brand_slug.in_(own),
        SkuSnapshot.scraped_at >= since,
        *_kind_cond(kind),
    ]
    if city:
        cond.append(SkuSnapshot.city == city)
    if marketplace:
        cond.append(SkuSnapshot.mp_slug == marketplace)
    return (
        select(
            SkuSnapshot.platform_product_id.label("pid"),
            SkuSnapshot.product_name.label("name"),
            SkuSnapshot.merchant_id.label("store"),
            SkuSnapshot.in_stock.label("in_stock"),
            SkuSnapshot.price.label("price"),
            SkuSnapshot.discount_pct.label("discount_pct"),
            SkuSnapshot.scraped_at.label("scraped_at"),
        )
        .where(*cond)
        .distinct(SkuSnapshot.platform_product_id, SkuSnapshot.merchant_id)
        .order_by(
            SkuSnapshot.platform_product_id,
            SkuSnapshot.merchant_id,
            SkuSnapshot.scraped_at.desc(),
        )
        .subquery()
    )


async def get_availability(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 30,
    city: str | None = None,
    marketplace: str | None = None,
    kind: str = "main",
) -> Page[AvailabilityRow]:
    """Public stock-out monitoring — latest row per (marketplace, city, product),
    out-of-stock first. Sourced from sku_snapshots (the targeted own-SKU scrape)."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return Page.build([], 0, pagination)

    since = now_ist() - timedelta(days=days)
    cond = [
        SkuSnapshot.tenant_id == tenant_id,
        SkuSnapshot.brand_slug.in_(own),
        SkuSnapshot.scraped_at >= since,
        *_kind_cond(kind),
    ]
    if city:
        cond.append(SkuSnapshot.city == city)
    if marketplace:
        cond.append(SkuSnapshot.mp_slug == marketplace)

    # Latest row per (marketplace, city, product).
    rows = (
        await session.execute(
            select(SkuSnapshot)
            .where(*cond)
            .order_by(
                SkuSnapshot.mp_slug,
                SkuSnapshot.city,
                SkuSnapshot.platform_product_id,
                SkuSnapshot.scraped_at.desc(),
            )
            .distinct(
                SkuSnapshot.mp_slug, SkuSnapshot.city, SkuSnapshot.platform_product_id
            )
        )
    ).scalars().all()

    rows.sort(key=lambda r: (r.in_stock, r.platform_product_id))  # OOS first
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(
        [AvailabilityRow.model_validate(r) for r in page], total, pagination
    )


async def get_distribution(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 30,
    city: str | None = None,
    marketplace: str | None = None,
    kind: str = "main",
) -> dict:
    """Per own SKU: distribution % = in-stock stores ÷ stores where it appears,
    using the latest snapshot per store. Worst coverage first."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return {"period_days": days, "as_of": None, "skus": []}

    since = now_ist() - timedelta(days=days)
    latest = _latest_per_store(tenant_id, own, since, city, marketplace, kind)
    rows = (
        await session.execute(
            select(
                latest.c.pid,
                func.max(latest.c.name),
                func.count(),
                func.sum(cast(latest.c.in_stock, Integer)),
                func.avg(latest.c.price),
                func.avg(latest.c.discount_pct),
                func.max(latest.c.scraped_at),
            ).group_by(latest.c.pid)
        )
    ).all()
    if not rows:
        return {"period_days": days, "as_of": None, "skus": []}

    skus = [
        {
            "platform_product_id": pid,
            "product_name": name,
            "total_stores": int(total),
            "in_stock_stores": int(in_stock or 0),
            "distribution_pct": _round(int(in_stock or 0) / total * 100, 1) if total else 0.0,
            "avg_price": _round(price),
            "avg_discount": _round(disc, 1),
        }
        for pid, name, total, in_stock, price, disc, _ in rows
    ]
    skus.sort(key=lambda s: s["distribution_pct"])  # widest gaps first
    as_of = max(r[6] for r in rows)
    return {"period_days": days, "as_of": as_of, "skus": skus}


async def get_availability_history(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 84,
    city: str | None = None,
    marketplace: str | None = None,
    kind: str = "main",
) -> dict:
    """Weekly on-shelf availability % for own SKUs — the stock-out trend."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return {"period_days": days, "points": []}

    since = now_ist() - timedelta(days=days)
    cond = [
        SkuSnapshot.tenant_id == tenant_id,
        SkuSnapshot.brand_slug.in_(own),
        SkuSnapshot.scraped_at >= since,
        *_kind_cond(kind),
    ]
    if city:
        cond.append(SkuSnapshot.city == city)
    if marketplace:
        cond.append(SkuSnapshot.mp_slug == marketplace)

    week = func.date_trunc("week", SkuSnapshot.scraped_at).label("week")
    rows = (
        await session.execute(
            select(week, func.avg(cast(SkuSnapshot.in_stock, Integer)), func.count())
            .where(*cond)
            .group_by(week)
            .order_by(week)
        )
    ).all()
    points = [
        {
            "week": w.date() if hasattr(w, "date") else w,
            "availability_pct": _round(float(avail) * 100, 1),
            "oos_pct": _round((1 - float(avail)) * 100, 1),
            "samples": n,
        }
        for w, avail, n in rows
    ]
    return {"period_days": days, "points": points}


async def get_pricing(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 30,
    city: str | None = None,
    marketplace: str | None = None,
    kind: str = "main",
) -> dict:
    """Per own SKU: price dispersion across stores (min/median/max) + avg discount,
    using the latest snapshot per store."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return {"period_days": days, "as_of": None, "skus": []}

    since = now_ist() - timedelta(days=days)
    latest = _latest_per_store(tenant_id, own, since, city, marketplace, kind)
    rows = (
        await session.execute(
            select(
                latest.c.pid,
                func.max(latest.c.name),
                func.count(),
                func.min(latest.c.price),
                func.percentile_cont(0.5).within_group(latest.c.price.asc()),
                func.max(latest.c.price),
                func.avg(latest.c.discount_pct),
                func.max(latest.c.scraped_at),
            )
            .where(latest.c.price.is_not(None))
            .group_by(latest.c.pid)
        )
    ).all()
    if not rows:
        return {"period_days": days, "as_of": None, "skus": []}

    skus = [
        {
            "platform_product_id": pid,
            "product_name": name,
            "stores": int(stores),
            "min_price": _round(mn),
            "median_price": _round(med),
            "max_price": _round(mx),
            "avg_discount": _round(disc, 1),
        }
        for pid, name, stores, mn, med, mx, disc, _ in rows
    ]
    as_of = max(r[7] for r in rows)
    return {"period_days": days, "as_of": as_of, "skus": skus}
