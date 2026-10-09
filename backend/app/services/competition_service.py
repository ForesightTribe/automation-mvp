"""Competitive intelligence over public scraped data, viewed through a client's
watchlist. Scoped to the client's OWN brand(s) (relationship='own'); narrow
further with optional keyword/city/marketplace filters.
"""
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import Integer, case, distinct, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.cache import ttl_cache

# Public-scrape aggregates. Long enough to carry a reading session, short
# enough that a scrape landing is reflected the same working day.
_TTL = 6 * 60 * 60

from app.dependencies import Pagination
from app.models.search import SearchListing, SearchSnapshot
from app.schemas.common import Page
from app.schemas.competition import CompetitorRankRow
from app.services import watchlist_service


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive calendar dates -> half-open [start 00:00, end+1 00:00). Public
    metrics filter on the selected window, not "last N days from now" — anchoring to
    now slides the cutoff past a window that doesn't end today and drops its data."""
    return (
        datetime.combine(start, time.min),
        datetime.combine(end + timedelta(days=1), time.min),
    )


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


# Only searches that RETURNED RESULTS. Since 2026-09-30 the keyword scrape also stores a
# snapshot for a search that came back empty (total_results = 0, rank and SoV NULL), so
# "this keyword returns nothing at this store" can be told apart from "never scraped".
# Those rows are an audit record, not a measurement: avg() already skips their NULLs, but
# a bare count() would include them, and "avg share over N searches" would then quote an
# N larger than the number of searches the average was taken over. Every snapshot query
# below that reports a sample count carries this condition.
_HAS_RESULTS = SearchSnapshot.brand_sov.is_not(None)


# Per-row price at the pack's display basis: ₹/100 ml, ₹/100 g, ₹/piece. NULL when
# the pack is unparseable, heterogeneous (pack_uom ""), or size 0 — so the aggregate
# bands below ignore exactly the rows that can't be compared, without dropping their
# raw-rupee contribution. Comparing raw prices across pack sizes is meaningless (a
# 12-pack vs a single); this is the fair band. Only compare within one UOM.
_UNIT_MULT = case(
    (SearchListing.pack_uom.in_(("ml", "g")), 100.0),
    (SearchListing.pack_uom == "pc", 1.0),
    else_=None,
)
_UNIT_PRICE = SearchListing.price / func.nullif(SearchListing.pack_size, 0) * _UNIT_MULT


@ttl_cache(_TTL)
async def get_share_of_voice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    marketplaces: list[str] | None = None,
    keyword: str | None = None,
    city: str | None = None,
    start: date,
    end: date,
) -> dict:
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    summary = {
        "brands": own,
        "marketplaces": marketplaces,
        "keyword": keyword,
        "city": city,
        "period_days": (end - start).days + 1,
        "latest_sov": None,
        "avg_sov": None,
        "avg_rank": None,
        "total_samples": 0,
    }
    if not own:
        # No 'own' brand on the watchlist -> nothing to report.
        return {"summary": summary, "trend": []}

    lo, hi = _bounds(start, end)
    conditions = [
        SearchSnapshot.tenant_id == tenant_id,
        SearchSnapshot.brand_slug.in_(own),
        SearchSnapshot.scraped_at >= lo,
        SearchSnapshot.scraped_at < hi,
        _HAS_RESULTS,
    ]
    if marketplaces:
        conditions.append(SearchSnapshot.mp_slug.in_(marketplaces))
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
    marketplaces: list[str] | None = None,
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
    if marketplaces:
        conditions.append(SearchListing.mp_slug.in_(marketplaces))
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
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
) -> dict:
    """Own-brand avg rank + SoV per (keyword, city) over the window — the data
    for the "where am I weak?" heatmap. Cells are a flat list; the axes are the
    distinct keywords (rows) and cities (columns)."""
    own = await watchlist_service.get_brands_by_relationship(session, tenant_id, "own")
    empty = {"keywords": [], "cities": [], "cells": [], "period_days": (end - start).days + 1, "as_of": None}
    if not own:
        return empty

    lo, hi = _bounds(start, end)
    cond = [
        SearchSnapshot.tenant_id == tenant_id,
        SearchSnapshot.brand_slug.in_(own),
        SearchSnapshot.scraped_at >= lo,
        SearchSnapshot.scraped_at < hi,
        _HAS_RESULTS,
    ]
    if marketplaces:
        cond.append(SearchSnapshot.mp_slug.in_(marketplaces))

    # `searches` counts snapshots — one search at one probe point — NOT distinct
    # stores. Rank and SoV are what the shopper sees in a blended result list, so the
    # search is the honest sample unit here, and counting searches keeps the whole
    # history usable (rows scraped before 2026-07-18 carry no merchant_id). Store-grain
    # counting belongs where store identity actually matters — see get_top_competitors.
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
            "searches": n,
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
        "period_days": (end - start).days + 1,
        "as_of": as_of,
    }


