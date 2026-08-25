"""Zepto-side reads for the Ads page.

Separate from `ads_service.py` because the sources differ: Blinkit spreads ads
across six tables (campaign identity, daily metrics, keyword detail, SOV,
collections, visibility plans), whereas Zepto's campaign identity and metrics
land on one campaign x day table, with keywords on a second.

Return shapes match the `ads_service` functions they pair with, so results from
both marketplaces can be merged without callers knowing which produced them.

What Zepto has no equivalent of, and which therefore stays Blinkit-only rather
than being faked: **budget split**, **brand collections**, **visibility plans**,
and the **direct/indirect attribution split** that Blinkit applies to sales and
add-to-carts — Zepto reports one undifferentiated total for each.

Going the other way, Zepto reports things Blinkit does not: clicks, CPC, eCPM,
per-campaign share-of-voice, ad position, unique reach, new-to-brand share, and
an orders split by whether the sale was the advertised SKU or another one.
"""
import uuid
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoAdCampaignDaily as Ad
from app.models.zepto_seller import ZeptoAdBreakdownDaily as Bd
from app.models.zepto_seller import ZeptoAdKeywordDaily as Kw
from app.models.zepto_seller import ZeptoAdProductDaily as Prod

SLUG = "zepto"


def wants_zepto(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Zepto."""
    return marketplaces is None or SLUG in marketplaces


def _conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    return [Ad.tenant_id == tenant_id, Ad.date >= start, Ad.date <= end]


# Totals here cover EVERY campaign type, which is the right figure for "what
# did this client spend on Zepto ads". It will not equal any single tab on
# Zepto's own Analytics page: that page is per campaign category, so its
# Sponsored Products view excludes Display and Brands campaigns. Measured
# 14-19 Aug 2026: ours Rs 34,848 across all types, Zepto's Sponsored Products
# tab Rs 33,826, the difference being exactly one Display/PCA campaign
# (Rs 1,023). Both are correct; they answer different questions.


# Zepto's own reported ad revenue, from the Analytics page's campaign table.
#
# This was previously reconstructed as `spend * roi`, because the Campaign
# Management endpoint reports a RoAS ratio but no rupee figure. The derivation
# was close — Rs 7,586 against a real Rs 7,580 on 14 Aug, the gap being RoAS
# rounded to 2dp — but it is no longer needed: `/metrics/tabular` reports
# revenue directly, and does respect the date window.
#
# COALESCE to the old derivation for rows scraped before the tabular fetch
# existed, so a mixed-vintage table does not read as a revenue collapse.
_AD_SALES = func.coalesce(
    func.sum(func.coalesce(Ad.revenue, Ad.spend * Ad.roi)), 0.0
)

# Add-to-carts and orders, both from the same tabular view and both windowed.
#
# NOT `Ad.orders`, which comes from the campaigns endpoint and ignores the date
# range entirely — the same campaign returned 427 for a 1-day, a 6-day and a
# 31-day window alike. Summing that per day multiplied it by the number of days
# scraped and put 5,845 on the Units-sold tile. `Ad.windowed_orders` is the
# Analytics view's own orders figure, which does move with the window.
_AD_ATC = func.coalesce(func.sum(Ad.atc), 0)
_AD_UNITS = func.coalesce(func.sum(Ad.windowed_orders), 0)


async def summary_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, float, int, int, int]:
    """(spend, impressions, ad_sales, atc, units, active campaigns).

    Tuple shape matches ads_service._summary_agg so the two marketplaces add.
    """
    spend, impr, sales, atc, units = (
        await session.execute(
            select(
                func.coalesce(func.sum(Ad.spend), 0.0),
                func.coalesce(func.sum(Ad.impressions), 0),
                _AD_SALES,
                _AD_ATC,
                _AD_UNITS,
            ).where(*_conds(tenant_id, start, end))
        )
    ).one()

    # "Active" = had activity in the window, matching what the Blinkit half of
    # this tile counts. Its docstring says "distinct campaigns with any daily
    # row in the window", which sounds broader but isn't: that table is sparse
    # and only ever holds rows for campaigns that spent (verified 14-20 Aug —
    # 219 rows, zero of them zero-spend, 46 campaigns either way).
    #
    # Zepto's table is dense by contrast: the campaigns endpoint returns all 26
    # campaigns every day whether or not they ran, so 118 of 156 rows are
    # zero-spend. Counting "any row" here would give 26 against Blinkit's 46
    # and mean something different, so the activity test is explicit.
    #
    # NOT `is_active`, which is a status flag rather than an activity test — it
    # gives the same 7 on this data, but would diverge for a campaign flagged
    # active that never spent, or one paused after spending earlier in the
    # window.
    active = (
        await session.execute(
            select(func.count(distinct(Ad.campaign_id))).where(
                *_conds(tenant_id, start, end),
                (Ad.spend > 0) | (Ad.impressions > 0),
            )
        )
    ).scalar_one()

    return float(spend), int(impr), float(sales), int(atc), int(units), int(active)


async def ads_agg(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> tuple[float, int, float]:
    """(spend, impressions, ad_sales) — the additive bases only.

    Pairs with analytics_service._ads_agg, which is the shared backbone behind
    the Overview marketplace cards, the Analytics page's ad metrics and the Ads
    page's per-marketplace breakdown. Those three read Blinkit's daily table
    directly, so without this they reported Zepto as zero spend while the Ads
    summary tiles — which go through summary_agg — showed the real figure.

    Deliberately not `summary_agg()[:3]`: that would also run the active
    campaign count, which none of these callers use.
    """
    spend, impr, sales = (
        await session.execute(
            select(
                func.coalesce(func.sum(Ad.spend), 0.0),
                func.coalesce(func.sum(Ad.impressions), 0),
                _AD_SALES,
            ).where(*_conds(tenant_id, start, end))
        )
    ).one()
    return float(spend), int(impr), float(sales)


async def performance(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Daily account totals — same shape as ads_service.get_performance."""
    rows = (
        await session.execute(
            select(
                Ad.date,
                func.coalesce(func.sum(Ad.spend), 0.0),
                func.coalesce(func.sum(Ad.impressions), 0),
                _AD_SALES,
            )
            .where(*_conds(tenant_id, start, end))
            .group_by(Ad.date)
            .order_by(Ad.date)
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
    """Per-campaign rollup over the window.

    Zepto also reports clicks, CPC, eCPM, share-of-voice, ad position, unique
    reach and new-to-brand share, which are stored on the table but not returned
    here: `CampaignRow` has no fields for them, because Blinkit — the schema's
    original and only source until now — does not report them. Surfacing them
    means widening a schema shared with Blinkit, where they would always be null.
    """
    rows = (
        await session.execute(
            select(
                Ad.campaign_id,
                func.max(Ad.campaign_name),
                func.coalesce(func.sum(Ad.spend), 0.0),
                func.coalesce(func.sum(Ad.impressions), 0),
                _AD_SALES,
                _AD_ATC,
                _AD_UNITS,
                func.max(Ad.status),
                func.max(Ad.campaign_type),
            )
            .where(*_conds(tenant_id, start, end))
            .group_by(Ad.campaign_id)
        )
    ).all()
    return [
        {
            # CampaignRow types this as int, and Zepto's ids are numeric.
            "campaign_id": cid,
            "name": name,
            "spend": round(float(spend), 2),
            "impressions": int(impr),
            "sales": round(float(sales), 2),
            "atc": int(atc),
            "units_sold": int(units),
            "roas": round(float(sales) / float(spend), 4) if spend else None,
            "status": status,
            "campaign_type": ctype,
        }
        for cid, name, spend, impr, sales, atc, units, status, ctype in rows
    ]


async def budget_split(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Spend and RoAS per campaign type over the window.

    Split on `campaign_type` (PLA / Display) rather than `campaign_category`
    (sponsored_products / sponsored_brands), for two reasons: it is the same
    column name and the same idea as the Blinkit donut's dimension, so the two
    marketplaces stay comparable; and it describes the campaign itself rather
    than which tab it was found under.

    `campaign_sub_type` would give a finer cut — PLA splits into AUCTION_UP_SELL,
    Display into PCA and PDA — but that has no Blinkit counterpart.
    """
    rows = (
        await session.execute(
            select(
                Ad.campaign_type,
                func.coalesce(func.sum(Ad.spend), 0.0),
                _AD_SALES,
            )
            .where(*_conds(tenant_id, start, end))
            .group_by(Ad.campaign_type)
        )
    ).all()
    out = [
        {
            "campaign_type": t,
            "budget_consumed": round(float(b), 2),
            "ad_sales": round(float(s), 2),
            # Recomputed from the summed bases, never averaged across days —
            # matching how RoAS is derived everywhere else.
            "roas": round(float(s) / float(b), 4) if b else 0.0,
        }
        for t, b, s in rows
    ]
    out.sort(key=lambda r: r["budget_consumed"], reverse=True)
    return out


async def share_of_voice(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Share of voice and ad position per campaign — a SNAPSHOT, not a window.

    Both fields are trailing figures Zepto recomputes on its own schedule
    (its column is titled "SOV - last 7 day"), and neither moves with the
    requested date range: every campaign has exactly one distinct value across
    every day scraped. So this takes the LATEST row per campaign rather than
    summing or averaging — an average over days would silently be an average of
    one repeated number, which reads as windowed data but is not.

    `start`/`end` therefore only bound which scrapes are considered; they do not
    define the period the figures describe. The returned `as_of` date says what
    the numbers actually refer to, so the UI can label it rather than implying
    it matches the date picker.

    Campaigns with no SOV reported (no activity) are excluded — a zero here
    would mean "not measured", not "no visibility".
    """
    latest = (
        select(
            Ad.campaign_id,
            func.max(Ad.date).label("as_of"),
        )
        .where(*_conds(tenant_id, start, end), Ad.sov.is_not(None))
        .group_by(Ad.campaign_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Ad.campaign_id,
                Ad.campaign_name,
                Ad.sov,
                Ad.ad_position,
                Ad.campaign_type,
                Ad.date,
            )
            .join(
                latest,
                (Ad.campaign_id == latest.c.campaign_id) & (Ad.date == latest.c.as_of),
            )
            .where(Ad.tenant_id == tenant_id)
            .order_by(Ad.sov.desc())
        )
    ).all()
    return [
        {
            "campaign_id": cid,
            "campaign_name": name,
            "campaign_type": ctype,
            # Passed through exactly as Zepto reports it. Their Campaign
            # Management column is already labelled a percentage, so it is NOT
            # rescaled here — verify against the dashboard before changing that.
            "sov": sov,
            "ad_position": pos,
            "as_of": d,
        }
        for cid, name, sov, pos, ctype, d in rows
    ]


async def keywords(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> list[dict]:
    """Per-keyword rollup over the window.

    Grain note that matters for any caller merging this with Blinkit's: Zepto
    reports keywords **per brand per campaign category**, with no campaign id
    anywhere in the response. A keyword cannot be attributed to the campaign
    that bid on it, so `campaign_id` is None rather than guessed. That is the
    one place Blinkit's `blinkit_ad_campaign_detail` is genuinely richer.

    Grouped by keyword AND match type, matching the table's grain: Zepto bids
    the same keyword under more than one match type at very different rates
    ("sado bread" took Rs 2,014 on BROAD and Rs 60 on EXACT on 14 Aug), so
    collapsing them would hide which one is actually spending.

    Ratios are recomputed from the summed components rather than averaged —
    averaging a per-day CPC across days weights a day with two clicks the same
    as a day with two hundred.
    """
    rows = (
        await session.execute(
            select(
                Kw.keyword,
                Kw.match_type,
                func.array_agg(distinct(Kw.campaign_category)),
                func.coalesce(func.sum(Kw.spend), 0.0),
                func.coalesce(func.sum(Kw.revenue), 0.0),
                func.coalesce(func.sum(Kw.impressions), 0),
                func.coalesce(func.sum(Kw.clicks), 0),
                func.coalesce(func.sum(Kw.orders), 0),
                func.coalesce(func.sum(Kw.atc), 0),
            )
            .where(Kw.tenant_id == tenant_id, Kw.date >= start, Kw.date <= end)
            .group_by(Kw.keyword, Kw.match_type)
            .order_by(func.coalesce(func.sum(Kw.spend), 0.0).desc())
        )
    ).all()
    return [
        {
            "keyword": kw,
            "match_type": match,
            "ad_types": sorted(t for t in cat if t),
            "impressions": int(impr),
            "clicks": int(clicks),
            "spend": round(float(spend), 2),
            "sales": round(float(rev), 2),
            "atc": int(atc),
            "units_sold": int(orders),
            "ctr": round(clicks / impr * 100, 4) if impr else None,
            "cpc": round(float(spend) / clicks, 2) if clicks else None,
            "cpm": round(float(spend) / impr * 1000, 2) if impr else None,
            "roas": round(float(rev) / float(spend), 4) if spend else None,
        }
        for kw, match, cat, spend, rev, impr, clicks, orders, atc in rows
    ]


def _ratios(spend: float, rev: float, impr: int, clicks: int) -> dict:
    """Ratios rebuilt from summed components rather than averaged.

    Averaging a per-day CPC across days weights a day with two clicks the same
    as a day with two hundred, so every ratio here is derived from the totals.
    """
    return {
        "ctr": round(clicks / impr * 100, 4) if impr else None,
        "cpc": round(spend / clicks, 2) if clicks else None,
        "cpm": round(spend / impr * 1000, 2) if impr else None,
        "roas": round(rev / spend, 4) if spend else None,
    }


async def products(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    campaign_category: str | None = None,
) -> list[dict]:
    """Ad spend and return per advertised SKU over the window.

    Summed across ad types by default, which is what "how much did we spend
    advertising this SKU" means. `campaign_category` narrows to one ad type —
    no product has been observed running under two, but a retail category has,
    so the filter is offered rather than assumed unnecessary.
    """
    conds = [Prod.tenant_id == tenant_id, Prod.date >= start, Prod.date <= end]
    if campaign_category:
        conds.append(Prod.campaign_category == campaign_category)
    rows = (
        await session.execute(
            select(
                Prod.product_variant_id,
                func.max(Prod.product_name),
                func.max(Prod.image_link),
                func.max(Prod.product_category),
                # Which ad types this SKU actually ran under. Aggregated rather
                # than taken with max() because a row may combine more than one,
                # and the UI shows a tag per type so the client can see which
                # spend came from where.
                func.array_agg(distinct(Prod.campaign_category)),
                func.coalesce(func.sum(Prod.spend), 0.0),
                func.coalesce(func.sum(Prod.revenue), 0.0),
                func.coalesce(func.sum(Prod.impressions), 0),
                func.coalesce(func.sum(Prod.clicks), 0),
                func.coalesce(func.sum(Prod.orders), 0),
                func.coalesce(func.sum(Prod.atc), 0),
            )
            .where(*conds)
            .group_by(Prod.product_variant_id)
            .order_by(func.coalesce(func.sum(Prod.spend), 0.0).desc())
        )
    ).all()
    return [
        {
            "product_variant_id": pid,
            "product_name": name,
            "image_link": img,
            "product_category": pcat,
            "ad_types": sorted(t for t in ad_types if t),
            "spend": round(float(spend), 2),
            "sales": round(float(rev), 2),
            "impressions": int(impr),
            "clicks": int(clicks),
            "units_sold": int(orders),
            "atc": int(atc),
            **_ratios(float(spend), float(rev), int(impr), int(clicks)),
        }
        for pid, name, img, pcat, ad_types, spend, rev, impr, clicks, orders, atc in rows
    ]


async def breakdown(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    dimension: str,
    campaign_category: str | None = None,
) -> list[dict]:
    """Ad spend and return per bucket, for one breakdown dimension.

    `dimension` is "category" (the RETAIL category — Breads & Buns, Cheese),
    "city", or "page" (Search Page, Product Details Page, ...). Not to be
    confused with `campaign_category`, which is the AD type and is the optional
    filter here.

    Summed across ad types by default, which matters: Cheese ran under both
    sponsored products and sponsored brands on 19-Aug-2026, so only the combined
    figure is complete. `ad_types` reports which contributed, so a combined row
    still shows where its spend came from.

    Zepto reports no CTR for these views, but it is derivable from the summed
    clicks and impressions, so it is returned like the others.
    """
    conds = [
        Bd.tenant_id == tenant_id,
        Bd.date >= start,
        Bd.date <= end,
        Bd.dimension == dimension,
    ]
    if campaign_category:
        conds.append(Bd.campaign_category == campaign_category)
    rows = (
        await session.execute(
            select(
                Bd.name,
                func.array_agg(distinct(Bd.campaign_category)),
                func.coalesce(func.sum(Bd.spend), 0.0),
                func.coalesce(func.sum(Bd.revenue), 0.0),
                func.coalesce(func.sum(Bd.impressions), 0),
                func.coalesce(func.sum(Bd.clicks), 0),
                func.coalesce(func.sum(Bd.orders), 0),
                func.coalesce(func.sum(Bd.atc), 0),
            )
            .where(*conds)
            .group_by(Bd.name)
            .order_by(func.coalesce(func.sum(Bd.spend), 0.0).desc())
        )
    ).all()
    return [
        {
            "name": name,
            "ad_types": sorted(t for t in ad_types if t),
            "spend": round(float(spend), 2),
            "sales": round(float(rev), 2),
            "impressions": int(impr),
            "clicks": int(clicks),
            "units_sold": int(orders),
            "atc": int(atc),
            **_ratios(float(spend), float(rev), int(impr), int(clicks)),
        }
        for name, ad_types, spend, rev, impr, clicks, orders, atc in rows
    ]
