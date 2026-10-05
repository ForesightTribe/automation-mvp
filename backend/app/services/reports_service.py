"""Aggregations for the Reports feature — the client's Excel views, computed
server-side. Client-scoped (filtered by `tenant_id`); read-only.

The sales pivot returns one platform block per marketplace with sales in the
window. Blinkit comes from `blinkit_seller_sales` (old partnersbiz domain) or
`blinkit_seller_hub_sales_order_ro` (new seller-hub domain, e.g. Sereko) —
both under the "blinkit" block, since a tenant only ever has one of them.
"""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blinkit_marketing import BlinkitAdCampaign, BlinkitAdCampaignDaily
from app.models.blinkit_seller import BlinkitSellerSale
from app.models.search import SearchListing
from app.services import blinkit_seller_hub_analytics, instamart_reports, zepto_ads, zepto_reports
from scraper.utils.pack import per_unit_price
from app.schemas.reports import (
    CampaignHalf,
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
    AdTypeSection,
    BannerRow,
    SalesPivot,
    WeekendBlock,
    WeekendCampaign,
    WeekendPlanning,
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

    # Zepto rows arrive in the same tuple shape, so everything below — the week
    # axis, category grouping, subtotals, the weekday/weekend split — runs over
    # both marketplaces without knowing which produced a row. `platform` keeps
    # them in separate top-level blocks.
    # Seller-hub Blinkit accounts (Sereko) land in the same "blinkit" block —
    # a tenant is on one Blinkit domain or the other, never both.
    if blinkit_seller_hub_analytics.wants_blinkit_seller_hub(marketplaces):
        rows = [
            *rows,
            *await blinkit_seller_hub_analytics.pivot_rows(
                session, tenant_id=tenant_id, start=start, end=end, metric=metric
            ),
        ]
    if zepto_reports.wants_zepto(marketplaces):
        rows = [
            *rows,
            *await zepto_reports.pivot_rows(
                session, tenant_id=tenant_id, start=start, end=end, metric=metric
            ),
        ]
    if instamart_reports.wants_instamart(marketplaces):
        rows = [
            *rows,
            *await instamart_reports.pivot_rows(
                session, tenant_id=tenant_id, start=start, end=end, metric=metric
            ),
        ]

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

    if zepto_reports.wants_zepto(marketplaces):
        # Add into the Blinkit figures rather than replacing them: with both
        # marketplaces selected a day carries the spend of both.
        for d, (sp, sa, im) in (
            await zepto_ads.trend_series(
                session, tenant_id=tenant_id, start=start, end=end
            )
        ).items():
            b_sp, b_sa, b_im = ad_map.get(d, (0.0, 0.0, 0))
            ad_map[d] = (b_sp + sp, b_sa + sa, b_im + im)
    if instamart_reports.wants_instamart(marketplaces):
        for d, (sp, sa, im) in (
            await instamart_reports.ad_daily(
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
            )
            .where(*sale_conds)
            .group_by(Sale.date)
        )
    ).all()
    sale_map = {d: float(rev) for d, rev in sale_rows}

    if blinkit_seller_hub_analytics.wants_blinkit_seller_hub(marketplaces):
        for d, rev in (
            await blinkit_seller_hub_analytics.sales_daily(
                session, tenant_id=tenant_id, start=start, end=end
            )
        ).items():
            sale_map[d] = sale_map.get(d, 0.0) + rev
    if zepto_reports.wants_zepto(marketplaces):
        for d, rev in (
            await zepto_reports.sales_daily(
                session, tenant_id=tenant_id, start=start, end=end
            )
        ).items():
            sale_map[d] = sale_map.get(d, 0.0) + rev
    if instamart_reports.wants_instamart(marketplaces):
        for d, rev in (
            await instamart_reports.sales_daily(
                session, tenant_id=tenant_id, start=start, end=end
            )
        ).items():
            sale_map[d] = sale_map.get(d, 0.0) + rev

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


# ── Weekend planning ───────────────────────────────────────────────────────