# --- Competitor leaderboard --------------------------------------------------

@ttl_cache(_TTL)
async def get_top_competitors(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    limit: int = 15,
) -> dict:
    """Which competitors show up in most DARK STORES across the client's searches,
    plus keyword spread, avg position/price, and share of all competitor presences.

    Counts distinct `SearchListing.merchant_id` — the store that fulfils *that
    competitor's product*, which is not necessarily the store serving the coordinate.
    One response can span an express store and one or more longtail hubs, so the old
    version (joining the snapshot for its lat/lon) mis-attributed any competitor
    product served from a hub. Reading the listing's own merchant also drops the join
    entirely.

    ⚠️ Rows scraped before 2026-07-18 have no `merchant_id` and are excluded — store
    presence is meaningless without a store. Expect a shorter window here than on the
    rank/SoV views, which stay search-based and keep their full history."""
    lo, hi = _bounds(start, end)
    cond = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.is_brand.is_(False),
        SearchListing.scraped_at >= lo, SearchListing.scraped_at < hi,
        SearchListing.merchant_id != "",
    ]
    if keyword:
        cond.append(SearchListing.keyword == keyword)
    if city:
        cond.append(SearchListing.city == city)
    if marketplaces:
        cond.append(SearchListing.mp_slug.in_(marketplaces))

    store = SearchListing.merchant_id
    rows = (
        await session.execute(
            select(
                SearchListing.brand_slug,
                func.count(distinct(store)),
                func.count(distinct(SearchListing.keyword)),
                func.avg(SearchListing.position),
                func.avg(SearchListing.price),
                func.max(SearchListing.scraped_at),
            )
            .where(*cond)
            .group_by(SearchListing.brand_slug)
            .order_by(func.count(distinct(store)).desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return {
            "period_days": (end - start).days + 1, "as_of": None,
            "total_competitor_stores": 0, "competitors": [],
        }

    # Total competitor presences = distinct (competitor, store) pairs.
    total = (
        await session.execute(
            select(func.count(distinct(tuple_(SearchListing.brand_slug, store))))
            .where(*cond)
        )
    ).scalar_one()

    competitors = [
        {
            "competitor": slug or "unknown",
            "stores": n_stores,
            "keywords": kw_count,
            "avg_position": _round(pos, 1),
            "avg_price": _price(price),
            "share_pct": _round(n_stores / total * 100, 1) if total else None,
        }
        for slug, n_stores, kw_count, pos, price, _ in rows
    ]
    as_of = max(r[5] for r in rows)
    return {
        "period_days": (end - start).days + 1,
        "as_of": as_of,
        "total_competitor_stores": total,
        "competitors": competitors,
    }


@ttl_cache(_TTL)
async def get_top_competitors_by_marketplace(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    limit: int = 15,
) -> list[dict]:
    """`get_top_competitors`, split by the marketplace each presence was seen on.

    One query, not one per marketplace: `mp_slug` is already a column on
    `search_listings`, so it only has to join the GROUP BY. A competitor selling
    on two marketplaces is two rows — store counts and ranks are per-marketplace
    and adding them would invent a shelf that does not exist.

    Share is of that MARKETPLACE's competitor presences, so each marketplace's
    shares add to 100 on their own.
    """
    lo, hi = _bounds(start, end)
    cond = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.is_brand.is_(False),
        SearchListing.scraped_at >= lo, SearchListing.scraped_at < hi,
        SearchListing.merchant_id != "",
    ]
    if keyword:
        cond.append(SearchListing.keyword == keyword)
    if city:
        cond.append(SearchListing.city == city)
    if marketplaces:
        cond.append(SearchListing.mp_slug.in_(marketplaces))

    store = SearchListing.merchant_id
    rows = (
        await session.execute(
            select(
                SearchListing.mp_slug,
                SearchListing.brand_slug,
                func.count(distinct(store)),
                func.count(distinct(SearchListing.keyword)),
                func.avg(SearchListing.position),
                func.avg(SearchListing.price),
            )
            .where(*cond)
            .group_by(SearchListing.mp_slug, SearchListing.brand_slug)
            .order_by(func.count(distinct(store)).desc())
            .limit(limit)
        )
    ).all()

    totals = dict(
        (
            await session.execute(
                select(
                    SearchListing.mp_slug,
                    func.count(distinct(tuple_(SearchListing.brand_slug, store))),
                )
                .where(*cond)
                .group_by(SearchListing.mp_slug)
            )
        ).all()
    )

    return [
        {
            "marketplace": mp,
            "competitor": slug or "unknown",
            "stores": n_stores,
            "keywords": kw_count,
            "avg_position": _round(pos, 1),
            "avg_price": _price(price),
            "share_pct": (
                _round(n_stores / totals[mp] * 100, 1) if totals.get(mp) else None
            ),
        }
        for mp, slug, n_stores, kw_count, pos, price in rows
    ]


# --- Price positioning (own vs competitor range, per keyword) ----------------

@ttl_cache(_TTL)
async def get_price_position(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
    by_marketplace: bool = False,
) -> dict:
    """Per keyword: the own brand's price band vs the competitor price band, so you
    can see if you're priced into or out of the consideration set. Reports BOTH the
    raw-rupee band (absolute shelf price) and the per-unit band (₹/100 ml · 100 g ·
    piece), the latter being the fair comparison across pack sizes. `unit_uom` names
    the keyword's dominant UOM so the caller can label the basis. `kind` filters
    combos (default `main` = singles, on both own + competitor)."""
    lo, hi = _bounds(start, end)
    base = [SearchListing.tenant_id == tenant_id, SearchListing.scraped_at >= lo, SearchListing.scraped_at < hi,
            SearchListing.price.is_not(None), *_kind_cond(kind)]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    # `by_marketplace` adds one column to the grouping: a price band is per
    # shelf, and both views are built from this one query.
    keys = (
        [SearchListing.mp_slug, SearchListing.keyword]
        if by_marketplace
        else [SearchListing.keyword]
    )
    n_keys = len(keys)

    # Own band per keyword — raw rupees + per-unit. mode() gives the keyword's
    # dominant UOM (drinks-with-drinks in practice), for labelling the basis.
    own_rows = (
        await session.execute(
            select(
                *keys,
                func.avg(SearchListing.price),
                func.min(SearchListing.price),
                func.max(SearchListing.price),
                func.count(),
                func.avg(_UNIT_PRICE),
                func.min(_UNIT_PRICE),
                func.max(_UNIT_PRICE),
                func.mode().within_group(SearchListing.pack_uom.asc()),
                func.count(distinct(SearchListing.platform_product_id)),
            )
            .where(*base, SearchListing.is_brand.is_(True))
            .group_by(*keys)
        )
    ).all()
    own = {tuple(r[:n_keys]): r[n_keys:] for r in own_rows}

    # Competitor band (+ median) per keyword — raw rupees + per-unit.
    comp_rows = (
        await session.execute(
            select(
                *keys,
                func.avg(SearchListing.price),
                func.min(SearchListing.price),
                func.percentile_cont(0.5).within_group(SearchListing.price.asc()),
                func.max(SearchListing.price),
                func.count(),
                func.avg(_UNIT_PRICE),
                func.min(_UNIT_PRICE),
                func.percentile_cont(0.5).within_group(_UNIT_PRICE.asc()),
                func.max(_UNIT_PRICE),
                func.mode().within_group(SearchListing.pack_uom.asc()),
                func.count(distinct(SearchListing.platform_product_id)),
            )
            .where(*base, SearchListing.is_brand.is_(False))
            .group_by(*keys)
        )
    ).all()
    comp = {tuple(r[:n_keys]): r[n_keys:] for r in comp_rows}

    rows = []
    for key in sorted(set(own) | set(comp)):
        o = own.get(key)
        c = comp.get(key)
        # UOM label: prefer own's dominant, fall back to competitors'.
        uom = (o[7] if o else None) or (c[9] if c else None) or ""
        rows.append({
            "marketplace": key[0] if by_marketplace else None,
            "keyword": key[-1],
            "own_avg_price": _price(o[0]) if o else None,
            "own_min_price": _price(o[1]) if o else None,
            "own_max_price": _price(o[2]) if o else None,
            "comp_avg_price": _price(c[0]) if c else None,
            "comp_min_price": _price(c[1]) if c else None,
            "comp_median_price": _price(c[2]) if c else None,
            "comp_max_price": _price(c[3]) if c else None,
            "own_samples": o[3] if o else 0,
            "comp_samples": c[4] if c else 0,
            # ⚠️ The counts above are LISTING ROWS (product x store x scrape day),
            # which overstate the basis by three orders of magnitude — "soda"
            # counts listing rows, not the products behind them.
            # These are the real basis, and what any confidence gate must use.
            "own_products": o[8] if o else 0,
            "comp_products": c[10] if c else 0,
            "unit_uom": uom,
            "own_avg_unit_price": _price(o[4]) if o else None,
            "own_min_unit_price": _price(o[5]) if o else None,
            "own_max_unit_price": _price(o[6]) if o else None,
            "comp_avg_unit_price": _price(c[5]) if c else None,
            "comp_min_unit_price": _price(c[6]) if c else None,
            "comp_median_unit_price": _price(c[7]) if c else None,
            "comp_max_unit_price": _price(c[8]) if c else None,
        })

    as_of = (
        await session.execute(
            select(func.max(SearchListing.scraped_at)).where(*base)
        )
    ).scalar()
    return {"period_days": (end - start).days + 1, "as_of": as_of, "rows": rows}


# ── Competitor benchmarking (ads, discounting, price by store) ───────────────
#
# Reads over the same `search_listings` rows the SoV views use, at three grains.
# No new tables.
#
# ⚠️ `is_ad` is FALSE for every Blinkit row before 2026-09-04 — the marker was
# not captured and cannot be backfilled. A window reaching before that date
# reports those days as 0% paid rather than unknown. Zepto is unaffected.
AD_MARKER_FROM = date(2026, 9, 4)


def _ad_marker_caveat(start: date, mps: list[str] | None) -> str | None:
    """Warning text when the window predates Blinkit's `is_ad` capture."""
    if start >= AD_MARKER_FROM:
        return None
    if mps and "blinkit" not in mps:
        return None
    return (
        f"Blinkit paid placements were not recorded before "
        f"{AD_MARKER_FROM:%-d %b %Y}; earlier days in this window read as 0% paid."
    )


@ttl_cache(_TTL)
async def get_ad_presence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
    by_city: bool = False,
) -> dict:
    """Who is buying search slots, how hard, and how high they land.

    Per brand (optionally per city): how many placements were paid, what share of
    that brand's listings that is, and the average position of its PAID rows.
    Volume and position separate two different strategies — buying the top slot a
    few hundred times, versus blanketing page three — and the pair is the point.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.brand_slug.is_not(None),
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    keys = [SearchListing.brand_slug] + ([SearchListing.city] if by_city else [])
    paid = case((SearchListing.is_ad.is_(True), 1), else_=None)
    rows = (
        await session.execute(
            select(
                *keys,
                func.count().label("listings"),
                func.count(paid).label("paid"),
                # Position of PAID rows only — an organic rank would drag it.
                func.avg(case((SearchListing.is_ad.is_(True), SearchListing.position))),
                func.min(case((SearchListing.is_ad.is_(True), SearchListing.position))),
                func.max(SearchListing.is_brand.cast(Integer)),
            )
            .where(*base)
            .group_by(*keys)
            .having(func.count() > 0)
        )
    ).all()

    out = []
    for r in rows:
        n = len(keys)
        brand, city_val = r[0], (r[1] if by_city else None)
        listings, paid_n, avg_pos, best_pos, own = r[n], r[n + 1], r[n + 2], r[n + 3], r[n + 4]
        out.append({
            "brand": brand,
            "city": city_val,
            "is_own": bool(own),
            "listings": listings,
            "paid_placements": paid_n,
            "paid_share_pct": _round(100.0 * paid_n / listings, 1) if listings else None,
            "avg_paid_position": _round(avg_pos, 1),
            "best_paid_position": best_pos,
        })
    out.sort(key=lambda d: (-(d["paid_placements"] or 0), d["brand"]))
    return {
        "rows": out,
        "by_city": by_city,
        "caveat": _ad_marker_caveat(start, marketplaces),
    }


@ttl_cache(_TTL)
async def get_discount_depth(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
) -> dict:
    """How hard each brand is discounting against the client.

    `discount_pct` is the marketplace's own stated cut off MRP, so this is the
    advertised depth a shopper sees, not a margin estimate. Rows without an MRP
    are excluded rather than counted as 0% — "not on offer" and "we don't know"
    are different, and averaging the second as zero understates everyone.

    `on_offer_share_pct` is the breadth of the promotion: a brand at 30% off on
    two SKUs is a different threat from one at 20% off across its range.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.brand_slug.is_not(None),
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    known = SearchListing.discount_pct.is_not(None)
    discounted = case((SearchListing.discount_pct > 0, 1), else_=None)
    rows = (
        await session.execute(
            select(
                SearchListing.brand_slug,
                func.max(SearchListing.is_brand.cast(Integer)),
                func.count().label("listings"),
                func.count(case((known, 1))).label("priced"),
                func.count(discounted).label("on_offer"),
                func.avg(case((known, SearchListing.discount_pct))),
                func.percentile_cont(0.5).within_group(
                    SearchListing.discount_pct.asc()
                ),
                func.max(SearchListing.discount_pct),
                func.count(distinct(SearchListing.platform_product_id)),
            )
            .where(*base)
            .group_by(SearchListing.brand_slug)
        )
    ).all()

    out = []
    for brand, own, listings, priced, on_offer, avg_d, med_d, max_d, skus in rows:
        out.append({
            "brand": brand,
            "is_own": bool(own),
            "listings": listings,
            "skus": skus,
            # Of the rows where a discount is KNOWN, how many are actually cut.
            "on_offer_share_pct": _round(100.0 * on_offer / priced, 1) if priced else None,
            "avg_discount_pct": _round(avg_d, 1),
            "median_discount_pct": _round(med_d, 1),
            "max_discount_pct": _round(max_d, 1),
        })
    out.sort(key=lambda d: (-(d["avg_discount_pct"] or 0), d["brand"]))
    return {"rows": out}


@ttl_cache(_TTL)
async def get_price_by_store(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
    limit: int = 200,
    min_listings: int = 1,
) -> dict:
    """Own price against the competitor set, store by store.

    The existing price-position view answers "am I priced into the set" for a
    keyword across everywhere. This answers it per dark store, because the same
    SKU is not priced identically across them and a national average hides the
    stores where you are the expensive option.

    Compared on PER-UNIT price (₹/100 ml · 100 g · piece), never raw rupees — a
    12-pack against a single is not a price difference. Rows whose pack cannot be
    parsed carry no per-unit value and drop out of both sides.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.price.is_not(None),
        SearchListing.merchant_id != "",
        _UNIT_MULT.is_not(None),
        SearchListing.pack_size > 0,
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    # ⚠️ pack_uom is part of the KEY — ₹/100 g and ₹/100 ml do not average
    # together. A store selling both bases appears once per basis.
    keys = [
        SearchListing.merchant_id,
        SearchListing.city,
        SearchListing.mp_slug,
        SearchListing.pack_uom,
    ]
    rows = (
        await session.execute(
            select(
                *keys,
                func.avg(case((SearchListing.is_brand.is_(True), _UNIT_PRICE))),
                func.avg(case((SearchListing.is_brand.is_(False), _UNIT_PRICE))),
                func.min(case((SearchListing.is_brand.is_(False), _UNIT_PRICE))),
                func.count(case((SearchListing.is_brand.is_(True), 1))),
                func.count(case((SearchListing.is_brand.is_(False), 1))),
            )
            .where(*base)
            .group_by(*keys)
            # Both sides must be present, at least `min_listings` times each.
            .having(
                func.count(case((SearchListing.is_brand.is_(True), 1))) >= min_listings
            )
            .having(
                func.count(case((SearchListing.is_brand.is_(False), 1))) >= min_listings
            )
        )
    ).all()

    out = []
    for store, city_val, mp, uom, own_p, comp_p, comp_min, own_n, comp_n in rows:
        gap = (
            _round(100.0 * (float(own_p) - float(comp_p)) / float(comp_p), 1)
            if own_p is not None and comp_p
            else None
        )
        out.append({
            "store": store,
            "city": city_val,
            "marketplace": mp,
            "unit_basis": uom,
            "own_unit_price": _price(own_p),
            "competitor_avg_unit_price": _price(comp_p),
            "competitor_cheapest_unit_price": _price(comp_min),
            # Positive = we are the pricier option at this store.
            "gap_vs_competitor_pct": gap,
            "own_listings": own_n,
            "competitor_listings": comp_n,
        })
    # Worst first: the stores where the client is most overpriced are the point.
    out.sort(key=lambda d: -(d["gap_vs_competitor_pct"] or -999))
    return {
        "rows": out[:limit],
        "stores_compared": len(out),
        "min_listings": min_listings,
    }


@ttl_cache(_TTL)
async def get_store_competition(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
    limit: int = 200,
) -> dict:
    """The competitive picture at each dark store: rank, share, and who else is there.

    The store grain the other reads do not cover. `rank-matrix` stops at
    (keyword, city) and `top-competitors` counts how many stores a rival appears
    in without saying which — so "where do I stand in THIS store" had no source.

    Per store: the own brand's average position and share of results, how many
    rival brands are present, and the rival holding the best average position
    there. Worst own rank first, because the weak stores are the point.

    ⚠️ Rows scraped before 2026-07-18 carry no `merchant_id` and are excluded, so
    this view's history is shorter than the keyword-grain ones. Callers should
    say so rather than show a brand as absent.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.merchant_id != "",
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    own = SearchListing.is_brand.is_(True)
    # zone is the locality label and pincode its postal key — both are on the
    # row and both are what a field team actually navigates by.
    keys = [
        SearchListing.merchant_id,
        SearchListing.city,
        SearchListing.mp_slug,
        SearchListing.zone,
        SearchListing.pincode,
    ]

    rows = (
        await session.execute(
            select(
                *keys,
                func.count().label("results"),
                func.count(case((own, 1))).label("own_results"),
                func.avg(case((own, SearchListing.position))).label("own_rank"),
                func.min(case((own, SearchListing.position))).label("own_best"),
                func.count(distinct(case((~own, SearchListing.brand_slug)))).label("rivals"),
                func.count(distinct(case((own, SearchListing.platform_product_id)))).label("own_skus"),
                func.count(case((own & SearchListing.in_stock.is_(True), 1))).label("own_in_stock"),
            )
            .where(*base)
            .group_by(*keys)
        )
    ).all()

    # The strongest rival per store, by average position.
    rival_rows = (
        await session.execute(
            select(
                SearchListing.merchant_id,
                SearchListing.brand_slug,
                func.avg(SearchListing.position),
                func.count(),
            )
            .where(*base, ~own, SearchListing.brand_slug.is_not(None))
            .group_by(SearchListing.merchant_id, SearchListing.brand_slug)
        )
    ).all()
    best_rival: dict[str, tuple[str, float]] = {}
    for store, brand, pos, _n in rival_rows:
        if pos is None:
            continue
        cur = best_rival.get(store)
        if cur is None or float(pos) < cur[1]:
            best_rival[store] = (brand, float(pos))

    out = []
    for (store, city_val, mp, zone, pincode, results, own_n, own_rank,
         own_best, rivals, skus, in_stock) in rows:
        rival = best_rival.get(store)
        out.append({
            "store": store,
            "city": city_val,
            "marketplace": mp,
            "locality": zone,
            "pincode": pincode,
            "results": results,
            "own_listings": own_n,
            # Share of everything returned at this store that was ours.
            "own_share_pct": _round(100.0 * own_n / results, 1) if results else None,
            "own_avg_position": _round(own_rank, 1),
            "own_best_position": own_best,
            "own_skus": skus,
            "own_in_stock_pct": _round(100.0 * in_stock / own_n, 1) if own_n else None,
            "rival_brands": rivals,
            "top_rival": rival[0] if rival else None,
            "top_rival_avg_position": _round(rival[1], 1) if rival else None,
        })
    # Absent (no own listing at all) first, then worst rank downwards — both
    # answer "which store do I fix next". A higher position number is worse.
    out.sort(
        key=lambda d: (d["own_avg_position"] is None, d["own_avg_position"] or 0),
        reverse=True,
    )
    return {"rows": out[:limit], "stores": len(out)}


@ttl_cache(_TTL)
async def get_keyword_presence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
) -> dict:
    """Per keyword: in how many of the stores searched does the brand appear.

    `stores_found / stores_searched` is the honest denominator — a keyword the
    brand wins in three stores out of four is a different fact from one it wins
    in three out of four hundred, and an average rank alone hides both.

    Rank and share are "when found" only. Averaging a missing listing as rank 0
    or as the last position would invent a number the scrape never saw.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.merchant_id != "",
        *_kind_cond(kind),
    ]
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    own = SearchListing.is_brand.is_(True)
    rows = (
        await session.execute(
            select(
                SearchListing.keyword,
                func.count(distinct(SearchListing.merchant_id)),
                func.count(distinct(case((own, SearchListing.merchant_id)))),
                func.avg(case((own, SearchListing.position))),
                func.min(case((own, SearchListing.position))),
                func.count(case((own, 1))),
                func.count(),
            )
            .where(*base)
            .group_by(SearchListing.keyword)
        )
    ).all()

    out = []
    for kw, searched, found, rank, best, own_n, total in rows:
        out.append({
            "keyword": kw,
            "stores_searched": searched,
            "stores_found": found,
            "presence_pct": _round(100.0 * found / searched, 1) if searched else None,
            "avg_rank": _round(rank, 1),
            "best_rank": best,
            # Share of results at the keyword, i.e. how much of the shelf is ours.
            "avg_sov_pct": _round(100.0 * own_n / total, 1) if total else None,
        })
    out.sort(key=lambda d: d["presence_pct"] or 0)
    return {"rows": out}


@ttl_cache(_TTL)
async def get_sku_variance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
) -> dict:
    """Own SKUs: how far price and availability drift between dark stores.

    One SKU is not one price. The spread between the cheapest and dearest store
    is the number worth acting on — a wide band usually means a stale override
    somewhere rather than deliberate local pricing.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.is_brand.is_(True),
        SearchListing.merchant_id != "",
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    rows = (
        await session.execute(
            select(
                SearchListing.product_name,
                func.count(),
                func.count(distinct(SearchListing.merchant_id)),
                func.min(SearchListing.price),
                func.max(SearchListing.price),
                func.avg(SearchListing.price),
                func.count(case((SearchListing.in_stock.is_(True), 1))),
                func.mode().within_group(SearchListing.pack_raw.asc()),
            )
            .where(*base)
            .group_by(SearchListing.product_name)
        )
    ).all()

    out = []
    for name, appearances, stores, lo_p, hi_p, avg_p, in_stock, pack in rows:
        spread = (
            _round(100.0 * (float(hi_p) - float(lo_p)) / float(lo_p), 1)
            if lo_p and hi_p is not None and float(lo_p) > 0
            else None
        )
        out.append({
            "sku": name,
            "pack": pack or "",
            "appearances": appearances,
            "stores": stores,
            "min_price": _price(lo_p),
            "max_price": _price(hi_p),
            "avg_price": _price(avg_p),
            # How much dearer the priciest store is than the cheapest.
            "price_spread_pct": spread,
            "in_stock_pct": _round(100.0 * in_stock / appearances, 1) if appearances else None,
        })
    out.sort(key=lambda d: -(d["price_spread_pct"] or 0))
    return {"rows": out}


