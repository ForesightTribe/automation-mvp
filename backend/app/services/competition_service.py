"""Competitive intelligence over public scraped data, viewed through a client's
watchlist. Scoped to the client's OWN brand(s) (relationship='own'); narrow
further with optional keyword/city/marketplace filters.
"""
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.utils.time import now_ist
from app.models.search import SearchListing, SearchSnapshot
from app.schemas.common import Page
from app.schemas.competition import CompetitorRankRow
from app.services import watchlist_service


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


async def get_share_of_voice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    marketplace: str | None = None,
    keyword: str | None = None,
    city: str | None = None,
    days: int = 30,
) -> dict:
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    summary = {
        "brands": own,
        "marketplace": marketplace,
        "keyword": keyword,
        "city": city,
        "period_days": days,
        "latest_sov": None,
        "avg_sov": None,
        "avg_rank": None,
        "total_samples": 0,
    }
    if not own:
        # No 'own' brand on the watchlist -> nothing to report.
        return {"summary": summary, "trend": []}

    since = now_ist() - timedelta(days=days)
    conditions = [
        SearchSnapshot.tenant_id == tenant_id,
        SearchSnapshot.brand_slug.in_(own),
        SearchSnapshot.scraped_at >= since,
    ]
    if marketplace:
        conditions.append(SearchSnapshot.mp_slug == marketplace)
    if keyword:
        conditions.append(SearchSnapshot.keyword == keyword)
    if city:
        conditions.append(SearchSnapshot.city == city)

    day = func.date(SearchSnapshot.scraped_at).label("day")
    rows = (
        await session.execute(
            select(
                day,
                func.avg(SearchSnapshot.brand_sov),
                func.avg(SearchSnapshot.brand_rank),
                func.count(),
            )
            .where(*conditions)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    trend = [
        {"date": d, "avg_sov": _round(sov), "avg_rank": _round(rank, 2), "samples": n}
        for d, sov, rank, n in rows
    ]

    avg_sov, avg_rank, total = (
        await session.execute(
            select(
                func.avg(SearchSnapshot.brand_sov),
                func.avg(SearchSnapshot.brand_rank),
                func.count(),
            ).where(*conditions)
        )
    ).one()

    summary.update(
        latest_sov=trend[-1]["avg_sov"] if trend else None,
        avg_sov=_round(avg_sov),
        avg_rank=_round(avg_rank, 2),
        total_samples=total,
    )
    return {"summary": summary, "trend": trend}


async def get_rankings(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    keyword: str | None = None,
    city: str | None = None,
    marketplace: str | None = None,
    competitor: str | None = None,
) -> Page[CompetitorRankRow]:
    # Competitors are the non-own listing rows in this client's own searches.
    # Tenant-scoped storage means a flat `tenant_id` filter replaces the old
    # watchlist lens; `is_brand=False` excludes the client's own products.
    conditions = [SearchListing.tenant_id == tenant_id, SearchListing.is_brand.is_(False)]
    if keyword:
        conditions.append(SearchListing.keyword == keyword)
    if city:
        conditions.append(SearchListing.city == city)
    if marketplace:
        conditions.append(SearchListing.mp_slug == marketplace)
    if competitor:
        conditions.append(SearchListing.brand_slug == competitor)

    total = (
        await session.execute(
            select(func.count()).select_from(SearchListing).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(SearchListing)
            .where(*conditions)
            .order_by(SearchListing.scraped_at.desc(), SearchListing.position)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()

    items = [
        CompetitorRankRow(
            competitor=r.brand_slug or r.product_name,
            keyword=r.keyword,
            city=r.city,
            zone=r.zone,
            mp_slug=r.mp_slug,
            position=r.position,
            price=r.price,
            scraped_at=r.scraped_at,
        )
        for r in rows
    ]
    return Page.build(items, total, pagination)
