"""Blinkit NEW-domain (seller.blinkit.com/seller-hub) reads for the Analytics
page — Sereko today, any future account Blinkit migrates off partnersbiz.com
next.

Kept out of `analytics_service.py` for the same reason `zepto_analytics` is:
the source is shaped differently from `blinkit_seller.BlinkitSellerSale`.
Tagged `platform="blinkit"` like the old table (see `blinkit_seller_hub.py`),
so this is additive, not a new filterable marketplace — a tenant is on one
domain or the other, never both, so summing is safe.

Two tables, two different safety rules:

* `blinkit_seller_hub_sales_daily_ro` — real calendar date, every item summed
  together. Safe to sum across any date range, same as the old table.
* `blinkit_seller_hub_sales_by_product_ro` — one row per item per SNAPSHOT,
  where each snapshot's `sales_amount` already covers a rolling window
  ("Last 7 days", etc.) as of `as_of_date`. Summing across multiple
  `as_of_date`s in a range double/triple-counts the same days' sales, because
  neighboring snapshots' windows overlap. Every read of this table below picks
  ONE `as_of_date` (the latest one inside the requested range) rather than
  aggregating across several — see `_latest_snapshot_date`.

City and category breakdown: corrected 2026-10-01 — an earlier pass concluded
wrongly, twice, that this API has no city or category dimension at all, based
on not fully reading/testing the `sales/performance/metrics` endpoint's
filters. Both `filters.city_filter: [<city>]` and
`filters.business_category_filter: [<category_id>]` genuinely narrow it
server-side (verified live), so `sales_by_city` and `category_trend` read
`blinkit_seller_hub_sales_city_daily_ro` / `_category_daily_ro`, each scraped
once per value the same way Zepto's per-city breakdown is. `city_category`
(the heatmap) still has no equivalent here — both filters CAN combine in one
request in principle, but that's 29 cities x 3 categories = 87 calls/scrape
for Sereko, deliberately left unbuilt given the rate-limit issues the city
sweep alone already hit (see `scraper.py`'s `_RELOAD_EVERY`).
"""
import uuid
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_seller_hub import (
    BlinkitSellerHubSalesByProductRO as ByProduct,
    BlinkitSellerHubSalesCategoryDailyRO as CategoryDaily,
    BlinkitSellerHubSalesCityDailyRO as City,
    BlinkitSellerHubSalesDailyRO as Daily,
)

# Shares the old table's slug deliberately — see module docstring.
SLUG = "blinkit"


def wants_blinkit_seller_hub(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Blinkit."""
    return marketplaces is None or SLUG in marketplaces


def _daily_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Daily.tenant_id == tenant_id, Daily.date >= start, Daily.date <= end]


async def _latest_snapshot_date(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> date | None:
    """The one `as_of_date` to read from the by-product table for this window,
    or None if no scrape landed inside [start, end]. Never pick more than one —
    see module docstring."""
    return (
        await session.execute(
            select(func.max(ByProduct.as_of_date)).where(
                ByProduct.tenant_id == tenant_id,
                ByProduct.as_of_date >= start,
                ByProduct.as_of_date <= end,
            )
        )
    ).scalar_one_or_none()


async def sales_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, int]:
    """(revenue, units, distinct SKUs) — mirrors analytics_service._sales_agg.

    Revenue/units from the daily table (real dates, safe to sum). SKU count
    from the single latest by-product snapshot inside the window, or 0 if none
    was taken — an honest gap, not a guess.
    """
    revenue, units = (
        await session.execute(
            select(
                func.coalesce(func.sum(Daily.sales_amount), 0.0),
                func.coalesce(func.sum(Daily.units_sold), 0),
            ).where(*_daily_conds(tenant_id, start, end))
        )
    ).one()

    as_of = await _latest_snapshot_date(session, tenant_id=tenant_id, start=start, end=end)
    skus = 0
    if as_of is not None:
        skus = (
            await session.execute(
                select(func.count(distinct(ByProduct.item_id))).where(
                    ByProduct.tenant_id == tenant_id, ByProduct.as_of_date == as_of
                )
            )
        ).scalar_one()
    return float(revenue), int(units), int(skus)


async def revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    rows = (
        await session.execute(
            select(Daily.date, Daily.sales_amount, Daily.units_sold)
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
    """Top items from the single latest snapshot in the window. Each row's
    revenue covers that snapshot's own rolling window, not [start, end] — the
    caller gets `window_label` ("Last 7 days", ...) to say so honestly rather
    than implying it matches the requested date range."""
    as_of = await _latest_snapshot_date(session, tenant_id=tenant_id, start=start, end=end)
    if as_of is None:
        return []
    revenue = func.coalesce(func.sum(ByProduct.sales_amount), 0.0)
    rows = (
        await session.execute(
            select(
                ByProduct.item_id,
                func.max(ByProduct.product_name),
                revenue,
                func.coalesce(func.sum(ByProduct.units_sold), 0),
                func.max(ByProduct.window_label),
            )
            .where(ByProduct.tenant_id == tenant_id, ByProduct.as_of_date == as_of)
            .group_by(ByProduct.item_id)
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
            "window_label": window_label,
        }
        for item_id, name, rev, units, window_label in rows
    ]


async def sales_by_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Same single-snapshot rule as `top_skus` — see module docstring."""
    as_of = await _latest_snapshot_date(session, tenant_id=tenant_id, start=start, end=end)
    if as_of is None:
        return []
    revenue = func.coalesce(func.sum(ByProduct.sales_amount), 0.0)
    category = func.coalesce(ByProduct.business_category_name, "Uncategorized")
    rows = (
        await session.execute(
            select(category, revenue, func.coalesce(func.sum(ByProduct.units_sold), 0))
            .where(ByProduct.tenant_id == tenant_id, ByProduct.as_of_date == as_of)
            .group_by(category)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {"category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for cat, rev, units in rows
    ]


async def sales_by_city(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Real calendar dates, safe to sum across the whole range — unlike
    `top_skus`/`sales_by_category` above, this table isn't a rolling-window
    snapshot (see `BlinkitSellerHubSalesCityDailyRO`)."""
    revenue = func.coalesce(func.sum(City.sales_amount), 0.0)
    rows = (
        await session.execute(
            select(City.city, revenue, func.coalesce(func.sum(City.units_sold), 0))
            .where(City.tenant_id == tenant_id, City.date >= start, City.date <= end)
            .group_by(City.city)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {"city": city, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for city, rev, units in rows
    ]


async def category_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Per-day revenue/units per category — real calendar dates from
    `blinkit_seller_hub_sales_category_daily_ro`, NOT the rolling-window
    by-product table's category field (that one has no day axis at all).
    Safe to sum across the whole range, same as `revenue_series`."""
    revenue = func.coalesce(func.sum(CategoryDaily.sales_amount), 0.0)
    rows = (
        await session.execute(
            select(CategoryDaily.date, CategoryDaily.category, revenue,
                   func.coalesce(func.sum(CategoryDaily.units_sold), 0))
            .where(
                CategoryDaily.tenant_id == tenant_id,
                CategoryDaily.date >= start,
                CategoryDaily.date <= end,
            )
            .group_by(CategoryDaily.date, CategoryDaily.category)
            .order_by(CategoryDaily.date, CategoryDaily.category)
        )
    ).all()
    return [
        {"date": d, "category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, cat, rev, units in rows
    ]
