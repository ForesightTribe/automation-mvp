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
from scraper.utils.pack import per_unit_price
from app.schemas.reports import (
    CompetitionReport,
    CompGroup,
    CompRow,
    MarketingReport,
    MarketingRow,
    MarketingTotals,
    PivotCategory,
    PivotDay,
    PivotPlatform,
    PivotSku,
    PivotSplit,
    PivotWeek,
    SalesPivot,
)

UNCATEGORISED = "Uncategorised"

Sale = BlinkitSellerSale
AdDaily = BlinkitAdCampaignDaily
Listing = SearchListing


def _ratio(num: float, denom: float) -> float | None:
    """A quotient rounded to 2dp, or None when the denominator is 0."""
    return round(num / denom, 2) if denom else None


def _num(value: float | None) -> float | None:
    """Round a nullable number to 2dp, passing None through."""
    return None if value is None else round(float(value), 2)


def _full_weeks(start: date, end: date) -> list[tuple[date, date]]:
    """Complete Monday–Sunday weeks inside [start, end], as (monday, sunday).

    Partial weeks at the edges are **dropped, not clamped**. Clamping made a
    3-day stub sit next to a 7-day week in the same series, so every
    week-over-week delta crossing an edge was a length artefact rather than a
    real move. A window with no whole week returns [] and the weekly view says so.
    """
    weeks: list[tuple[date, date]] = []
    cur = start + timedelta(days=(7 - start.weekday()) % 7)  # first Monday on/after start
    while cur + timedelta(days=6) <= end:
        weeks.append((cur, cur + timedelta(days=6)))
        cur += timedelta(days=7)
    return weeks


def _is_weekend(d: date) -> bool:
    """Fri/Sat/Sun — the client's trading convention, not the calendar's."""
    return d.weekday() >= 4


def _deltas(series: list[float]) -> list[float | None]:
    """Week-over-week growth: element i vs i-1. Index 0 and any zero-prev is None."""
    out: list[float | None] = []
    for i, v in enumerate(series):
        prev = series[i - 1] if i else None
        out.append(round((v - prev) / prev, 4) if prev else None)
    return out


WEEKDAY_DAYS = 4  # Mon–Thu
WEEKEND_DAYS = 3  # Fri–Sun


def _split(sums: list[float], days_per_week: int) -> PivotSplit:
    """Turn one half's weekly *sums* into **average sales per day**, with its
    window average and week-over-week deltas.

    Averaging, not summing, is what makes the two halves comparable at all: a
    Mon–Thu block spans 4 days and a Fri–Sun block 3, so their sums are not like
    quantities. Because `weeks` now holds only whole Mon–Sun weeks, the divisor is
    a constant 4 or 3 — no partial week can distort it.

    `total` is the average day across the whole window (every day weighted
    equally), not the mean of the weekly averages — identical while weeks are
    complete, and the honest definition if that ever changes. Deltas are
    unaffected by the division, since the divisor cancels in a ratio.
    """
    cells = [s / days_per_week for s in sums]
    total = sum(sums) / (days_per_week * len(sums)) if sums else 0.0
    return PivotSplit(
        cells=[round(c, 2) for c in cells],
        total=round(total, 2),
        deltas=_deltas(cells),
    )


def _week_avg(wd: list[float], we: list[float]) -> float:
    """Average sales per day across the whole week — all 7 days of every full week.

    This is a *weighted* mean of the two halves (4 weekdays to 3 weekend days), so
    it deliberately does not equal `weekday.total + weekend.total`, nor their
    midpoint. It is the "an average day looks like this" number.
    """
    return round((sum(wd) + sum(we)) / (7 * len(wd)), 2) if wd else 0.0


