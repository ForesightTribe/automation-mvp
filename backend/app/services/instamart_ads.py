"""Instamart ad data for the Insights page.

Three tables, three different shapes:

* `instamart_ad_campaigns` (`campaigns()` below) — one row per campaign,
  LIFETIME totals, replaced whole on every scrape. `/api/v1/campaigns` gives
  no real window: verified live that a date filter changes GMV/impressions
  there but NOT spend (always lifetime regardless). Only used for what IS
  genuinely lifetime or unwindowable — campaign identity (name, status,
  type, daily_budget) and (start_time, end_time), which decide WHICH
  campaigns a window's list includes. Its own spend/gmv/impressions fields
  are NOT used for a windowed row — see `instamart_ad_product_daily` below.

* `instamart_ad_account_daily` (`summary_agg()`, `performance()` below) — one
  row per DAY, account-wide (not per-campaign), from
  `/api/v1/advertiser/metrics/batch` with `dimensions: ["DIMENSION_TYPE_DAY"]`.
  This one genuinely respects a date window: verified live that summing 8
  days here matched the portal's own windowed dashboard exactly on GMV,
  impressions AND spend. This is the source for anything that needs a real
  period-over-period comparison — the KPI strip's growth and the daily trend
  chart.

* `instamart_ad_product_daily` / `instamart_ad_keyword_daily` (asset_metrics.py)
  — one row per day PER CAMPAIGN per product/keyword, genuinely windowed and
  campaign-attributed (verified live, row by row, against the account's own
  downloaded CSV report — matched to the paisa across 8 days). `campaigns()`
  below sums the product table by campaign_id for a real windowed per-campaign
  spend/sales/impressions/atc, instead of the lifetime figures
  `instamart_ad_campaigns` carries.
"""
import uuid
from datetime import date, datetime, time

from sqlalchemy import func, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instamart_ads import InstamartAdAccountDaily as Daily
from app.models.instamart_ads import InstamartAdCampaign as Ad


def wants_instamart(marketplaces: list[str] | None) -> bool:
    return marketplaces is None or "instamart" in marketplaces


# The Insights page's status filter is a hardcoded 5-item list (ACTIVE, STOPPED,
# ON_HOLD, COMPLETED, DRAFT) built against Blinkit/Zepto's own status words —
# Instamart's raw values (CAMPAIGN_STATUS_LIVE, CAMPAIGN_STATUS_PAUSED, ...)
# never match any of them literally, so an unmapped status silently drops every
# Instamart campaign the moment someone picks a filter. Mapped onto the SAME
# words Blinkit/Zepto already use, the existing filter and status badge just
# work — no frontend change needed. EXHAUSTED -> ON_HOLD follows the badge's
# own documented reasoning (its ON_HOLD case IS "delivery paused because the
# day's budget ran out", which is exactly what Instamart's EXHAUSTED means).
# Only LIVE/PAUSED/STOPPED have been observed on the real account; the rest
# come from the portal's own status-filter enum, mapped defensively so a
# campaign that reaches one of them still shows a sensible badge instead of
# a raw enum string.
_STATUS_MAP = {
    "CAMPAIGN_STATUS_LIVE": "ACTIVE",
    "CAMPAIGN_STATUS_ACTIVE": "ACTIVE",
    "CAMPAIGN_STATUS_PAUSED": "PAUSED",
    "CAMPAIGN_STATUS_STOPPED": "STOPPED",
    "CAMPAIGN_STATUS_EXHAUSTED": "ON_HOLD",
    "CAMPAIGN_STATUS_EXPIRED": "COMPLETED",
    "CAMPAIGN_STATUS_UPCOMING": "SCHEDULED",
    "CAMPAIGN_STATUS_IN_REVIEW": "UNDER_REVIEW",
    "CAMPAIGN_STATUS_REJECTED": "REJECTED",
}


def _status_label(raw: str | None) -> str | None:
    return _STATUS_MAP.get(raw or "", raw)


def _type_label(raw: str | None) -> str | None:
    """Strips Instamart's redundant "CAMPAIGN_TYPE_" prefix so the (data-derived)
    type filter reads "Item"/"Banner" like Blinkit's "PRODUCT_LISTING" reads
    "Product Listing", not the doubled-up "Campaign Type Item"."""
    return (raw or "").removeprefix("CAMPAIGN_TYPE_") or raw


