"""Competitive-intelligence queries over public scraped data.

Public domain: keyed by brand_slug + marketplace + city, no tenant scoping.
Pattern for the whole codebase: services take `session` first, accept filters
as keyword args, and return plain dicts / Pydantic models that the route's
`response_model` validates.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.search import CompetitorRanking, SearchResult
from app.schemas.common import Page
from app.schemas.competition import CompetitorRankRow


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


async def get_share_of_voice(
    session: AsyncSession,
    *,
    brand_slug: str,
    marketplace: str | None = None,
    keyword: str | None = None,
    city: str | None = None,
    days: int = 30,
) -> dict:
    since = datetime.utcnow() - timedelta(days=days)

    conditions = [
        SearchResult.brand_slug == brand_slug,
        SearchResult.scraped_at >= since,
    ]
    if marketplace:
        conditions.append(SearchResult.mp_slug == marketplace)
    if keyword:
        conditions.append(SearchResult.keyword == keyword)
    if city:
        conditions.append(SearchResult.city == city)

    # Daily trend
    day = func.date(SearchResult.scraped_at).label("day")
    trend_stmt = (
        select(
            day,
            func.avg(SearchResult.brand_sov).label("avg_sov"),
            func.avg(SearchResult.brand_rank).label("avg_rank"),
            func.count().label("samples"),
        )
        .where(*conditions)
        .group_by(day)
        .order_by(day)
    )
    rows = (await session.execute(trend_stmt)).all()
    trend = [
        {
            "date": r.day,
            "avg_sov": _round(r.avg_sov),
            "avg_rank": _round(r.avg_rank, 2),
            "samples": r.samples,
        }
        for r in rows
    ]

    # Period summary
    summary_stmt = select(
        func.avg(SearchResult.brand_sov),
        func.avg(SearchResult.brand_rank),
        func.count(),
    ).where(*conditions)
    avg_sov, avg_rank, total = (await session.execute(summary_stmt)).one()

    return {
        "summary": {
            "brand_slug": brand_slug,
            "marketplace": marketplace,
            "keyword": keyword,
            "city": city,
            "period_days": days,
            "latest_sov": trend[-1]["avg_sov"] if trend else None,
            "avg_sov": _round(avg_sov),
            "avg_rank": _round(avg_rank, 2),
            "total_samples": total,
        },
        "trend": trend,
    }


async def get_rankings(
    session: AsyncSession,
    *,
    pagination: Pagination,
    keyword: str | None = None,
    city: str | None = None,
    marketplace: str | None = None,
    competitor: str | None = None,
) -> Page[CompetitorRankRow]:
    conditions = []
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