# Each platform's own campaign-type enum, in the words the client's sheet
# uses. Blinkit's and Zepto's; Instamart has no type axis (always None, which
# falls through to the "Other Ads" default below).
AD_TYPE_LABELS = {
    "PRODUCT_LISTING": "Keyword Ads",
    "PRODUCT_RECOMMENDATION": "Recommendation Ads",
    "BANNER_LISTING": "Banner Listing Ads",
    "BANNER_DIY": "Banner Ads",
    "SHELF_DIY": "Shelf Ads",
    "SEARCH_SUGGESTION": "Search Suggestion Ads",
    "PLA": "PLA Ads",
    "Display": "Display Ads",
}

# Banner placements carry no revenue attribution, so they are reported on cost
# per impression instead and live on their own sheet.
BANNER_TYPES = {"BANNER_LISTING", "BANNER_DIY"}


def _weekend_blocks(start: date, end: date) -> list[WeekendBlock]:
    """Every Fri–Sun weekend that OVERLAPS the window, labelled by its Friday.

    Overlap, not containment: a window ending on a Saturday still contains two
    thirds of that weekend, and dropping it would silently lose the most recent
    days — the ones anyone opening this report is looking for. The block is
    clamped to the window so its numbers only ever cover days that were asked
    for.
    """
    blocks: list[WeekendBlock] = []
    cur = start - timedelta(days=(start.weekday() - 4) % 7)   # the Friday on or before
    while cur <= end:
        fri, sun = cur, cur + timedelta(days=2)
        if sun >= start:
            lo, hi = max(fri, start), min(sun, end)
            n = len(blocks) + 1
            blocks.append(
                WeekendBlock(
                    label=f"Weekend {n} ({fri:%d %b})",
                    index=n,
                    start=lo,
                    end=hi,
                    days=(hi - lo).days + 1,
                )
            )
        cur += timedelta(days=7)
    return blocks


def _half(spend: float, revenue: float, impressions: int) -> CampaignHalf:
    return CampaignHalf(
        spend=round(spend, 2),
        revenue=round(revenue, 2),
        roas=round(revenue / spend, 4) if spend else None,
        impressions=impressions,
    )