def _daily_conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Daily.tenant_id == tenant_id, Daily.date >= start, Daily.date <= end]


async def summary_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple:
    """(spend, impressions, gmv, atc, units, active campaigns) over the window
    — a REAL window now, from the daily table. Tuple shape matches
    `ads_service._summary_agg` so the two marketplaces add.

    units is 0: Instamart's ad data never reports a unit count anywhere
    (checked both this endpoint and the campaigns list) — 0 is "not
    reported", not "measured zero". atc IS real here (METRIC_TYPE_
    ADD_TO_CART_COUNT, requested since 2026-09-24).

    ⚠️ Tried substituting `conversions` (a purchase-completion COUNT, not a
    unit quantity — one order can hold more than one unit) here on
    2026-09-25, same pattern `zepto_ads.py` already uses in places. Reverted
    same day at the user's request: a plausible-looking but silently wrong
    number (undercounts whenever a customer buys >1 unit per order) is worse
    than an honest 0, especially once it feeds AOV or cross-marketplace
    comparisons. Left un-fixed on purpose — if this is revisited, verify
    what `conversions` actually counts against a real ground-truth source
    first (the PO export's CSV cross-check earlier this session is the
    pattern to follow), not just infer it from the metric's name.

    "Active campaigns" = distinct campaigns with any product/keyword-daily
    row in the window — matching Blinkit's and Zepto's "had activity in the
    window" definition (ads_service._summary_agg, zepto_ads.summary_agg),
    the one the KPI tile's own tooltip states ("delivered at least once in
    this window"). This used to instead count `status == CAMPAIGN_STATUS_LIVE`
    (running right now, regardless of the selected window) — wrong on two
    counts: it doesn't match what the tile claims to show, and being window-
    INDEPENDENT it added the same number to every window's total (including
    the previous-period comparison), diluting the delta badge. Verified live
    2026-09-25: every live campaign, BANNER included, has a
    instamart_ad_product_daily row for a day it ran, so counting from there
    doesn't silently drop a campaign type that only has keyword/product
    dimensioning in principle but not in practice.
    """
    from app.models.instamart_ads import InstamartAdKeywordDaily as KD
    from app.models.instamart_ads import InstamartAdProductDaily as PD

    spend, impr, gmv, atc = (
        await session.execute(
            select(
                func.coalesce(func.sum(Daily.spend), 0.0),
                func.coalesce(func.sum(Daily.impressions), 0),
                func.coalesce(func.sum(Daily.gmv), 0.0),
                func.coalesce(func.sum(Daily.add_to_cart_count), 0),
            ).where(*_daily_conds(tenant_id, start, end))
        )
    ).one()
    # Campaigns with a product OR keyword row in the window, counted in ONE query (a UNION
    # dedupes across the two tables) rather than one round trip per table (2026-10-08).
    ids = union(*(
        select(model.campaign_id).where(
            model.tenant_id == tenant_id,
            model.date >= start,
            model.date <= end,
            model.campaign_id.is_not(None),
        )
        for model in (PD, KD)
    )).subquery()
    active = (
        await session.execute(select(func.count()).select_from(ids))
    ).scalar_one()
    return (float(spend), int(impr), float(gmv), int(atc), 0, int(active))


async def ads_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, float]:
    """(spend, impressions, gmv) — the additive bases only.

    Pairs with analytics_service._ads_agg, the shared backbone behind the
    Overview marketplace cards, the Analytics page's ad metrics and the Ads
    page's per-marketplace breakdown. Those three read Blinkit's daily table
    directly, so without this they report Instamart as zero spend/ROAS while
    the Ads Insights tiles (which go through summary_agg) show the real
    figure — the exact gap `zepto_ads.ads_agg` was added to close for Zepto.

    Deliberately not `summary_agg()[:3]`: that also queries the active
    campaign count, which none of these callers use.
    """
    spend, impr, gmv = (
        await session.execute(
            select(
                func.coalesce(func.sum(Daily.spend), 0.0),
                func.coalesce(func.sum(Daily.impressions), 0),
                func.coalesce(func.sum(Daily.gmv), 0.0),
            ).where(*_daily_conds(tenant_id, start, end))
        )
    ).one()
    return (float(spend), int(impr), float(gmv))


