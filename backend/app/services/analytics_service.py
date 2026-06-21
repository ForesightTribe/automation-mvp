"""Analytics aggregations over first-party (client-scoped) dashboard data.

Every function takes `session` first and filters by `tenant_id` (the client).
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_marketing import AdCampaign
from app.models.blinkit_seller import BlinkitSellerSale

Sale = BlinkitSellerSale


async def get_overview(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> dict:
    since = date.today() - timedelta(days=days)

    revenue, units, skus = (
        await session.execute(
            select(
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.count(distinct(Sale.item_id)),
            ).where(Sale.tenant_id == tenant_id, Sale.date >= since)
        )
    ).one()

    spend, impressions, campaigns = (
        await session.execute(
            select(
                func.coalesce(func.sum(AdCampaign.budget_consumed), 0.0),
                func.coalesce(func.sum(AdCampaign.impressions), 0),
                func.count(distinct(AdCampaign.campaign_id)),
            ).where(AdCampaign.tenant_id == tenant_id, AdCampaign.date >= since)
        )
    ).one()

    return {
        "client_id": tenant_id,
        "period_days": days,
        "revenue": round(float(revenue), 2),
        "units_sold": int(units),
        "distinct_skus": int(skus),
        "active_campaigns": int(campaigns),
        "ad_spend": round(float(spend), 2),
        "impressions": int(impressions),
    }


async def get_revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(Sale.tenant_id == tenant_id, Sale.date >= since)
            .group_by(Sale.date)
            .order_by(Sale.date)
        )
    ).all()
    return [
        {"date": d, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, rev, units in rows
    ]


async def get_top_skus(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30, limit: int = 10
) -> list[dict]:
    since = date.today() - timedelta(days=days)
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    rows = (
        await session.execute(
            select(
                Sale.item_id,
                func.max(Sale.item_name),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(Sale.tenant_id == tenant_id, Sale.date >= since)
            .group_by(Sale.item_id)
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


async def get_sales_by_city(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    since = date.today() - timedelta(days=days)
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    rows = (
        await session.execute(
            select(
                Sale.city_id,
                func.max(Sale.city_name),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(Sale.tenant_id == tenant_id, Sale.date >= since)
            .group_by(Sale.city_id)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {
            "city": city_name or city_id,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for city_id, city_name, rev, units in rows
    ]


async def get_sales_by_category(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    since = date.today() - timedelta(days=days)
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    category = func.coalesce(Sale.category, "Uncategorized")
    rows = (
        await session.execute(
            select(
                category,
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(Sale.tenant_id == tenant_id, Sale.date >= since)
            .group_by(category)
            .order_by(revenue.desc())
        )
    ).all()
    return [
        {"category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for cat, rev, units in rows
    ]
