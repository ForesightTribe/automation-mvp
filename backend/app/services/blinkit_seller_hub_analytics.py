"""Blinkit NEW-domain (seller.blinkit.com/seller-hub) reads for the Analytics
page — Sereko today, any future account Blinkit migrates off partnersbiz.com
next.

Kept out of `analytics_service.py` for the same reason `zepto_analytics` is:
the source is shaped differently from `blinkit_seller.BlinkitSellerSale`.
Tagged `platform="blinkit"` like the old table (see `blinkit_seller_hub.py`),
so this is additive, not a new filterable marketplace — a tenant is on one
domain or the other, never both, so summing is safe.

SCOPE, as of 2026-10-01: every function below reads
`blinkit_seller_hub_sales_order_ro` (order-level, real item x city x day
grain — see that model's docstring), not the daily/city/category chart
tables this module used to read. Those three are fully derivable from the
order table (`SUM(...) GROUP BY order_date` / `supply_city` /
`business_category`), so reading them separately only ever meant trusting a
second, less granular copy of the same numbers — their tables and any rows
from past runs are left in the database, just not read here anymore.

`blinkit_seller_hub_sales_by_product_ro` is STILL used, but only for fields
the order table doesn't have at all: Blinkit's own computed "top selling"/
product-expansion signals (`is_transitioned`, `transition_date`,
`sales_contribution_pct`). `top_skus`/`sales_by_category` moved OFF it onto
the order table — the old ByProduct-based versions could only ever answer
"top items over whatever rolling window was last scraped," never the exact
requested date range; the order table answers the real question honestly.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_seller_hub import BlinkitSellerHubSalesOrderRO as Order

# Shares the old table's slug deliberately — see module docstring.
SLUG = "blinkit"


def wants_blinkit_seller_hub(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Blinkit."""
    return marketplaces is None or SLUG in marketplaces


def _conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Order.tenant_id == tenant_id, Order.order_date >= start, Order.order_date <= end]


async def sales_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, int]:
    """(revenue, units, distinct SKUs) — real order-level data, safe to sum
    across any date range."""
    revenue, units, skus = (
        await session.execute(
            select(
                func.coalesce(func.sum(Order.total_gross_amount), 0.0),
                func.coalesce(func.sum(Order.quantity), 0),
                func.count(func.distinct(Order.item_id)),
            ).where(*_conds(tenant_id, start, end))
        )
    ).one()
    return float(revenue), int(units), int(skus)


async def revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    rows = (
        await session.execute(
            select(
                Order.order_date,
                func.coalesce(func.sum(Order.total_gross_amount), 0.0),
                func.coalesce(func.sum(Order.quantity), 0),
            )
            .where(*_conds(tenant_id, start, end))
            .group_by(Order.order_date)
            .order_by(Order.order_date)
        )
    ).all()
    return [
        {"date": d, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, rev, units in rows
    ]


async def top_skus(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date, limit: int = 10
) -> list[dict]:
    """Top items for the EXACT requested date range — not a rolling-window
    approximation (see module docstring)."""
    revenue = func.coalesce(func.sum(Order.total_gross_amount), 0.0)
    rows = (
        await session.execute(
            select(
                Order.item_id,
                func.max(Order.product_name),
                revenue,
                func.coalesce(func.sum(Order.quantity), 0),
            )
            .where(*_conds(tenant_id, start, end))
            .group_by(Order.item_id)
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
    revenue = func.coalesce(func.sum(Order.total_gross_amount), 0.0)
    category = func.coalesce(Order.business_category, "Uncategorized")
    rows = (
        await session.execute(
            select(category, revenue, func.coalesce(func.sum(Order.quantity), 0))
            .where(*_conds(tenant_id, start, end))
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
    """Grouped by `supply_city` (where the order shipped FROM — the seller's
    own distribution footprint), not `customer_city` (where it was
    delivered TO). Not independently confirmed which one the old
    city-filtered dashboard chart matched — supply_city is the natural
    reading for a SELLER dashboard's "sales by city," and it's what the
    table's own index is built on."""
    revenue = func.coalesce(func.sum(Order.total_gross_amount), 0.0)
    city = func.coalesce(Order.supply_city, "Unknown")
    rows = (
        await session.execute(
            select(city, revenue, func.coalesce(func.sum(Order.quantity), 0))
            .where(*_conds(tenant_id, start, end))
            .group_by(city)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {"city": city_name, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for city_name, rev, units in rows
    ]


async def category_trend(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    revenue = func.coalesce(func.sum(Order.total_gross_amount), 0.0)
    category = func.coalesce(Order.business_category, "Uncategorized")
    rows = (
        await session.execute(
            select(Order.order_date, category, revenue, func.coalesce(func.sum(Order.quantity), 0))
            .where(*_conds(tenant_id, start, end))
            .group_by(Order.order_date, category)
            .order_by(Order.order_date, category)
        )
    ).all()
    return [
        {"date": d, "category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, cat, rev, units in rows
    ]