async def performance(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Daily account totals — same shape as `ads_service.get_performance`."""
    rows = (
        await session.execute(
            select(Daily.date, Daily.spend, Daily.impressions, Daily.gmv)
            .where(*_daily_conds(tenant_id, start, end))
            .order_by(Daily.date)
        )
    ).all()
    return [
        {
            "date": d,
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "ad_sales": round(float(s), 2),
            "roas": round(float(s) / float(b), 4) if b else None,
        }
        for d, b, i, s in rows
    ]


async def campaigns(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Campaigns ACTIVE at some point in [start, end], shaped like
    `zepto_ads.campaigns()` so `ads_service.get_campaigns` can append them the
    same way.

    WHICH campaigns are listed is windowed by (start_time, end_time) overlap
    -- matching how the portal's own date picker narrows "All Campaigns" to a
    handful for a given week, not the account's full lifetime list.

    Each row's spend/sales/impressions/atc are ALSO windowed now -- summed
    from `instamart_ad_product_daily` (grouped by campaign_id) over exactly
    [start, end], not the lifetime totals `instamart_ad_campaigns` carries.
    That table's own date filter was verified to change GMV/impressions but
    leave spend always lifetime-cumulative (see module docstring), which is
    why a campaign like "Bread KW" could show real windowed spend elsewhere
    on the page (Ad asset performance) but ₹0 here -- both numbers were
    genuinely lifetime, just for different fields. product_daily has none of
    that inconsistency: every field there is a real per-day sum, verified
    live against the account's own downloaded CSV report to the paisa (see
    asset_metrics.py). A campaign with no product_daily rows in this window
    (nothing scraped yet, or genuinely no activity) shows zeros, same as any
    other marketplace's windowed campaign row would.

    Keyword rows are NOT also summed in here — product and keyword daily are
    two views of the SAME spend (see InstamartAssetPerformanceCard's
    docstring); adding both would double it.
    """
    from app.models.instamart_ads import InstamartAdProductDaily as PD

    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)
    rows = (
        await session.execute(
            select(Ad).where(
                Ad.tenant_id == tenant_id,
                Ad.start_time <= window_end,
                or_(Ad.end_time.is_(None), Ad.end_time >= window_start),
            )
        )
    ).scalars().all()

    metrics = {
        cid: {"spend": float(spend), "gmv": float(gmv), "impressions": int(impr), "atc": int(atc)}
        for cid, spend, gmv, impr, atc in (
            await session.execute(
                select(
                    PD.campaign_id,
                    func.coalesce(func.sum(PD.spend), 0.0),
                    func.coalesce(func.sum(PD.gmv), 0.0),
                    func.coalesce(func.sum(PD.impressions), 0),
                    func.coalesce(func.sum(PD.add_to_cart_count), 0),
                )
                .where(
                    PD.tenant_id == tenant_id, PD.date >= start, PD.date <= end,
                    PD.campaign_id.is_not(None),
                )
                .group_by(PD.campaign_id)
            )
        ).all()
    }
    zero = {"spend": 0.0, "gmv": 0.0, "impressions": 0, "atc": 0}

    return [
        {
            "campaign_id": r.campaign_id,
            "name": r.name,
            "spend": round(metrics.get(r.campaign_id, zero)["spend"], 2),
            "impressions": metrics.get(r.campaign_id, zero)["impressions"],
            "sales": round(metrics.get(r.campaign_id, zero)["gmv"], 2),
            "atc": metrics.get(r.campaign_id, zero)["atc"],
            # Instamart's campaign list reports orders/GMV, never a unit count —
            # 0 here is "not reported", matching how the rest of this app
            # defaults an absent metric rather than substituting a different one.
            "units_sold": 0,
            # Recomputed from the windowed sums (gmv / spend), not Instamart's
            # own METRIC_TYPE_ROI, whose definition isn't confirmed to match —
            # comparability across marketplaces matters more here than any
            # one platform's own ratio.
            "roas": (
                round(metrics[r.campaign_id]["gmv"] / metrics[r.campaign_id]["spend"], 4)
                if metrics.get(r.campaign_id, zero)["spend"] else None
            ),
            "status": _status_label(r.status),
            "campaign_type": _type_label(r.campaign_type),
            "daily_budget": int(r.daily_budget) if r.daily_budget is not None else None,
        }
        for r in rows
    ]


