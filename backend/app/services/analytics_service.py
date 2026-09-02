"""Analytics aggregations over first-party (client-scoped) dashboard data.

Every function takes `session` first and filters by `tenant_id` (the client).
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_marketing import BlinkitAdCampaignDaily
from app.models.blinkit_seller import BlinkitSellerSale
from app.models.search import SearchSnapshot
from app.services import watchlist_service, zepto_ads, zepto_analytics

Sale = BlinkitSellerSale
AdDaily = BlinkitAdCampaignDaily


def _merge_series(
    a: list[dict], b: list[dict], key: str | tuple[str, ...], sums: tuple[str, ...]
) -> list[dict]:
    """Combine two same-shaped series, adding `sums` where `key` collides.

    Zepto's rows live in their own tables (different grain, no city dimension),
    so cross-marketplace totals are merged here rather than in SQL. `key` may be
    a tuple for series keyed on more than one field, e.g. (date, category).
    Sorted by key so a merged series is still ordered for charting.
    """
    fields = (key,) if isinstance(key, str) else key
    out: dict = {}
    for row in [*a, *b]:
        k = tuple(row[f] for f in fields)
        if k in out:
            for f in sums:
                out[k][f] = out[k][f] + row[f]
        else:
            out[k] = dict(row)
    return [out[k] for k in sorted(out)]


def _metric(value: float | None, prev: float | None) -> dict:
    """Pack a value + its previous-period value + growth. `delta_pct` is None
    when there's no prior value to grow from (avoids divide-by-zero / inf)."""
    v = None if value is None else round(float(value), 4)
    p = None if prev is None else round(float(prev), 4)
    delta = None if v is None or not p else round((v - p) / p, 4)
    return {"value": v, "prev": p, "delta_pct": delta}


async def _sales_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None,
) -> tuple[float, int, int]:
    """(revenue, units, distinct SKUs) for one window, optionally per platform."""
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    rev, units, skus = (
        await session.execute(
            select(
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.count(distinct(Sale.item_id)),
            ).where(*conds)
        )
    ).one()

    if zepto_analytics.wants_zepto(marketplaces):
        z_rev, z_units, z_skus = await zepto_analytics.sales_agg(
            session, tenant_id=tenant_id, start=start, end=end
        )
        # SKU counts add rather than dedupe: a SKU is per-marketplace here, so
        # the same physical product listed on both is two sellable items.
        rev, units, skus = rev + z_rev, units + z_units, skus + z_skus

    return rev, units, skus


async def _ads_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None,
) -> tuple[float, int, float]:
    """(spend, impressions, ad_sales) for one window, optionally per platform.
    Summed from the per-campaign daily backbone — additive bases only; RoAS is
    recomputed by the caller as ad_sales / spend."""
    conds = [
        AdDaily.tenant_id == tenant_id,
        AdDaily.date >= start,
        AdDaily.date <= end,
    ]
    if marketplaces is not None:
        conds.append(AdDaily.platform.in_(marketplaces))
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            ).where(*conds)
        )
    ).one()

    # Zepto's ads live on their own table, so the query above cannot see them.
    # Merged here rather than at each call site because this is the shared
    # backbone for the Overview marketplace cards, the Analytics ad metrics and
    # the Ads per-marketplace breakdown — all three reported Zepto as zero spend
    # while the Ads summary tiles showed the real figure.
    if zepto_ads.wants_zepto(marketplaces):
        z = await zepto_ads.ads_agg(session, tenant_id=tenant_id, start=start, end=end)
        totals = tuple(a + b for a, b in zip(totals, z))

    return totals


async def _market_agg(
    session: AsyncSession,
    *,
    own_brands: list[str],
    start: date,
    end: date,
    marketplaces: list[str] | None,
) -> tuple[float | None, float | None]:
    """(avg visibility/SOV, avg rank) over own brands' public samples for one
    window. Returns (None, None) when there are no samples."""
    if not own_brands:
        return None, None
    sr_day = func.date(SearchSnapshot.scraped_at)
    conds = [
        SearchSnapshot.brand_slug.in_(own_brands),
        sr_day >= start,
        sr_day <= end,
    ]
    if marketplaces is not None:
        conds.append(SearchSnapshot.mp_slug.in_(marketplaces))
    return (
        await session.execute(
            select(
                func.avg(SearchSnapshot.brand_sov),
                func.avg(SearchSnapshot.brand_rank),
            ).where(*conds)
        )
    ).one()


def _roas(revenue: float, spend: float) -> float | None:
    """Blended RoAS = revenue / spend. None when there's no spend to divide by."""
    return round(float(revenue) / float(spend), 4) if spend else None


