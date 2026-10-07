"""Instamart-side reads for the Overview and Analytics pages.

Kept out of `analytics_service.py` for the same reason Zepto is: the source is
shaped differently. Blinkit aggregates item x city x day; Zepto has brand totals
plus a SKU breakdown; Instamart's report is finer than either — one row per
**day x store x item** — so every total here is a sum over stores.

Every function returns the same shape as its `analytics_service` counterpart, so
results from all three marketplaces merge without callers caring which produced
them.

Two things worth knowing before adding to this module:

**Never mix the two tables.** `instamart_seller_store_daily` (per store) and
`instamart_brand_city_daily` (per city, whole brand) hold the same rupees at
different resolutions. Sales totals come from the store table, because it is the
one scoped to our own products; the city table carries brand-level marketing
figures (impressions, orders, new-to-brand buyers) that the store table lacks.

**A city split IS available here**, unlike Zepto — the store table carries both
`city` and `area_name`, so per-city charts can be served for Instamart where
Zepto has to sit them out.
"""
import uuid
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instamart_seller import InstamartSellerStoreDaily as Store

# Which marketplace slug routes to these tables.
SLUG = "instamart"


def wants_instamart(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Instamart."""
    return marketplaces is None or SLUG in marketplaces


def _store_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Store.tenant_id == tenant_id, Store.date >= start, Store.date <= end]


async def sales_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, int]:
    """(revenue, units, distinct SKUs) — mirrors analytics_service._sales_agg.

    All three come from the store table: it is the finest grain the portal
    publishes, and summing it over stores reproduces the portal's own headline
    Sales figure exactly (checked against the dashboard KPI for 15-21 Sep).
    """
    revenue, units, skus = (
        await session.execute(
            select(
                func.coalesce(func.sum(Store.gmv), 0.0),
                func.coalesce(func.sum(Store.units_sold), 0),
                func.count(distinct(Store.item_code)),
            ).where(*_store_conds(tenant_id, start, end))
        )
    ).one()
    return float(revenue), int(units), int(skus)


async def revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Revenue and units per day, summed across every store."""
    rows = (
        await session.execute(
            select(
                Store.date,
                func.sum(Store.gmv),
                func.sum(Store.units_sold),
            )
            .where(*_store_conds(tenant_id, start, end))
            .group_by(Store.date)
            .order_by(Store.date)
        )
    ).all()
    return [
        {"date": d, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, rev, units in rows
    ]


async def sales_by_city(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Revenue, units and store count per city — Instamart can do this split."""
    rows = (
        await session.execute(
            select(
                Store.city,
                func.sum(Store.gmv),
                func.sum(Store.units_sold),
                func.count(distinct(Store.store_id)),
            )
            .where(*_store_conds(tenant_id, start, end), Store.city.isnot(None))
            .group_by(Store.city)
            .order_by(func.sum(Store.gmv).desc())
        )
    ).all()
    return [
        {"city": city, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for city, rev, units, stores in rows
    ]


async def top_skus(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
    limit: int = 20,
) -> list[dict]:
    """Best sellers by revenue — mirrors analytics_service.get_top_skus rows."""
    rows = (
        await session.execute(
            select(
                Store.item_code,
                func.max(Store.product_name),
                func.max(Store.variant),
                func.sum(Store.gmv),
                func.sum(Store.units_sold),
                func.count(distinct(Store.store_id)),
            )
            .where(*_store_conds(tenant_id, start, end))
            .group_by(Store.item_code)
            .order_by(func.sum(Store.gmv).desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "item_id": code,
            "item_name": f"{name} ({variant})" if name and variant else name,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for code, name, variant, rev, units, stores in rows
    ]


async def sales_by_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Revenue/units by category. L2 is the useful level (cheese, bread and
    buns); L1 is the fallback when a row has no L2."""
    category = func.coalesce(Store.l2_category, Store.l1_category, "Uncategorized")
    rows = (
        await session.execute(
            select(category, func.sum(Store.gmv), func.sum(Store.units_sold))
            .where(*_store_conds(tenant_id, start, end))
            .group_by(category)
            .order_by(func.sum(Store.gmv).desc())
        )
    ).all()
    return [
        {"category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for cat, rev, units in rows
    ]


async def category_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Per-day revenue/units by category."""
    category = func.coalesce(Store.l2_category, Store.l1_category, "Uncategorized")
    rows = (
        await session.execute(
            select(Store.date, category, func.sum(Store.gmv),
                   func.sum(Store.units_sold))
            .where(*_store_conds(tenant_id, start, end))
            .group_by(Store.date, category)
            .order_by(Store.date)
        )
    ).all()
    return [
        {"date": d, "category": cat, "revenue": round(float(rev), 2),
         "units_sold": int(u)}
        for d, cat, rev, u in rows
    ]


async def city_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
    limit: int = 15,
) -> list[dict]:
    """City x category cells for the heatmap.

    Instamart can serve this where Zepto cannot: the report carries the store —
    and therefore its city — on the same row as the category, so no cross-join
    of two different grains is needed.
    """
    category = func.coalesce(Store.l2_category, Store.l1_category, "Uncategorized")
    top = (
        await session.execute(
            select(Store.city)
            .where(*_store_conds(tenant_id, start, end), Store.city.isnot(None))
            .group_by(Store.city)
            .order_by(func.sum(Store.gmv).desc())
            .limit(limit)
        )
    ).scalars().all()
    if not top:
        return []

    rows = (
        await session.execute(
            select(Store.city, category, func.sum(Store.gmv),
                   func.sum(Store.units_sold))
            .where(*_store_conds(tenant_id, start, end), Store.city.in_(top))
            .group_by(Store.city, category)
        )
    ).all()
    return [
        {"city": city, "category": cat, "revenue": round(float(rev), 2),
         "units_sold": int(units)}
        for city, cat, rev, units in rows
    ]