async def campaigns_daily(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """`campaigns()` at campaign x DAY grain, shaped like `zepto_ads.campaigns_daily` so
    `ads_service.get_campaigns_daily` can append these rows the same way — this is what
    feeds the Insights page's budget-utilisation column, which had no Instamart rows at
    all until this was added (that endpoint never called into this module).

    Summed from `instamart_ad_product_daily`, same real per-day, per-campaign source
    `campaigns()` uses above (see module docstring) — not `instamart_ad_campaigns`,
    whose own spend is lifetime-cumulative regardless of date filter. `daily_budget`
    comes from the catalogue (`instamart_ad_campaigns`), a current snapshot rather than
    history, same limitation every other marketplace's budget-utilisation figure has.
    """
    from app.models.instamart_ads import InstamartAdProductDaily as PD

    rows = (
        await session.execute(
            select(
                PD.date,
                PD.campaign_id,
                func.coalesce(func.sum(PD.spend), 0.0),
                func.coalesce(func.sum(PD.gmv), 0.0),
            )
            .where(
                PD.tenant_id == tenant_id, PD.date >= start, PD.date <= end,
                PD.campaign_id.is_not(None),
            )
            .group_by(PD.date, PD.campaign_id)
            .having(func.coalesce(func.sum(PD.spend), 0.0) > 0)
        )
    ).all()
    catalogue = {
        c.campaign_id: c
        for c in (
            await session.execute(select(Ad).where(Ad.tenant_id == tenant_id))
        ).scalars().all()
    }
    out = []
    for day, cid, spend, gmv in rows:
        cat = catalogue.get(cid)
        out.append(
            {
                "date": day,
                "campaign_id": cid,
                "platform": "instamart",
                "name": cat.name if cat else None,
                "type": _type_label(cat.campaign_type) if cat else None,
                "budget_consumed": round(float(spend), 2),
                "daily_budget": (
                    int(cat.daily_budget)
                    if cat and cat.daily_budget is not None
                    else None
                ),
                "ad_sales": round(float(gmv), 2),
            }
        )
    return out


async def budget_split(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Spend + recomputed RoAS per campaign type, windowed, for the
    budget-split donut — same shape and now the same windowing as Zepto's
    (`zepto_ads.budget_split`).

    Used to be LIFETIME (`instamart_ad_campaigns.spend`, that table's own
    date filter changes GMV/impressions but never spend — see module
    docstring), same limitation the Campaign insights table had until it was
    fixed the same way this is: sum the real per-day, per-campaign figures
    from `instamart_ad_product_daily` instead, then look up each campaign's
    TYPE (not a time-series value, stays from the lifetime table) to bucket
    by. A campaign with no product_daily rows in this window contributes
    nothing to its type's bucket, same as it contributing zero would.
    """
    from app.models.instamart_ads import InstamartAdProductDaily as PD

    campaign_types = dict(
        (await session.execute(
            select(Ad.campaign_id, Ad.campaign_type).where(Ad.tenant_id == tenant_id)
        )).all()
    )
    metrics_rows = (
        await session.execute(
            select(
                PD.campaign_id,
                func.coalesce(func.sum(PD.spend), 0.0),
                func.coalesce(func.sum(PD.gmv), 0.0),
            )
            .where(
                PD.tenant_id == tenant_id, PD.date >= start, PD.date <= end,
                PD.campaign_id.is_not(None),
            )
            .group_by(PD.campaign_id)
        )
    ).all()

    by_type: dict[str, dict] = {}
    for cid, spend, gmv in metrics_rows:
        t = _type_label(campaign_types.get(cid)) or "Unknown"
        bucket = by_type.setdefault(t, {"spend": 0.0, "gmv": 0.0})
        bucket["spend"] += float(spend)
        bucket["gmv"] += float(gmv)
    out = [
        {
            "campaign_type": t,
            "budget_consumed": round(b["spend"], 2),
            "ad_sales": round(b["gmv"], 2),
            "roas": round(b["gmv"] / b["spend"], 4) if b["spend"] else 0.0,
        }
        for t, b in by_type.items()
    ]
    out.sort(key=lambda r: r["budget_consumed"], reverse=True)
    return out


async def products(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
) -> list[dict]:
    """Per-product rollup over the window, account-wide (from
    `instamart_ad_product_daily` — see asset_metrics.py). `candidate_id` is
    the same id `sku_snapshots.platform_product_id` carries, so name/pack are
    resolved with a join rather than a separate catalogue fetch.

    Rows whose candidate_id doesn't resolve to a known product are dropped,
    not shown unnamed: verified live that a brand-wide campaign type (e.g.
    Search Auto Suggest) reports its `DIMENSION_TYPE_AD_CANDIDATE` as the
    ACCOUNT'S OWN brand id, not a product — showing that as an unlabelled
    "product" row (it was the single highest-spend row, ₹32k) would be a
    real, misleading blank rather than an honest gap.

    Grouped by candidate_id only (not campaign_id), so a product advertised
    by several campaigns is one row here with the combined total — see
    `_campaign_breakdown` for the per-campaign split attached as `campaigns`.
    """
    from app.models.instamart_ads import InstamartAdProductDaily as PD
    from app.models.instamart_ads import InstamartProductCatalog as Catalog
    from app.models.search import SkuSnapshot

    rows = (
        await session.execute(
            select(
                PD.candidate_id,
                func.coalesce(func.sum(PD.spend), 0.0),
                func.coalesce(func.sum(PD.gmv), 0.0),
                func.coalesce(func.sum(PD.impressions), 0),
                func.coalesce(func.sum(PD.clicks), 0),
                func.coalesce(func.sum(PD.add_to_cart_count), 0),
            )
            .where(PD.tenant_id == tenant_id, PD.date >= start, PD.date <= end)
            .group_by(PD.candidate_id)
            .order_by(func.coalesce(func.sum(PD.spend), 0.0).desc())
        )
    ).all()

    names = dict(
        (await session.execute(
            select(SkuSnapshot.platform_product_id, SkuSnapshot.product_name)
            .where(SkuSnapshot.tenant_id == tenant_id, SkuSnapshot.mp_slug == "instamart")
            .distinct(SkuSnapshot.platform_product_id)
        )).all()
    )
    images = dict(
        (await session.execute(
            select(Catalog.candidate_id, Catalog.image_url)
            .where(Catalog.tenant_id == tenant_id)
        )).all()
    )
    campaigns_by_candidate = await _campaign_breakdown(
        session, tenant_id=tenant_id, start=start, end=end, model=PD, key_col=PD.candidate_id,
    )

    return [
        {
            "product_variant_id": cid,
            "product_name": names.get(cid),
            "image_link": images.get(cid),
            "spend": round(float(spend), 2),
            "sales": round(float(gmv), 2),
            "impressions": int(impr),
            "clicks": int(clicks),
            "atc": int(atc),
            "units_sold": 0,  # not reported anywhere on Instamart's ad side
            "ctr": round(clicks / impr * 100, 4) if impr else None,
            "cpc": round(float(spend) / clicks, 2) if clicks else None,
            "cpm": round(float(spend) / impr * 1000, 2) if impr else None,
            "roas": round(float(gmv) / float(spend), 4) if spend else None,
            "campaigns": campaigns_by_candidate.get(cid, []),
        }
        for cid, spend, gmv, impr, clicks, atc in rows
        if cid in names
    ]


async def _campaign_breakdown(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date, model, key_col,
) -> dict[str, list[dict]]:
    """{key: [{campaign_id, campaign_name, spend, gmv, impressions}, ...]},
    sorted by spend desc — which campaign(s) a product/keyword's total is made
    of. Sums exactly to the same total `products()` computes
    (grouping by key_col alone, ignoring campaign_id, gives the total;
    grouping by both gives this breakdown) — verified live against the
    proven-correct unfiltered total (see asset_metrics.py's module docstring).
    """
    rows = (
        await session.execute(
            select(
                key_col,
                model.campaign_id,
                func.coalesce(func.sum(model.spend), 0.0),
                func.coalesce(func.sum(model.gmv), 0.0),
                func.coalesce(func.sum(model.impressions), 0),
            )
            .where(
                model.tenant_id == tenant_id, model.date >= start, model.date <= end,
                model.campaign_id.is_not(None),
            )
            .group_by(key_col, model.campaign_id)
        )
    ).all()
    campaign_ids = {r[1] for r in rows}
    names = dict(
        (await session.execute(
            select(Ad.campaign_id, Ad.name).where(
                Ad.tenant_id == tenant_id, Ad.campaign_id.in_(campaign_ids)
            )
        )).all()
    ) if campaign_ids else {}

    out: dict[str, list[dict]] = {}
    for key, cid, spend, gmv, impr in rows:
        out.setdefault(key, []).append({
            "campaign_id": cid,
            "campaign_name": names.get(cid, cid),
            "spend": round(float(spend), 2),
            "sales": round(float(gmv), 2),
            "impressions": int(impr),
        })
    for lst in out.values():
        lst.sort(key=lambda c: c["spend"], reverse=True)
    return out


async def campaign_keywords(
    session: AsyncSession, *, tenant_id: uuid.UUID, campaign_id: str, start: date, end: date,
    limit: int = 10,
) -> list[dict]:
    """Top keywords by spend for ONE campaign, windowed — powers the Campaign
    insights drawer's "Top keywords by spend" section for an Instamart
    campaign, the same spot Blinkit/Zepto campaigns already fill from their
    own (campaign-keyed) tables. Instamart's `instamart_ad_keyword_daily` has
    carried a real campaign_id since asset_metrics.py started requesting
    DIMENSION_TYPE_CAMPAIGN, so this is a plain filtered rollup, not a
    workaround — see that module's docstring for how campaign_id got there.

    No `most_viewed_position` (Instamart's keyword API doesn't report a
    ranked position anywhere, unlike Blinkit's `most_viewed_position`) — the
    caller should render that column as "not reported" rather than blank,
    same as every other absent-metric convention in this app.
    """
    from app.models.instamart_ads import InstamartAdKeywordDaily as KD

    rows = (
        await session.execute(
            select(
                KD.keyword,
                func.coalesce(func.sum(KD.spend), 0.0),
                func.coalesce(func.sum(KD.gmv), 0.0),
                func.coalesce(func.sum(KD.impressions), 0),
            )
            .where(
                KD.tenant_id == tenant_id, KD.campaign_id == campaign_id,
                KD.date >= start, KD.date <= end,
            )
            .group_by(KD.keyword)
            .order_by(func.coalesce(func.sum(KD.spend), 0.0).desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "keyword": kw,
            "spend": round(float(spend), 2),
            "sales": round(float(gmv), 2),
            "impressions": int(impr),
            "roas": round(float(gmv) / float(spend), 4) if spend else None,
        }
        for kw, spend, gmv, impr in rows
    ]


async def keyword_rows(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
) -> list[dict]:
    """Every campaign × keyword summed over the window — the Insights keyword table's
    Instamart rows, at the same grain as Blinkit's and Zepto's (2026-10-08; replaced the
    account-wide `keywords()` and its `/instamart-keywords` card). From
    `instamart_ad_keyword_daily` (campaign-attributed), grouped by campaign AND keyword. Rows
    without a campaign id are left out: they cannot be put under a campaign.

    No match type and no position (Instamart reports neither); no orders (no unit count on
    Instamart's ad side). Clicks and add-to-carts are reported."""
    from app.models.instamart_ads import InstamartAdKeywordDaily as KD

    rows = (
        await session.execute(
            select(
                KD.campaign_id,
                KD.keyword,
                func.coalesce(func.sum(KD.spend), 0.0),
                func.coalesce(func.sum(KD.gmv), 0.0),
                func.coalesce(func.sum(KD.impressions), 0),
                func.coalesce(func.sum(KD.clicks), 0),
                func.coalesce(func.sum(KD.add_to_cart_count), 0),
            )
            .where(KD.tenant_id == tenant_id, KD.date >= start, KD.date <= end,
                   KD.campaign_id.is_not(None))
            .group_by(KD.campaign_id, KD.keyword)
        )
    ).all()
    return [
        {
            "platform": "instamart",
            "campaign_id": cid,
            "keyword": kw,
            "spend": round(float(spend), 2),
            "sales": round(float(gmv), 2),
            "impressions": int(impr),
            "clicks": int(clicks),
            "atc": int(atc),
        }
        for cid, kw, spend, gmv, impr, clicks, atc in rows
    ]