async def get_overview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    marketplaces: list[str] | None = None,
) -> dict:
    own = await watchlist_service.get_brands_by_relationship(
        session, tenant_id, "own"
    )

    rev, units, skus = await _sales_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
    )
    p_rev, p_units, p_skus = await _sales_agg(
        session,
        tenant_id=tenant_id,
        start=prev_start,
        end=prev_end,
        marketplaces=marketplaces,
    )
    spend, impr, ad_sales = await _ads_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
    )
    p_spend, p_impr, p_ad_sales = await _ads_agg(
        session,
        tenant_id=tenant_id,
        start=prev_start,
        end=prev_end,
        marketplaces=marketplaces,
    )
    sov, rank = await _market_agg(
        session, own_brands=own, start=start, end=end, marketplaces=marketplaces
    )
    p_sov, p_rank = await _market_agg(
        session,
        own_brands=own,
        start=prev_start,
        end=prev_end,
        marketplaces=marketplaces,
    )

    return {
        "client_id": tenant_id,
        "start": start,
        "end": end,
        "marketplaces": marketplaces,
        "revenue": _metric(rev, p_rev),
        # Organic = store revenue not attributed to ads (clamped at 0).
        "organic_revenue": _metric(
            max(0.0, float(rev) - float(ad_sales)),
            max(0.0, float(p_rev) - float(p_ad_sales)),
        ),
        "units_sold": _metric(units, p_units),
        "distinct_skus": _metric(skus, p_skus),
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(ad_sales, p_ad_sales),
        "impressions": _metric(impr, p_impr),
        "roas": _metric(_roas(ad_sales, spend), _roas(p_ad_sales, p_spend)),
        "visibility": _metric(sov, p_sov),
        "avg_rank": _metric(rank, p_rank),
    }


