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


def _price(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _kind_cond(kind: str) -> list:
    """Combo/multipack filter for listings (own + competitor). Combos are priced
    higher, so price comparisons default to `main` (singles). `combo` / `all` too."""
    if kind == "combo":
        return [SearchListing.is_combo.is_(True)]
    if kind == "all":
        return []
    return [SearchListing.is_combo.is_(False)]


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


# --- Rank matrix (keyword × city heatmap) -----------------------------------

async def get_rank_matrix(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    marketplace: str | None = None,
    days: int = 30,
) -> dict:
    """Own-brand avg rank + SoV per (keyword, city) over the window — the data
    for the "where am I weak?" heatmap. Cells are a flat list; the axes are the
    distinct keywords (rows) and cities (columns)."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"keywords": [], "cities": [], "cells": [], "period_days": days, "as_of": None}
    if not own:
        return empty

    since = now_ist() - timedelta(days=days)
    cond = [
        SearchSnapshot.tenant_id == tenant_id,
        SearchSnapshot.brand_slug.in_(own),
        SearchSnapshot.scraped_at >= since,
    ]
    if marketplace:
        cond.append(SearchSnapshot.mp_slug == marketplace)

    rows = (
        await session.execute(
            select(
                SearchSnapshot.keyword,
                SearchSnapshot.city,
                func.avg(SearchSnapshot.brand_rank),
                func.avg(SearchSnapshot.brand_sov),
                func.count(),
                func.max(SearchSnapshot.scraped_at),
            )
            .where(*cond)
            .group_by(SearchSnapshot.keyword, SearchSnapshot.city)
            .order_by(SearchSnapshot.keyword, SearchSnapshot.city)
        )
    ).all()
    if not rows:
        return empty

    cells = [
        {
            "keyword": kw,
            "city": city,
            "avg_rank": _round(rank, 2),
            "avg_sov": _round(sov),
            "samples": n,
        }
        for kw, city, rank, sov, n, _ in rows
    ]
    keywords = sorted({c["keyword"] for c in cells})
    cities = sorted({c["city"] for c in cells})
    as_of = max(r[5] for r in rows)
    return {
        "keywords": keywords,
        "cities": cities,
        "cells": cells,
        "period_days": days,
        "as_of": as_of,
    }


# --- Competitor leaderboard --------------------------------------------------

async def get_top_competitors(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplace: str | None = None,
    days: int = 30,
    limit: int = 15,
) -> dict:
    """Which competitors show up most across the client's searches — appearances,
    keyword spread, avg position/price, and share of all competitor appearances."""
    since = now_ist() - timedelta(days=days)
    cond = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.is_brand.is_(False),
        SearchListing.scraped_at >= since,
    ]
    if keyword:
        cond.append(SearchListing.keyword == keyword)
    if city:
        cond.append(SearchListing.city == city)
    if marketplace:
        cond.append(SearchListing.mp_slug == marketplace)

    rows = (
        await session.execute(
            select(
                SearchListing.brand_slug,
                func.count(),
                func.count(func.distinct(SearchListing.keyword)),
                func.avg(SearchListing.position),
                func.avg(SearchListing.price),
                func.max(SearchListing.scraped_at),
            )
            .where(*cond)
            .group_by(SearchListing.brand_slug)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return {
            "period_days": days, "as_of": None,
            "total_competitor_appearances": 0, "competitors": [],
        }

    total = (
        await session.execute(
            select(func.count()).select_from(SearchListing).where(*cond)
        )
    ).scalar_one()

    competitors = [
        {
            "competitor": slug or "unknown",
            "appearances": appears,
            "keywords": kw_count,
            "avg_position": _round(pos, 1),
            "avg_price": _price(price),
            "share_pct": _round(appears / total * 100, 1) if total else None,
        }
        for slug, appears, kw_count, pos, price, _ in rows
    ]
    as_of = max(r[5] for r in rows)
    return {
        "period_days": days,
        "as_of": as_of,
        "total_competitor_appearances": total,
        "competitors": competitors,
    }


# --- Price positioning (own vs competitor range, per keyword) ----------------

async def get_price_position(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplace: str | None = None,
    days: int = 30,
    kind: str = "main",
) -> dict:
    """Per keyword: the own brand's price band vs the competitor price band, so
    you can see if you're priced into or out of the consideration set. `kind`
    filters combos/multipacks (default `main` = singles, on both own + competitor)."""
    since = now_ist() - timedelta(days=days)
    base = [SearchListing.tenant_id == tenant_id, SearchListing.scraped_at >= since,
            SearchListing.price.is_not(None), *_kind_cond(kind)]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplace:
        base.append(SearchListing.mp_slug == marketplace)

    # Own price band per keyword.
    own_rows = (
        await session.execute(
            select(
                SearchListing.keyword,
                func.avg(SearchListing.price),
                func.min(SearchListing.price),
                func.max(SearchListing.price),
                func.count(),
            )
            .where(*base, SearchListing.is_brand.is_(True))
            .group_by(SearchListing.keyword)
        )
    ).all()
    own = {kw: (avg, mn, mx, n) for kw, avg, mn, mx, n in own_rows}

    # Competitor price band (+ median) per keyword.
    comp_rows = (
        await session.execute(
            select(
                SearchListing.keyword,
                func.avg(SearchListing.price),
                func.min(SearchListing.price),
                func.percentile_cont(0.5).within_group(SearchListing.price.asc()),
                func.max(SearchListing.price),
                func.count(),
            )
            .where(*base, SearchListing.is_brand.is_(False))
            .group_by(SearchListing.keyword)
        )
    ).all()
    comp = {kw: (avg, mn, med, mx, n) for kw, avg, mn, med, mx, n in comp_rows}

    keywords = sorted(set(own) | set(comp))
    rows = []
    for kw in keywords:
        o = own.get(kw)
        c = comp.get(kw)
        rows.append({
            "keyword": kw,
            "own_avg_price": _price(o[0]) if o else None,
            "own_min_price": _price(o[1]) if o else None,
            "own_max_price": _price(o[2]) if o else None,
            "comp_avg_price": _price(c[0]) if c else None,
            "comp_min_price": _price(c[1]) if c else None,
            "comp_median_price": _price(c[2]) if c else None,
            "comp_max_price": _price(c[3]) if c else None,
            "own_samples": o[3] if o else 0,
            "comp_samples": c[4] if c else 0,
        })

    as_of = (
        await session.execute(
            select(func.max(SearchListing.scraped_at)).where(*base)
        )
    ).scalar()
    return {"period_days": days, "as_of": as_of, "rows": rows}
