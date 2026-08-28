"""Zepto-side reads for the Analytics page.

Kept out of `analytics_service.py` because the sources are shaped differently:
Blinkit aggregates one table of item × city × day rows, whereas Zepto has two
tables at different grains — authoritative brand totals per day, and a per-SKU
breakdown per day.

Every function returns the same dict shape as its `analytics_service`
counterpart so results from both marketplaces can be merged without the callers
caring which one produced them.

Deliberately absent: anything per-city. Zepto's Sales Analytics API exposes no
city dimension at the grain we scrape, so `get_sales_by_city` and
`get_city_category` have no Zepto equivalent — those charts stay Blinkit-only
rather than silently reporting a blank or partial series.
"""
import uuid
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoSellerProductPerf as Prod
from app.models.zepto_seller import ZeptoSellerProductCityDaily as ProdCity
from app.models.zepto_seller import ZeptoSellerSalesDaily as Daily

# Which marketplace slug routes to these tables.
SLUG = "zepto"


def wants_zepto(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Zepto."""
    return marketplaces is None or SLUG in marketplaces


def _daily_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Daily.tenant_id == tenant_id, Daily.date >= start, Daily.date <= end]


def _prod_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    # period_start == period_end for day-grain rows; filtering on period_start
    # keeps any older window-grain row from leaking into a day-scoped query.
    return [
        Prod.tenant_id == tenant_id,
        Prod.period_start >= start,
        Prod.period_start <= end,
        Prod.period_start == Prod.period_end,
    ]


async def sales_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, int]:
    """(revenue, units, distinct SKUs) — mirrors analytics_service._sales_agg.

    Revenue and units come from the daily table, which carries Zepto's own
    totals; the SKU count comes from the product table. They are deliberately
    from different sources: summing the product rows undercounts, because
    Zepto's "top selling" response omits some SKUs (observed ~3-7% short).
    """
    revenue, units = (
        await session.execute(
            select(
                func.coalesce(func.sum(Daily.gmv), 0.0),
                func.coalesce(func.sum(Daily.units), 0),
            ).where(*_daily_conds(tenant_id, start, end))
        )
    ).one()
    skus = (
        await session.execute(
            select(func.count(distinct(Prod.product_variant_id))).where(
                *_prod_conds(tenant_id, start, end)
            )
        )
    ).scalar_one()
    return float(revenue), int(units), int(skus)


async def revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    rows = (
        await session.execute(
            select(Daily.date, Daily.gmv, Daily.units)
            .where(*_daily_conds(tenant_id, start, end))
            .order_by(Daily.date)
        )
    ).all()
    return [
        {"date": d, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, rev, units in rows
    ]


async def top_skus(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date, limit: int = 10
) -> list[dict]:
    revenue = func.coalesce(func.sum(Prod.gmv), 0.0)
    rows = (
        await session.execute(
            select(
                Prod.product_variant_id,
                func.max(Prod.product_name),
                revenue,
                func.coalesce(func.sum(Prod.qty_sold), 0),
            )
            .where(*_prod_conds(tenant_id, start, end))
            .group_by(Prod.product_variant_id)
            .order_by(revenue.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "item_id": item_id,
            "item_name": name,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for item_id, name, rev, units in rows
    ]


async def sales_by_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Grouped by SUBcategory, not category.

    Zepto's `categoryName` is one broad bucket for this account ("Dairy, Bread
    & Eggs" covers every SKU), so grouping on it produces a single useless bar.
    `subcategoryName` — Breads & Buns / Cheese / Paneer & Cream — is the level
    that actually distinguishes products.
    """
    revenue = func.coalesce(func.sum(Prod.gmv), 0.0)
    category = func.coalesce(Prod.subcategory_name, "Uncategorized")
    rows = (
        await session.execute(
            select(category, revenue, func.coalesce(func.sum(Prod.qty_sold), 0))
            .where(*_prod_conds(tenant_id, start, end))
            .group_by(category)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {"category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for cat, rev, units in rows
    ]


async def category_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Per-day revenue/units by subcategory — only possible because the product
    rows are scraped at day grain (a window-grain scrape collapses the time
    axis this chart needs)."""
    revenue = func.coalesce(func.sum(Prod.gmv), 0.0)
    units = func.coalesce(func.sum(Prod.qty_sold), 0)
    category = func.coalesce(Prod.subcategory_name, "Uncategorized")
    rows = (
        await session.execute(
            select(Prod.period_start, category, revenue, units)
            .where(*_prod_conds(tenant_id, start, end))
            .group_by(Prod.period_start, category)
            .order_by(Prod.period_start, category)
        )
    ).all()
    return [
        {
            "date": d,
            "category": cat,
            "revenue": round(float(rev), 2),
            "units_sold": int(u),
        }
        for d, cat, rev, u in rows
    ]


async def sales_by_city(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Revenue and units per city — same shape as analytics_service's Blinkit one.

    Zepto reports no city split in any single response, so these rows come from
    one API call per city (see scraper.fetch_sales_by_city). Only cities with
    actual sales are stored, so this returns a short list: on this account it is
    Bengaluru alone, which accounts for 100% of GMV.

    `city_name` carries Zepto's own prefixed form ("BLR - Bengaluru"); it is left
    as-is rather than cleaned, so the dashboard shows what the seller portal shows.
    """
    rows = (
        await session.execute(
            select(
                ProdCity.city_id,
                func.max(ProdCity.city_name),
                func.coalesce(func.sum(ProdCity.gmv), 0.0),
                func.coalesce(func.sum(ProdCity.qty_sold), 0),
            )
            .where(
                ProdCity.tenant_id == tenant_id,
                ProdCity.date >= start,
                ProdCity.date <= end,
            )
            .group_by(ProdCity.city_id)
            .order_by(func.coalesce(func.sum(ProdCity.gmv), 0.0).desc())
        )
    ).all()
    return [
        {
            "city": name or city_id,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for city_id, name, rev, units in rows
    ]


async def city_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
    limit: int = 15,
) -> list[dict]:
    """City x category revenue cells for the Analytics heatmap.

    Reads `zepto_seller_product_city_daily` — the only Zepto table carrying city
    and category on one row. `zepto_seller_sales_city_daily` has no category and
    `zepto_seller_product_perf` has no city, so neither can answer this on its
    own, and joining them on date alone would attribute every SKU's revenue to
    whichever cities sold that day rather than reading the real split.

    Scoped to the top `limit` cities by revenue, mirroring the Blinkit version:
    the heatmap renders cities as rows, and there are more of them than fit.

    Returns [] until a scrape has run since the per-city breakdown was added —
    the caller then shows an empty chart, which is the honest state, rather than
    a synthesised one.
    """
    revenue = func.coalesce(func.sum(ProdCity.gmv), 0.0)
    conds = [
        ProdCity.tenant_id == tenant_id,
        ProdCity.date >= start,
        ProdCity.date <= end,
    ]

    top = (
        await session.execute(
            select(ProdCity.city_id, func.max(ProdCity.city_name), revenue)
            .where(*conds)
            .group_by(ProdCity.city_id)
            .order_by(revenue.desc())
            .limit(limit)
        )
    ).all()
    if not top:
        return []
    name_by_id = {cid: (cname or cid) for cid, cname, _ in top}

    category = func.coalesce(ProdCity.subcategory_name, ProdCity.category_name,
                             "Uncategorized")
    cells = (
        await session.execute(
            select(
                ProdCity.city_id,
                category,
                revenue,
                func.coalesce(func.sum(ProdCity.qty_sold), 0),
            )
            .where(*conds, ProdCity.city_id.in_(list(name_by_id)))
            .group_by(ProdCity.city_id, category)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {
            "city": name_by_id[cid],
            "category": cat,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for cid, cat, rev, units in cells
    ]
