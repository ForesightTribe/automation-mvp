"""Aggregations for the Reports feature — the client's Excel views, computed
server-side. Client-scoped (filtered by `tenant_id`); read-only.

Sales pipeline is Blinkit-only today, so the sales pivot returns one platform
block per marketplace present in `blinkit_seller_sales` (Blinkit in practice).
"""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_marketing import BlinkitAdCampaignDaily
from app.models.blinkit_seller import BlinkitSellerSale
from app.models.search import SearchListing
from app.schemas.reports import (
    CompetitionReport,
    CompGroup,
    CompRow,
    MarketingReport,
    MarketingRow,
    MarketingTotals,
    PivotDay,
    PivotPlatform,
    PivotSku,
    PivotWeek,
    SalesPivot,
)

Sale = BlinkitSellerSale
AdDaily = BlinkitAdCampaignDaily
Listing = SearchListing


def _ratio(num: float, denom: float) -> float | None:
    """A quotient rounded to 2dp, or None when the denominator is 0."""
    return round(num / denom, 2) if denom else None


def _num(value: float | None) -> float | None:
    """Round a nullable number to 2dp, passing None through."""
    return None if value is None else round(float(value), 2)


def _calendar_weeks(start: date, end: date) -> list[tuple[date, date, date]]:
    """Monday-start calendar weeks intersecting [start, end]. Returns
    (week_key, visible_start, visible_end) per week, where `week_key` is the
    week's Monday (its stable identity) and visible_start/end are clamped to the
    selected range so partial edge weeks sum only the days actually shown."""
    weeks: list[tuple[date, date, date]] = []
    cur = start - timedelta(days=start.weekday())  # Monday on/before start
    while cur <= end:
        weeks.append((cur, max(cur, start), min(cur + timedelta(days=6), end)))
        cur += timedelta(days=7)
    return weeks


def _deltas(series: list[float]) -> list[float | None]:
    """Week-over-week growth: element i vs i-1. Index 0 and any zero-prev is None."""
    out: list[float | None] = []
    for i, v in enumerate(series):
        prev = series[i - 1] if i else None
        out.append(round((v - prev) / prev, 4) if prev else None)
    return out


async def get_sales_pivot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    metric: str = "value",
) -> SalesPivot:
    """SKU × day pivot grouped by marketplace, with calendar-week rollups and
    week-over-week deltas. `metric` picks the cell value: revenue (`mrp_value`)
    or units (`qty_sold`)."""
    metric_col = Sale.qty_sold if metric == "units" else Sale.mrp_value

    conds = [Sale.tenant_id == tenant_id, Sale.date >= start, Sale.date <= end]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))

    rows = (
        await session.execute(
            select(
                Sale.platform,
                Sale.item_id,
                func.max(Sale.item_name),
                Sale.date,
                func.coalesce(func.sum(metric_col), 0.0),
            )
            .where(*conds)
            .group_by(Sale.platform, Sale.item_id, Sale.date)
        )
    ).all()

    # ── Column axes ────────────────────────────────────────────────────────
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_index = {d: i for i, d in enumerate(days)}
    weeks = _calendar_weeks(start, end)
    week_of_day: dict[date, int] = {}
    for wi, (_, vis_start, vis_end) in enumerate(weeks):
        d = vis_start
        while d <= vis_end:
            week_of_day[d] = wi
            d += timedelta(days=1)

    # ── Pivot rows into platform → item → {name, cells[], weeks[]} ──────────
    plats: dict[str, dict[str, dict]] = {}
    for platform, item_id, name, d, val in rows:
        sku = plats.setdefault(platform, {}).get(item_id)
        if sku is None:
            sku = {
                "name": name or item_id,
                "cells": [0.0] * len(days),
                "weeks": [0.0] * len(weeks),
            }
            plats[platform][item_id] = sku
        di = day_index.get(d)
        if di is None:
            continue
        v = float(val)
        sku["cells"][di] += v
        wi = week_of_day.get(d)
        if wi is not None:
            sku["weeks"][wi] += v

    # ── Assemble, with the Grand Total row per platform ────────────────────
    platforms_out: list[PivotPlatform] = []
    for platform, items in plats.items():
        sku_list: list[PivotSku] = []
        day_totals = [0.0] * len(days)
        week_totals = [0.0] * len(weeks)
        for item_id, sku in items.items():
            sku_list.append(
                PivotSku(
                    item_id=item_id,
                    name=sku["name"],
                    cells=[round(c, 2) for c in sku["cells"]],
                    total=round(sum(sku["cells"]), 2),
                    weeks=[round(w, 2) for w in sku["weeks"]],
                    week_deltas=_deltas(sku["weeks"]),
                )
            )
            for i, c in enumerate(sku["cells"]):
                day_totals[i] += c
            for i, w in enumerate(sku["weeks"]):
                week_totals[i] += w
        sku_list.sort(key=lambda s: s.total, reverse=True)
        platforms_out.append(
            PivotPlatform(
                platform=platform,
                live=True,  # present in the data ⇒ has a pipeline
                skus=sku_list,
                day_totals=[round(x, 2) for x in day_totals],
                total=round(sum(day_totals), 2),
                week_totals=[round(x, 2) for x in week_totals],
                week_deltas=_deltas(week_totals),
            )
        )
    platforms_out.sort(key=lambda p: p.total, reverse=True)

    return SalesPivot(
        client_id=tenant_id,
        start=start,
        end=end,
        metric="units" if metric == "units" else "value",
        days=[PivotDay(date=d, weekend=d.weekday() >= 4) for d in days],
        weeks=[
            PivotWeek(label=f"Wk {i + 1}", start=vis_start, end=vis_end)
            for i, (_, vis_start, vis_end) in enumerate(weeks)
        ],
        platforms=platforms_out,
    )