async def get_revenue_series(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds)
            .group_by(Sale.date)
            .order_by(Sale.date)
        )
    ).all()
    series = [
        {"date": d, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for d, rev, units in rows
    ]
    if zepto_analytics.wants_zepto(marketplaces):
        z = await zepto_analytics.revenue_series(
            session, tenant_id=tenant_id, start=start, end=end
        )
        series = _merge_series(series, z, "date", ("revenue", "units_sold"))
    return series


async def get_trends(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Unified daily series for the Overview charts + KPI sparklines: ad spend,
    ad sales, impressions (from the ad backbone) and revenue, units (from seller
    sales), aligned on a full date spine. A metric is None on days its source has
    no row, so charts show honest gaps instead of fake zeros."""
    ad_conds = [AdDaily.tenant_id == tenant_id, AdDaily.date >= start, AdDaily.date <= end]
    sale_conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        ad_conds.append(AdDaily.platform.in_(marketplaces))
        sale_conds.append(Sale.platform.in_(marketplaces))

    ad_rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
            )
            .where(*ad_conds)
            .group_by(AdDaily.date)
        )
    ).all()
    ad_map = {d: (sp, sa, im) for d, sp, sa, im in ad_rows}

    # Zepto ads live in their own table, so without this the Overview's ad chart
    # reads "no ad data" for a Zepto-only client that is in fact spending daily.
    # Added into the Blinkit figures, not over them: with both marketplaces
    # selected a day carries the spend of both.
    if zepto_ads.wants_zepto(marketplaces):
        for d, (sp, sa, im) in (
            await zepto_ads.trend_series(
                session, tenant_id=tenant_id, start=start, end=end
            )
        ).items():
            b_sp, b_sa, b_im = ad_map.get(d, (0.0, 0.0, 0))
            ad_map[d] = (b_sp + sp, b_sa + sa, b_im + im)

    sale_rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*sale_conds)
            .group_by(Sale.date)
        )
    ).all()
    sale_map = {d: (rev, units) for d, rev, units in sale_rows}

    if zepto_analytics.wants_zepto(marketplaces):
        for row in await zepto_analytics.revenue_series(
            session, tenant_id=tenant_id, start=start, end=end
        ):
            prev = sale_map.get(row["date"], (0.0, 0))
            sale_map[row["date"]] = (
                prev[0] + row["revenue"],
                prev[1] + row["units_sold"],
            )

    out = []
    day = start
    while day <= end:
        a = ad_map.get(day)
        s = sale_map.get(day)
        out.append(
            {
                "date": day,
                "ad_spend": round(float(a[0]), 2) if a else None,
                "ad_sales": round(float(a[1]), 2) if a else None,
                "impressions": int(a[2]) if a else None,
                "revenue": round(float(s[0]), 2) if s else None,
                "units": int(s[1]) if s else None,
            }
        )
        day += timedelta(days=1)
    return out


async def get_top_skus(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    rows = (
        await session.execute(
            select(
                Sale.item_id,
                func.max(Sale.item_name),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds)
            .group_by(Sale.item_id)
            .order_by(revenue.desc())
            .limit(limit)
        )
    ).all()
    skus = [
        {
            "item_id": item_id,
            "item_name": name,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for item_id, name, rev, units in rows
    ]
    if zepto_analytics.wants_zepto(marketplaces):
        z = await zepto_analytics.top_skus(
            session, tenant_id=tenant_id, start=start, end=end, limit=limit
        )
        # Each side is already its own top-N; re-sort the union and re-cut so
        # the result is the true top-N across both, not 2N rows.
        skus = sorted([*skus, *z], key=lambda r: r["revenue"], reverse=True)[:limit]
    return skus


async def get_sales_by_city(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    rows = (
        await session.execute(
            select(
                Sale.city_id,
                func.max(Sale.city_name),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds)
            .group_by(Sale.city_id)
            .order_by(revenue.desc())
        )
    ).all()
    out = [
        {
            "city": city_name or city_id,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for city_id, city_name, rev, units in rows
    ]

    # Zepto's per-city sales live on their own table — its sales response has no
    # city dimension, so the split is scraped one city at a time. Merged here,
    # like _sales_agg already does for the brand totals, so the Revenue-by-city
    # chart covers both marketplaces instead of silently being Blinkit-only.
    #
    # City names are marketplace-specific and are NOT reconciled: Zepto reports
    # "BLR - Bengaluru" where Blinkit reports "Bengaluru". Merging them by name
    # would need a mapping that does not exist yet, and guessing would combine
    # two marketplaces' revenue under a name that might not match either.
    if zepto_analytics.wants_zepto(marketplaces):
        out.extend(
            await zepto_analytics.sales_by_city(
                session, tenant_id=tenant_id, start=start, end=end
            )
        )
        out.sort(key=lambda r: r["revenue"], reverse=True)

    return out


async def get_sales_by_category(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    category = func.coalesce(Sale.category, "Uncategorized")
    rows = (
        await session.execute(
            select(
                category,
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds)
            .group_by(category)
            .order_by(revenue.desc())
        )
    ).all()
    cats = [
        {"category": cat, "revenue": round(float(rev), 2), "units_sold": int(units)}
        for cat, rev, units in rows
    ]
    if zepto_analytics.wants_zepto(marketplaces):
        z = await zepto_analytics.sales_by_category(
            session, tenant_id=tenant_id, start=start, end=end
        )
        cats = _merge_series(cats, z, "category", ("revenue", "units_sold"))
        cats.sort(key=lambda r: r["revenue"], reverse=True)
    return cats


async def get_category_trend(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Per-day revenue/units per category for the stacked-area trend. Returns one
    row per (date, category) that has sales — the frontend pivots categories into
    series and fills gaps. Ordered by date then category for stable rendering."""
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    category = func.coalesce(Sale.category, "Uncategorized")
    rows = (
        await session.execute(
            select(
                Sale.date,
                category,
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds)
            .group_by(Sale.date, category)
            .order_by(Sale.date, category)
        )
    ).all()
    trend = [
        {
            "date": d,
            "category": cat,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for d, cat, rev, units in rows
    ]
    if zepto_analytics.wants_zepto(marketplaces):
        z = await zepto_analytics.category_trend(
            session, tenant_id=tenant_id, start=start, end=end
        )
        trend = _merge_series(trend, z, ("date", "category"), ("revenue", "units_sold"))
    return trend


async def get_city_category(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    limit: int = 15,
) -> list[dict]:
    """City × category revenue matrix for the heatmap. There are hundreds of
    cities, so we scope to the top `limit` cities by revenue in the window and
    return their per-category cells — the frontend renders cities (rows) ×
    categories (columns)."""
    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)

    # Top cities by total revenue in the window (the heatmap's row set).
    top_rows = (
        await session.execute(
            select(Sale.city_id, func.max(Sale.city_name), revenue)
            .where(*conds)
            .group_by(Sale.city_id)
            .order_by(revenue.desc())
            .limit(limit)
        )
    ).all()
    # No Blinkit cities does NOT mean no cells — a Zepto-only client has none
    # here but may have plenty below. Returning early would skip the Zepto
    # branch entirely and leave the heatmap blank for exactly those clients.
    if not top_rows:
        return (
            await zepto_analytics.city_category(
                session, tenant_id=tenant_id, start=start, end=end, limit=limit
            )
            if zepto_analytics.wants_zepto(marketplaces)
            else []
        )
    name_by_id = {cid: (cname or cid) for cid, cname, _ in top_rows}
    top_ids = list(name_by_id)

    category = func.coalesce(Sale.category, "Uncategorized")
    cells = (
        await session.execute(
            select(
                Sale.city_id,
                category,
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
            )
            .where(*conds, Sale.city_id.in_(top_ids))
            .group_by(Sale.city_id, category)
            .order_by(revenue.desc())
        )
    ).all()
    out = [
        {
            "city": name_by_id[cid],
            "category": cat,
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
        }
        for cid, cat, rev, units in cells
    ]

    # Zepto's cells come from `zepto_seller_product_city_daily`, which is scraped
    # one city at a time — no single Zepto response carries city and category
    # together. Appended rather than merged by city name: Zepto reports
    # "BLR - Bengaluru" where Blinkit reports "Bengaluru", and combining them
    # would need a mapping that does not exist yet (see get_sales_by_city).
    if zepto_analytics.wants_zepto(marketplaces):
        out.extend(
            await zepto_analytics.city_category(
                session, tenant_id=tenant_id, start=start, end=end, limit=limit
            )
        )
    return out
