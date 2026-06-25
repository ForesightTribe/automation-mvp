"""Marketing / advertising data for a client (paid activity on the platform).

Metrics come from the per-campaign daily backbone (`BlinkitAdCampaignDaily`);
`BlinkitAdCampaign` supplies campaign metadata. RoAS is always recomputed as
ad_sales / spend over the window (never an average of daily ratios)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_marketing import (
    BlinkitAdCampaign,
    BlinkitAdCampaignDaily,
    BlinkitBrandCollection,
    BlinkitSponsoredSOV,
    BlinkitVisibilityPlan,
)
from app.schemas.ads import CampaignRow
from app.schemas.common import Page

AdDaily = BlinkitAdCampaignDaily


def _roas(ad_sales: float, spend: float) -> float:
    return round(ad_sales / spend, 4) if spend else 0.0


async def get_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 30,
    status: str | None = None,
) -> Page[CampaignRow]:
    since = date.today() - timedelta(days=days)

    # Per-campaign rollup of the daily backbone over the window.
    rollups = (
        await session.execute(
            select(
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.atc), 0),
                func.coalesce(func.sum(AdDaily.quantities_sold), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(AdDaily.tenant_id == tenant_id, AdDaily.date >= since)
            .group_by(AdDaily.campaign_id)
        )
    ).all()
    metrics = {
        cid: {
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "atc": int(a),
            "quantities_sold": int(q),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for cid, b, i, a, q, s in rollups
    }

    # Campaign metadata (latest snapshot, one row per campaign).
    conds = [BlinkitAdCampaign.tenant_id == tenant_id]
    if status:
        conds.append(BlinkitAdCampaign.status == status)
    campaigns = (
        await session.execute(select(BlinkitAdCampaign).where(*conds))
    ).scalars().all()

    zeros = {
        "budget_consumed": 0.0,
        "impressions": 0,
        "atc": 0,
        "quantities_sold": 0,
        "ad_sales": 0.0,
        "roas": 0.0,
    }
    rows = [
        {
            "campaign_id": c.campaign_id,
            "name": c.name,
            "type": c.type,
            "status": c.status,
            **metrics.get(c.campaign_id, zeros),
        }
        for c in campaigns
    ]

    # Campaign count per client is small -> rank + paginate in memory.
    rows.sort(key=lambda r: r["budget_consumed"], reverse=True)
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [CampaignRow.model_validate(r) for r in page]
    return Page.build(items, total, pagination)


async def get_performance(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    """Daily account totals (summed across campaigns) — replaces the old
    performance-summary table."""
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(AdDaily.tenant_id == tenant_id, AdDaily.date >= since)
            .group_by(AdDaily.date)
            .order_by(AdDaily.date)
        )
    ).all()
    return [
        {
            "date": d,
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "ad_sales": round(float(s), 2),
        }
        for d, b, i, s in rows
    ]


async def get_sponsored_sov(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[BlinkitSponsoredSOV]:
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(BlinkitSponsoredSOV)
            .where(
                BlinkitSponsoredSOV.tenant_id == tenant_id,
                BlinkitSponsoredSOV.date >= since,
            )
            .order_by(BlinkitSponsoredSOV.keyword, BlinkitSponsoredSOV.date.desc())
            .distinct(BlinkitSponsoredSOV.keyword)
        )
    ).scalars().all()
    rows.sort(key=lambda r: r.sov, reverse=True)
    return rows


async def get_visibility_plans(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitVisibilityPlan]:
    return (
        await session.execute(
            select(BlinkitVisibilityPlan)
            .where(BlinkitVisibilityPlan.tenant_id == tenant_id)
            .order_by(BlinkitVisibilityPlan.budget.desc())
        )
    ).scalars().all()


async def get_collections(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitBrandCollection]:
    return (
        await session.execute(
            select(BlinkitBrandCollection)
            .where(BlinkitBrandCollection.tenant_id == tenant_id)
            .order_by(BlinkitBrandCollection.number_of_products.desc())
        )
    ).scalars().all()