async def get_weekend_planning(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> WeekendPlanning:
    """Spend, revenue and RoAS per campaign, one column group per weekend.

    The client's own planning sheet: weekends side by side so the effect of a
    push on one is visible against the others, with the weekdays alongside as the
    baseline it is being judged against.

    Fri–Sun is the client's definition of a weekend and is the same one the sales
    pivot uses, so the two reports cannot disagree about which days those are.
    """
    conds = [
        BlinkitAdCampaignDaily.tenant_id == tenant_id,
        BlinkitAdCampaignDaily.date >= start,
        BlinkitAdCampaignDaily.date <= end,
    ]
    if marketplaces:
        conds.append(BlinkitAdCampaignDaily.platform.in_(marketplaces))

    rows = (
        await session.execute(
            select(
                BlinkitAdCampaignDaily.campaign_id,
                BlinkitAdCampaignDaily.campaign_type,
                BlinkitAdCampaignDaily.date,
                func.sum(BlinkitAdCampaignDaily.budget_consumed),
                func.sum(BlinkitAdCampaignDaily.ad_sales),
                func.sum(BlinkitAdCampaignDaily.impressions),
            )
            .where(*conds)
            .group_by(
                BlinkitAdCampaignDaily.campaign_id,
                BlinkitAdCampaignDaily.campaign_type,
                BlinkitAdCampaignDaily.date,
            )
        )
    ).all()

    names = dict(
        (
            await session.execute(
                select(BlinkitAdCampaign.campaign_id, BlinkitAdCampaign.name).where(
                    BlinkitAdCampaign.tenant_id == tenant_id
                )
            )
        ).all()
    )

    # Instamart: same shape, appended into the same `rows`/`names` the loop
    # below already consumes generically — campaign_id is a UUID string here
    # (Blinkit's is an int), so the two never collide as dict keys. Sourced
    # from `instamart_ad_product_daily` alone (not also keyword_daily): the
    # two are different VIEWS of the same spend, and summing both would
    # double it — see instamart_ads.py's own campaign-breakdown docstring.
    # `campaign_type` is always None here (Instamart's ad-type breakdown was
    # removed upstream as unreliable), so every Instamart campaign lands in
    # one flat section rather than Blinkit's "Keyword Ads"/"Banner Ads" split.
    if instamart_reports.wants_instamart(marketplaces):
        im_rows = await instamart_reports.weekend_rows(
            session, tenant_id=tenant_id, start=start, end=end
        )
        rows = [*rows, *im_rows]
        names.update(
            await instamart_reports.campaign_names(session, tenant_id=tenant_id)
        )

    # Zepto: same shape again. campaign_id arrives pre-prefixed "zepto:<id>"
    # (see zepto_reports.weekend_rows) since Zepto's ids, like Blinkit's, are
    # plain platform-assigned ints that could coincidentally collide for a
    # different client — the accumulator below keys purely on campaign_id, so
    # an unprefixed collision would silently merge two campaigns' spend.
    # campaign_type IS a real axis here (PLA | Display — see
    # ZeptoAdCampaignDaily's docstring), unlike Instamart's, so Zepto
    # campaigns split into their own sections below same as Blinkit's do.
    if zepto_reports.wants_zepto(marketplaces):
        zp_rows = await zepto_reports.weekend_rows(
            session, tenant_id=tenant_id, start=start, end=end
        )
        rows = [*rows, *zp_rows]
        names.update(
            await zepto_reports.campaign_names(session, tenant_id=tenant_id)
        )

    blocks = _weekend_blocks(start, end)
    index = {}
    for i, b in enumerate(blocks):
        d = b.start
        while d <= b.end:
            index[d] = i
            d += timedelta(days=1)

    # campaign → {"w": [ [spend, rev, impr] per weekend ], "d": [...] }
    acc: dict[int, dict] = {}
    for cid, ctype, day, spend, revenue, impressions in rows:
        slot = acc.setdefault(
            cid,
            {
                "type": ctype,
                "w": [[0.0, 0.0, 0] for _ in blocks],
                "d": [0.0, 0.0, 0],
            },
        )
        target = slot["w"][index[day]] if day in index else slot["d"]
        target[0] += float(spend or 0)
        target[1] += float(revenue or 0)
        target[2] += int(impressions or 0)

    def _campaign(cid: int | str, slot: dict, name: str) -> WeekendCampaign:
        weekends = [_half(*w) for w in slot["w"]]
        weekday = _half(*slot["d"])
        weekend_total = _half(
            sum(w[0] for w in slot["w"]),
            sum(w[1] for w in slot["w"]),
            sum(w[2] for w in slot["w"]),
        )
        # The ceiling this campaign has actually reached: the busiest weekend's
        # spend divided by the days of that weekend inside the window, so a
        # weekend clipped by the date picker is not scored as if it were short.
        max_daily = max(
            (w[0] / b.days for w, b in zip(slot["w"], blocks, strict=True) if b.days),
            default=0.0,
        )
        return WeekendCampaign(
            campaign_id=cid,
            name=name,
            ad_type=slot["type"],
            weekends=weekends,
            weekend_total=weekend_total,
            weekday=weekday,
            total=_half(
                weekend_total.spend + weekday.spend,
                weekend_total.revenue + weekday.revenue,
                weekend_total.impressions + weekday.impressions,
            ),
            max_daily_spend=round(max_daily, 2),
        )

    def _roll(rows: list[WeekendCampaign], cid: int, name: str, ad_type) -> WeekendCampaign:
        """A subtotal row, in the same shape as a campaign row so one renderer
        draws both. Ratios come from the summed inputs, never from averaging the
        rows' own ratios."""
        return WeekendCampaign(
            campaign_id=cid,
            name=name,
            ad_type=ad_type,
            weekends=[
                _half(
                    sum(r.weekends[i].spend for r in rows),
                    sum(r.weekends[i].revenue for r in rows),
                    sum(r.weekends[i].impressions for r in rows),
                )
                for i in range(len(blocks))
            ],
            weekend_total=_half(
                sum(r.weekend_total.spend for r in rows),
                sum(r.weekend_total.revenue for r in rows),
                sum(r.weekend_total.impressions for r in rows),
            ),
            weekday=_half(
                sum(r.weekday.spend for r in rows),
                sum(r.weekday.revenue for r in rows),
                sum(r.weekday.impressions for r in rows),
            ),
            total=_half(
                sum(r.total.spend for r in rows),
                sum(r.total.revenue for r in rows),
                sum(r.total.impressions for r in rows),
            ),
            # A subtotal's ceiling is the sum of its campaigns' ceilings: what the
            # block could spend in a day if every campaign hit its own best weekend.
            max_daily_spend=round(sum(r.max_daily_spend for r in rows), 2),
        )

    everyone = [
        _campaign(cid, slot, names.get(cid) or f"Campaign {cid}") for cid, slot in acc.items()
    ]
    everyone.sort(key=lambda c: -c.total.spend)

    # Banner campaigns are pulled out: with no revenue they would sit in the
    # planning table as permanent zero-RoAS rows and drag every subtotal.
    banner_rows = [c for c in everyone if (c.ad_type or "") in BANNER_TYPES]
    planning = [c for c in everyone if (c.ad_type or "") not in BANNER_TYPES]

    sections: list[AdTypeSection] = []
    for ad_type in dict.fromkeys(c.ad_type for c in planning):
        rows_of = [c for c in planning if c.ad_type == ad_type]
        sections.append(
            AdTypeSection(
                ad_type=ad_type or "OTHER",
                label=AD_TYPE_LABELS.get(ad_type or "", ad_type or "Other Ads"),
                campaigns=rows_of,
                subtotal=_roll(rows_of, 0, f"{AD_TYPE_LABELS.get(ad_type or '', 'Other')} Total", ad_type),
            )
        )

    banners = [
        BannerRow(
            campaign_id=c.campaign_id,
            name=c.name,
            spend=c.total.spend,
            impressions=c.total.impressions,
            spend_per_impression=(
                round(c.total.spend / c.total.impressions * 1000, 2)
                if c.total.impressions
                else None
            ),
        )
        for c in sorted(banner_rows, key=lambda c: -c.total.spend)
    ]

    totals = _roll(planning, 0, "Grand Total", None)

    return WeekendPlanning(
        client_id=tenant_id,
        start=start,
        end=end,
        weekends=blocks,
        sections=sections,
        totals=totals,
        banners=banners,
    )


async def get_raw_ad_rows(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    campaign_type: str,
) -> list[dict]:
    """The platform's own per-day export rows for one campaign type.

    Straight columns off `blinkit_ad_campaign_detail`, which is already at the
    grain the export uses: one row per date, campaign and targeting value. No
    aggregation, so these sheets are the raw material the pivots above are built
    from and can be checked against them.
    """
    from app.models.blinkit_marketing import BlinkitAdCampaignDetail

    rows = (
        await session.execute(
            select(BlinkitAdCampaignDetail, BlinkitAdCampaign.name, BlinkitAdCampaign.pacing_type)
            .join(
                BlinkitAdCampaign,
                (BlinkitAdCampaign.campaign_id == BlinkitAdCampaignDetail.campaign_id)
                & (BlinkitAdCampaign.tenant_id == BlinkitAdCampaignDetail.tenant_id),
                isouter=True,
            )
            .where(
                BlinkitAdCampaignDetail.tenant_id == tenant_id,
                BlinkitAdCampaignDetail.snapshot_date >= start,
                BlinkitAdCampaignDetail.snapshot_date <= end,
                BlinkitAdCampaignDetail.campaign_type == campaign_type,
            )
            .order_by(
                BlinkitAdCampaignDetail.snapshot_date,
                BlinkitAdCampaignDetail.campaign_id,
            )
        )
    ).all()

    return [
        {
            "date": d.snapshot_date,
            "campaign_id": d.campaign_id,
            "campaign_name": name or f"Campaign {d.campaign_id}",
            "targeting_type": "Keyword" if d.target_type == "keyword" else "Recommendation",
            "targeting_value": d.target,
            "match_type": d.match_type,
            "most_viewed_position": d.most_viewed_position,
            "pacing_type": pacing,
            "cpm": d.cpm,
            "impressions": d.impressions,
            "direct_atc": d.direct_atc,
            "indirect_atc": d.indirect_atc,
            "direct_quantities_sold": d.direct_quantities_sold,
            "indirect_quantities_sold": d.indirect_quantities_sold,
            "direct_sales": d.direct_sales,
            "indirect_sales": d.indirect_sales,
            "new_users_acquired": d.new_users_acquired,
            "budget_consumed": d.budget_consumed,
            "direct_roas": d.direct_roas,
            "total_roas": d.total_roas,
        }
        for d, name, pacing in rows
    ]