async def get_sales_pivot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    metric: str = "value",
) -> SalesPivot:
    """SKU × day pivot grouped by marketplace → category.

    Two column axes come back: the daily one covers the whole selected window,
    while the weekly one covers only **complete Mon–Sun weeks** within it and
    splits each into Mon–Thu and Fri–Sun, compared like-for-like week over week.
    `metric` picks the cell value: revenue (`mrp_value`) or units (`qty_sold`).
    """
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
                Sale.category,
                Sale.date,
                func.coalesce(func.sum(metric_col), 0.0),
            )
            .where(*conds)
            .group_by(Sale.platform, Sale.item_id, Sale.category, Sale.date)
        )
    ).all()

    # ── Column axes ────────────────────────────────────────────────────────
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_index = {d: i for i, d in enumerate(days)}
    # Weekly axis covers only whole Mon–Sun weeks, so days in a partial edge week
    # are absent from `week_of_day` and contribute to the daily view alone.
    weeks = _full_weeks(start, end)
    week_of_day: dict[date, int] = {}
    for wi, (mon, sun) in enumerate(weeks):
        d = mon
        while d <= sun:
            week_of_day[d] = wi
            d += timedelta(days=1)

    # ── Pivot rows into platform → item → {name, cells[], weeks[], cats{}} ──
    # A SKU is bucketed under one category, but `category` is stamped per sales
    # row, so an item whose category was re-tagged mid-window would otherwise
    # split into two rows. `cats` tallies the metric per category so the item
    # lands in whichever one it mostly sold under, with its full total intact.
    plats: dict[str, dict[str, dict]] = {}
    for platform, item_id, name, category, d, val in rows:
        sku = plats.setdefault(platform, {}).get(item_id)
        if sku is None:
            sku = {
                "name": name or item_id,
                "cells": [0.0] * len(days),
                "wd": [0.0] * len(weeks),   # Mon–Thu of each full week
                "we": [0.0] * len(weeks),   # Fri–Sun of each full week
                "cats": {},
            }
            plats[platform][item_id] = sku
        di = day_index.get(d)
        if di is None:
            continue
        v = float(val)
        sku["cells"][di] += v
        wi = week_of_day.get(d)
        if wi is not None:
            sku["we" if _is_weekend(d) else "wd"][wi] += v
        cat = (category or "").strip() or UNCATEGORISED
        sku["cats"][cat] = sku["cats"].get(cat, 0.0) + v

    # ── Assemble: category groups + subtotals, then the platform Grand Total ─
    platforms_out: list[PivotPlatform] = []
    for platform, items in plats.items():
        # category → {skus[], day_totals[], wd[], we[]}
        cats: dict[str, dict] = {}
        day_totals = [0.0] * len(days)
        wd_totals = [0.0] * len(weeks)
        we_totals = [0.0] * len(weeks)
        for item_id, sku in items.items():
            row = PivotSku(
                item_id=item_id,
                name=sku["name"],
                cells=[round(c, 2) for c in sku["cells"]],
                total=round(sum(sku["cells"]), 2),
                weekday=_split(sku["wd"], WEEKDAY_DAYS),
                weekend=_split(sku["we"], WEEKEND_DAYS),
                week_total=_week_avg(sku["wd"], sku["we"]),
            )
            cat_name = (
                max(sku["cats"].items(), key=lambda kv: kv[1])[0]
                if sku["cats"]
                else UNCATEGORISED
            )
            cat = cats.setdefault(
                cat_name,
                {
                    "skus": [],
                    "day_totals": [0.0] * len(days),
                    "wd": [0.0] * len(weeks),
                    "we": [0.0] * len(weeks),
                },
            )
            cat["skus"].append(row)
            for i, c in enumerate(sku["cells"]):
                cat["day_totals"][i] += c
                day_totals[i] += c
            for i in range(len(weeks)):
                cat["wd"][i] += sku["wd"][i]
                cat["we"][i] += sku["we"][i]
                wd_totals[i] += sku["wd"][i]
                we_totals[i] += sku["we"][i]

        cats_out: list[PivotCategory] = []
        for name, cat in cats.items():
            cat["skus"].sort(key=lambda s: s.total, reverse=True)
            cats_out.append(
                PivotCategory(
                    name=name,
                    skus=cat["skus"],
                    cells=[round(x, 2) for x in cat["day_totals"]],
                    total=round(sum(cat["day_totals"]), 2),
                    weekday=_split(cat["wd"], WEEKDAY_DAYS),
                    weekend=_split(cat["we"], WEEKEND_DAYS),
                    week_total=_week_avg(cat["wd"], cat["we"]),
                )
            )
        cats_out.sort(key=lambda c: c.total, reverse=True)

        platforms_out.append(
            PivotPlatform(
                platform=platform,
                live=True,  # present in the data ⇒ has a pipeline
                categories=cats_out,
                cells=[round(x, 2) for x in day_totals],
                total=round(sum(day_totals), 2),
                weekday=_split(wd_totals, WEEKDAY_DAYS),
                weekend=_split(we_totals, WEEKEND_DAYS),
                week_total=_week_avg(wd_totals, we_totals),
            )
        )
    platforms_out.sort(key=lambda p: p.total, reverse=True)

    return SalesPivot(
        client_id=tenant_id,
        start=start,
        end=end,
        metric="units" if metric == "units" else "value",
        days=[PivotDay(date=d, weekend=_is_weekend(d)) for d in days],
        weeks=[
            PivotWeek(label=f"Wk {i + 1}", start=mon, end=sun)
            for i, (mon, sun) in enumerate(weeks)
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
    window. `unit_price` normalizes price to the pack's UOM basis (₹/100 ml, ₹/100 g,
    ₹/piece) so different pack sizes compare fairly. `kind` filters combos (default
    `main` = singles on both sides)."""
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
                Listing.pack_size,
                Listing.pack_uom,
                Listing.pack_count,
            )
            .where(*conds)
            # Latest listing per (marketplace, keyword, product) — done in SQL, not by
            # fetching everything and dropping duplicates in Python. That earlier shape
            # pulled ~100k rows to build ~124: 99.9% waste, slow enough that the pooler
            # dropped the connection mid-transfer and the page never loaded.
            .distinct(Listing.mp_slug, Listing.keyword, Listing.product_name)
            .order_by(
                Listing.mp_slug,
                Listing.keyword,
                Listing.product_name,
                Listing.scraped_at.desc(),   # ⇒ DISTINCT ON keeps the newest
            )
        )
    ).all()

    groups: dict[tuple[str, str], dict[str, list[CompRow]]] = {}
    for mp, kw, brand, name, is_brand, price, mrp, pack_size, pack_uom, pack_count in rows:
        g = groups.setdefault((mp, kw), {"own": [], "competitors": []})
        row = CompRow(
            name=name,
            brand=brand,
            mrp=_num(mrp),
            sp=_num(price),
            pack_size=_num(pack_size),
            pack_uom=pack_uom or "",
            pack_count=pack_count,
            unit_price=per_unit_price(price, pack_size, pack_uom or ""),
        )
        g["own" if is_brand else "competitors"].append(row)

    out: list[CompGroup] = []
    for (mp, kw), g in groups.items():
        # Cheapest-per-unit first (nulls last), else by selling price. Within one
        # (marketplace, keyword) the packs share a UOM, so per-unit sorts cleanly.
        g["competitors"].sort(
            key=lambda r: (r.unit_price is None, r.unit_price or r.sp or 0.0)
        )
        out.append(
            CompGroup(marketplace=mp, keyword=kw, own=g["own"], competitors=g["competitors"])
        )
    out.sort(key=lambda x: (x.marketplace, x.keyword))

    return CompetitionReport(
        client_id=tenant_id, start=start, end=end, kind=kind, groups=out
    )
