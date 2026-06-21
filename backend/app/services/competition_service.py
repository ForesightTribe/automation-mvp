"""Competitive intelligence over public scraped data, viewed through a client's
watchlist. Scoped to the client's OWN brand(s) (relationship='own'); narrow
further with optional keyword/city/marketplace filters.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.search import CompetitorRanking, SearchResult
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

    since = datetime.utcnow() - timedelta(days=days)
    conditions = [SearchResult.brand_slug.in_(own), SearchResult.scraped_at >= since]
    if marketplace:
        conditions.append(SearchResult.mp_slug == marketplace)
    if keyword:
        conditions.append(SearchResult.keyword == keyword)
    if city:
        conditions.append(SearchResult.city == city)

    day = func.date(SearchResult.scraped_at).label("day")
    rows = (
        await session.execute(
            select(
                day,
                func.avg(SearchResult.brand_sov),
                func.avg(SearchResult.brand_rank),
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
                func.avg(SearchResult.brand_sov),
                func.avg(SearchResult.brand_rank),
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
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    if not own:
        return Page.build([], 0, pagination)

    conditions = [CompetitorRanking.brand_slug.in_(own)]
    if keyword:
        conditions.append(CompetitorRanking.keyword == keyword)
    if city:
        conditions.append(CompetitorRanking.city == city)
    if marketplace:
        conditions.append(CompetitorRanking.mp_slug == marketplace)
    if competitor:
        conditions.append(CompetitorRanking.competitor == competitor)

    total = (
        await session.execute(
            select(func.count()).select_from(CompetitorRanking).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(CompetitorRanking)
            .where(*conditions)
            .order_by(CompetitorRanking.scraped_at.desc(), CompetitorRanking.position)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()

    items = [CompetitorRankRow.model_validate(r) for r in rows]
    return Page.build(items, total, pagination)