@ttl_cache(_TTL)
async def get_brand_comparison(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keyword: str | None = None,
    city: str | None = None,
    marketplaces: list[str] | None = None,
    start: date,
    end: date,
    kind: str = "main",
) -> dict:
    """Every brand on one shelf: what it charges, where it ranks, how widely it is there.

    The question a category manager actually asks — "for this search, who is
    cheaper than me and are they beating me to the top?" — needs price and rank
    in the same row. Reading them off two separate views is what made the
    earlier tables hard to act on.

    Both price bases are returned. `avg_price` is the shelf price a shopper
    sees; `avg_unit_price` normalises for pack size and is the fair comparison,
    but only within one `unit_basis` — a ₹/100 g row and a ₹/100 ml row are not
    comparable, so the caller groups or labels by basis.
    """
    lo, hi = _bounds(start, end)
    base = [
        SearchListing.tenant_id == tenant_id,
        SearchListing.scraped_at >= lo,
        SearchListing.scraped_at < hi,
        SearchListing.brand_slug.is_not(None),
        *_kind_cond(kind),
    ]
    if keyword:
        base.append(SearchListing.keyword == keyword)
    if city:
        base.append(SearchListing.city == city)
    if marketplaces:
        base.append(SearchListing.mp_slug.in_(marketplaces))

    # Denominator for presence: every store that answered any of these searches.
    total_stores = (
        await session.execute(
            select(func.count(distinct(SearchListing.merchant_id))).where(
                *base, SearchListing.merchant_id != ""
            )
        )
    ).scalar() or 0

    rows = (
        await session.execute(
            select(
                SearchListing.brand_slug,
                func.max(SearchListing.is_brand.cast(Integer)),
                func.count(),
                func.count(distinct(SearchListing.merchant_id)),
                func.count(distinct(SearchListing.platform_product_id)),
                func.avg(SearchListing.position),
                func.min(SearchListing.position),
                func.avg(SearchListing.price),
                func.min(SearchListing.price),
                func.max(SearchListing.price),
                func.avg(_UNIT_PRICE),
                func.mode().within_group(SearchListing.pack_uom.asc()),
                func.avg(SearchListing.discount_pct),
                func.count(case((SearchListing.in_stock.is_(True), 1))),
                func.count(case((SearchListing.is_ad.is_(True), 1))),
            )
            .where(*base)
            .group_by(SearchListing.brand_slug)
        )
    ).all()

    out = []
    for (brand, own, listings, stores, skus, rank, best, avg_p, min_p, max_p,
         unit_p, uom, disc, in_stock, paid) in rows:
        out.append({
            "brand": brand,
            "is_own": bool(own),
            "listings": listings,
            "stores": stores,
            "presence_pct": _round(100.0 * stores / total_stores, 1) if total_stores else None,
            "skus": skus,
            "avg_position": _round(rank, 1),
            "best_position": best,
            "avg_price": _price(avg_p),
            "min_price": _price(min_p),
            "max_price": _price(max_p),
            "avg_unit_price": _price(unit_p),
            "unit_basis": uom or "",
            "avg_discount_pct": _round(disc, 1),
            "in_stock_pct": _round(100.0 * in_stock / listings, 1) if listings else None,
            "paid_share_pct": _round(100.0 * paid / listings, 1) if listings else None,
        })
    # Best rank first: the shelf as a shopper meets it.
    out.sort(key=lambda d: (d["avg_position"] is None, d["avg_position"] or 0))
    return {"rows": out, "stores_measured": total_stores, "keyword": keyword}
