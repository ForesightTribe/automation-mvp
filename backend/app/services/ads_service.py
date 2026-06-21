"""Marketing / advertising data for a client (paid activity on the platform)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_marketing import (
    AdCampaign,
    AdPerformanceSummary,
    BrandCollection,
    SponsoredSOV,
    VisibilityPlan,
)
from app.schemas.ads import CampaignRow
from app.schemas.common import Page


async def get_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 30,
    status: str | None = None,
) -> Page[CampaignRow]:
    since = date.today() - timedelta(days=days)
    conditions = [AdCampaign.tenant_id == tenant_id, AdCampaign.date >= since]
    if status:
        conditions.append(AdCampaign.status == status)

    # DISTINCT ON (campaign_id) ordered by date desc -> latest snapshot per campaign.
    rows = (
        await session.execute(
            select(AdCampaign)
            .where(*conditions)
            .order_by(AdCampaign.campaign_id, AdCampaign.date.desc())
            .distinct(AdCampaign.campaign_id)
        )
    ).scalars().all()

    # Campaign count per client is small -> rank + paginate in memory.
    rows.sort(key=lambda c: c.budget_consumed or 0, reverse=True)
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [CampaignRow.model_validate(c) for c in page]
    return Page.build(items, total, pagination)


async def get_performance(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[dict]:
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                AdPerformanceSummary.date,
                func.coalesce(func.sum(AdPerformanceSummary.budget_consumed), 0.0),
                func.coalesce(func.sum(AdPerformanceSummary.impressions), 0),
            )
            .where(
                AdPerformanceSummary.tenant_id == tenant_id,
                AdPerformanceSummary.date >= since,
            )
            .group_by(AdPerformanceSummary.date)
            .order_by(AdPerformanceSummary.date)
        )
    ).all()
    return [
        {"date": d, "budget_consumed": round(float(b), 2), "impressions": int(i)}
        for d, b, i in rows
    ]


async def get_sponsored_sov(
    session: AsyncSession, *, tenant_id: uuid.UUID, days: int = 30
) -> list[SponsoredSOV]:
    since = date.today() - timedelta(days=days)
    rows = (
        await session.execute(
            select(SponsoredSOV)
            .where(SponsoredSOV.tenant_id == tenant_id, SponsoredSOV.date >= since)
            .order_by(SponsoredSOV.keyword, SponsoredSOV.date.desc())
            .distinct(SponsoredSOV.keyword)
        )
    ).scalars().all()
    rows.sort(key=lambda r: r.sov, reverse=True)
    return rows


async def get_visibility_plans(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[VisibilityPlan]:
    return (
        await session.execute(
            select(VisibilityPlan)
            .where(VisibilityPlan.tenant_id == tenant_id)
            .order_by(VisibilityPlan.budget.desc())
        )
    ).scalars().all()


async def get_collections(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BrandCollection]:
    return (
        await session.execute(
            select(BrandCollection)
            .where(BrandCollection.tenant_id == tenant_id)
            .order_by(BrandCollection.number_of_products.desc())
        )
    ).scalars().all()