async def get_marketing_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> MarketingReport:
    """Daily ad ledger over the selected window: spend / ad-revenue / RoAS /
    organic / total / ROI / impressions, one row per day over a full date spine,
    plus footer totals. RoAS and ROI are recomputed from summed inputs — never
    averaged. Ad metrics come from `blinkit_ad_campaign_daily`; total revenue
    from `blinkit_seller_sales`."""
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
    ad_map = {d: (float(sp), float(sa), int(im)) for d, sp, sa, im in ad_rows}

    sale_rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
            )
            .where(*sale_conds)
            .group_by(Sale.date)
        )
    ).all()
    sale_map = {d: float(rev) for d, rev in sale_rows}

    rows: list[MarketingRow] = []
    tot_spend = tot_ad = tot_organic = tot_total = 0.0
    tot_impr = 0
    day = start
    while day <= end:
        spend, ad_rev, impr = ad_map.get(day, (0.0, 0.0, 0))
        total_rev = sale_map.get(day, 0.0)
        organic = max(0.0, total_rev - ad_rev)
        rows.append(
            MarketingRow(
                date=day,
                spend=round(spend, 2),
                ad_revenue=round(ad_rev, 2),
                roas=_ratio(ad_rev, spend),
                organic_revenue=round(organic, 2),
                total_revenue=round(total_rev, 2),
                roi=_ratio(total_rev, spend),
                impressions=impr,
            )
        )
        tot_spend += spend
        tot_ad += ad_rev
        tot_organic += organic
        tot_total += total_rev
        tot_impr += impr
        day += timedelta(days=1)

    totals = MarketingTotals(
        spend=round(tot_spend, 2),
        ad_revenue=round(tot_ad, 2),
        organic_revenue=round(tot_organic, 2),
        total_revenue=round(tot_total, 2),
        impressions=tot_impr,
        roas=_ratio(tot_ad, tot_spend),
        roi=_ratio(tot_total, tot_spend),
        days=len(rows),
    )

    return MarketingReport(
        client_id=tenant_id, start=start, end=end, rows=rows, totals=totals
    )


async def get_competition_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    kind: str = "main",
) -> CompetitionReport:
    """Own SKU vs competitors, grouped by (marketplace, keyword) — the client's
    price-comparison table. Sourced from `search_listings` (own + competitors
    surface together per search), taking the latest listing per product in the
    window. `sp_per_gram` is None until grammage is captured. `kind` filters
    combos (default `main` = singles on both sides)."""
    lo = datetime.combine(start, datetime.min.time())
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time())
    conds = [
        Listing.tenant_id == tenant_id,
        Listing.scraped_at >= lo,
        Listing.scraped_at < hi,
        Listing.price.is_not(None),
    ]
    if kind == "main":
        conds.append(Listing.is_combo.is_(False))
    elif kind == "combo":
        conds.append(Listing.is_combo.is_(True))
    if marketplaces is not None:
        conds.append(Listing.mp_slug.in_(marketplaces))

    rows = (
        await session.execute(
            select(
                Listing.mp_slug,
                Listing.keyword,
                Listing.brand_slug,
                Listing.product_name,
                Listing.is_brand,
                Listing.price,
                Listing.mrp,
                Listing.grammage,
            )
            .where(*conds)
            .order_by(Listing.scraped_at.desc())  # latest first ⇒ first-wins dedupe
        )
    ).all()

    seen: set[tuple] = set()
    groups: dict[tuple[str, str], dict[str, list[CompRow]]] = {}
    for mp, kw, brand, name, is_brand, price, mrp, grammage in rows:
        dedupe_key = (mp, kw, name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        g = groups.setdefault((mp, kw), {"own": [], "competitors": []})
        row = CompRow(
            name=name,
            brand=brand,
            mrp=_num(mrp),
            sp=_num(price),
            grammage=_num(grammage),
            sp_per_gram=round(price / grammage, 4) if price and grammage else None,
        )
        g["own" if is_brand else "competitors"].append(row)

    out: list[CompGroup] = []
    for (mp, kw), g in groups.items():
        # Cheapest-per-gram first (nulls last), else by selling price.
        g["competitors"].sort(
            key=lambda r: (r.sp_per_gram is None, r.sp_per_gram or r.sp or 0.0)
        )
        out.append(
            CompGroup(marketplace=mp, keyword=kw, own=g["own"], competitors=g["competitors"])
        )
    out.sort(key=lambda x: (x.marketplace, x.keyword))

    return CompetitionReport(
        client_id=tenant_id, start=start, end=end, kind=kind, groups=out
    )
