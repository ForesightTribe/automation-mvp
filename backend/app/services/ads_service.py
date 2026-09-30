"""Marketing / advertising data for a client (paid activity on the platform).

Metrics come from the per-campaign daily backbone (`BlinkitAdCampaignDaily`);
`BlinkitAdCampaign` supplies campaign metadata and `BlinkitAdCampaignDetail` the
keyword/asset breakdown. RoAS is always recomputed as ad_sales / spend over the
window (never an average of daily ratios). All queries are `tenant_id`-scoped and
optionally filtered to a set of marketplaces via the `platform` column (None =
every platform — today only Blinkit has ad data).

This module is READ-ONLY analytics. The v1 Campaign Manager (budget scheduler, bid
optimizer, live-position scraping and the Blinkit writes behind them) was retired on
2026-09-03 and deleted along with the `ad_campaigns/` package it drove — including its
`bid_optimizer_rules.json` side-writes, which were a global, non-tenant-scoped file.
Campaign automation lives in `campaign_manager/` and writes only through its own gated
choke-point. Nothing here launches a browser or mutates a marketplace."""
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import Numeric, case, cast, distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)

from app.dependencies import Pagination
from app.models.blinkit_marketing import (
    BlinkitAdCampaign,
    BlinkitAdCampaignDaily,
    BlinkitAdCampaignDetail,
    BlinkitBrandCollection,
    BlinkitSponsoredSOV,
    BlinkitVisibilityPlan,
)
from app.schemas.ads import CampaignRow, KeywordRow
from app.schemas.common import Page
from app.utils.cache import ttl_cache
from app.services import instamart_ads, reference_service, zepto_ads
# The pure status vocabularies — NOT the adapters, which pull in Playwright.
from campaign_manager import repo as cm_repo
from campaign_manager.marketplaces import canonical_status
from campaign_manager.marketplaces import supported as supported_marketplaces
# Shared window helpers — reused so ad aggregates stay identical to the Overview's.
from app.services.analytics_service import _ads_agg, _metric, _roas as _blended_roas

AdDaily = BlinkitAdCampaignDaily
Detail = BlinkitAdCampaignDetail

# Sort keys exposed by the campaign table -> the rollup field they order by.
_CAMPAIGN_SORTS = {
    "spend": "budget_consumed",
    "roas": "roas",
    "sales": "ad_sales",
    "impressions": "impressions",
}


async def _recent_campaign_cutoff(session: AsyncSession, tenant_id: uuid.UUID):
    """`scraped_at` a campaign must reach to count as part of the CURRENT account.

    The catalogue scrape upserts whatever Blinkit returns, so a campaign that stops coming
    back (the pre-migration account's) keeps its last `scraped_at` forever. Within 2 h of the
    newest scrape = returned by the latest run. None when the tenant has no campaigns."""
    latest = (
        await session.execute(
            select(func.max(BlinkitAdCampaign.scraped_at))
            .where(BlinkitAdCampaign.tenant_id == tenant_id)
        )
    ).scalar()
    return latest - timedelta(hours=2) if latest else None


def _roas(ad_sales: float, spend: float) -> float:
    """Display RoAS for table/chart rows — 0.0 (not None) when there's no spend."""
    return round(ad_sales / spend, 4) if spend else 0.0


def _acos(spend: float, ad_sales: float) -> float | None:
    """ACoS = spend / ad_sales (inverse of RoAS, lower is better). None when
    there's no ad-attributed revenue to divide by."""
    return round(float(spend) / float(ad_sales), 4) if ad_sales else None


def _ad_conds(tenant_id: uuid.UUID, start: date, end: date, marketplaces):
    conds = [
        AdDaily.tenant_id == tenant_id,
        AdDaily.date >= start,
        AdDaily.date <= end,
    ]
    if marketplaces is not None:
        conds.append(AdDaily.platform.in_(marketplaces))
    return conds


async def _summary_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None,
) -> tuple:
    """(spend, impressions, ad_sales, atc, units, active_campaigns) for one window.
    Active campaigns = distinct campaigns with any daily row in the window."""
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
                func.coalesce(func.sum(AdDaily.atc), 0),
                func.coalesce(func.sum(AdDaily.quantities_sold), 0),
                func.count(distinct(AdDaily.campaign_id)),
            ).where(*_ad_conds(tenant_id, start, end, marketplaces))
        )
    ).one()

    if zepto_ads.wants_zepto(marketplaces):
        z = await zepto_ads.summary_agg(session, tenant_id=tenant_id, start=start, end=end)
        totals = tuple(a + b for a, b in zip(totals, z))

    if instamart_ads.wants_instamart(marketplaces):
        # Real window now (instamart_ad_account_daily) -- unlike the
        # campaigns table, this one genuinely has day-level data, so a real
        # previous-period comparison is possible and this is called once per
        # window, same as Blinkit/Zepto above.
        i = await instamart_ads.summary_agg(session, tenant_id=tenant_id, start=start, end=end)
        totals = tuple(a + b for a, b in zip(totals, i))

    return totals


async def get_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
    marketplaces: list[str] | None = None,
) -> dict:
    """KPI strip — each tile vs the equal-length previous window."""
    spend, impr, sales, atc, units, camps = await _summary_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=marketplaces
    )
    p_spend, p_impr, p_sales, p_atc, p_units, p_camps = await _summary_agg(
        session,
        tenant_id=tenant_id,
        start=prev_start,
        end=prev_end,
        marketplaces=marketplaces,
    )
    return {
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(sales, p_sales),
        "roas": _metric(_blended_roas(sales, spend), _blended_roas(p_sales, p_spend)),
        "acos": _metric(_acos(spend, sales), _acos(p_spend, p_sales)),
        "impressions": _metric(impr, p_impr),
        "atc": _metric(atc, p_atc),
        "units_sold": _metric(units, p_units),
        "active_campaigns": _metric(camps, p_camps),
    }


async def _campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    status: str | None = None,
    sort: str = "spend",
    order: str = "desc",
    recent_only: bool = False,
) -> Page[CampaignRow]:
    # Per-campaign rollup of the daily backbone over the window.
    rollups = (
        await session.execute(
            select(
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.atc), 0),
                func.coalesce(func.sum(AdDaily.quantities_sold), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.campaign_id)
        )
    ).all()
    metrics = {
        cid: {
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "atc": int(a),
            "quantities_sold": int(q),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for cid, b, i, a, q, s in rollups
    }

    # Campaign metadata (latest snapshot, one row per campaign).
    conds = [BlinkitAdCampaign.tenant_id == tenant_id]
    if marketplaces is not None:
        conds.append(BlinkitAdCampaign.platform.in_(marketplaces))
    if status:
        conds.append(BlinkitAdCampaign.status == status)
    if recent_only:
        cutoff = await _recent_campaign_cutoff(session, tenant_id)
        if cutoff:
            conds.append(BlinkitAdCampaign.scraped_at >= cutoff)
    campaigns = (
        await session.execute(select(BlinkitAdCampaign).where(*conds))
    ).scalars().all()

    zeros = {
        "budget_consumed": 0.0,
        "impressions": 0,
        "atc": 0,
        "quantities_sold": 0,
        "ad_sales": 0.0,
        "roas": 0.0,
    }
    rows = [
        {
            "campaign_id": c.campaign_id,
            "platform": c.platform,
            "name": c.name,
            "type": c.type,
            "status": c.status,
            "daily_budget": c.daily_budget,
            **metrics.get(c.campaign_id, zeros),
        }
        for c in campaigns
    ]

    if zepto_ads.wants_zepto(marketplaces):
        # Zepto campaigns have no BlinkitAdCampaign metadata row to join to —
        # its campaigns endpoint returns identity and metrics together — so they
        # are appended already-shaped rather than merged by campaign_id. The
        # two marketplaces' ids are separate namespaces and never collide.
        for z in await zepto_ads.campaigns(session, tenant_id=tenant_id, start=start, end=end,
                                           recent_only=recent_only):
            if status and (z.get("status") or "") != status:
                continue
            rows.append(
                {
                    "campaign_id": z["campaign_id"],
                    "platform": zepto_ads.SLUG,
                    "name": z["name"],
                    "type": z.get("campaign_type"),
                    "status": z.get("status"),
                    # Whole rupees on Zepto; CampaignRow types it int.
                    "daily_budget": (
                        int(z["daily_budget"]) if z.get("daily_budget") is not None else None
                    ),
                    "budget_consumed": z["spend"],
                    "impressions": z["impressions"],
                    "clicks": z["clicks"],
                    "atc": z["atc"],
                    "quantities_sold": z["units_sold"],
                    "ad_sales": z["sales"],
                    "roas": z["roas"] or 0.0,
                }
            )

    if instamart_ads.wants_instamart(marketplaces):
        # Instamart's per-campaign METRICS are lifetime, not a daily backbone
        # (see instamart_ads.py) -- but WHICH campaigns are listed is still
        # windowed by start_time/end_time overlap, matching how the portal's
        # own date picker narrows "All Campaigns" for the selected range.
        for i in await instamart_ads.campaigns(session, tenant_id=tenant_id, start=start, end=end):
            if status and (i.get("status") or "") != status:
                continue
            rows.append(
                {
                    "campaign_id": i["campaign_id"],
                    # Required on every row (ZC-D1) — the automatable check and the
                    # canonical state below are both keyed by it.
                    "platform": "instamart",
                    "name": i["name"],
                    "type": i.get("campaign_type"),
                    "status": i.get("status"),
                    "daily_budget": i.get("daily_budget"),
                    "budget_consumed": i["spend"],
                    "impressions": i["impressions"],
                    "atc": i["atc"],
                    "quantities_sold": i["units_sold"],
                    "ad_sales": i["sales"],
                    "roas": i["roas"] or 0.0,
                }
            )

    # Campaign count per client is small -> rank + paginate in memory.
    sort_key = _CAMPAIGN_SORTS.get(sort, "budget_consumed")
    rows.sort(key=lambda r: r[sort_key], reverse=(order != "asc"))
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    # Which of this page's campaigns the automations may not touch (ZC-D3) — one catalogue
    # query per marketplace on the page, never per row.
    refused: dict[tuple[str, int | str], str] = {}
    driven = set(supported_marketplaces())
    for mp in {r["platform"] for r in page}:
        if mp not in driven:
            # A marketplace the automations cannot drive at all (Instamart): say so on every
            # row rather than asking a catalogue — `automation_refusals` would read it as
            # Blinkit's, and Instamart's campaign ids are UUIDs, not ints.
            for r in page:
                if r["platform"] == mp:
                    refused[(mp, r["campaign_id"])] = (
                        f"automations are not available on {mp.title()} yet")
            continue
        # On THIS request's session — a second session here held two pooled connections
        # per request and let bursts (Insights' per-day lists) deadlock the pool.
        for cid, why in (await cm_repo.automation_refusals(
                tenant_id, mp, [r["campaign_id"] for r in page if r["platform"] == mp],
                db=session)).items():
            refused[(mp, cid)] = why
    # The canonical state beside the raw status — see `CampaignRow.state`. Computed by the
    # same pure vocabulary the engines use, so the button the UI offers is the transition
    # the engine will accept.
    items = [CampaignRow.model_validate({
        **r, "state": canonical_status(r["platform"], r.get("status")),
        "automatable": (r["platform"], r["campaign_id"]) not in refused,
        "not_automatable_reason": refused.get((r["platform"], r["campaign_id"])),
    }) for r in page]
    return Page.build(items, total, pagination)


async def get_campaigns_daily(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Every campaign's spend per DAY over the window — what `get_campaigns` returns for a
    one-day window, for every day at once (2026-09-25). The budget-utilisation views asked
    `/ads/campaigns` once per day, up to 31 requests; this is one request and two queries
    per marketplace.

    Same rules as `get_campaigns`, so the two agree row for row: a Blinkit campaign needs a
    catalogue row (its metadata) to be listed, and its `daily_budget` is the current one.
    Only days with spend come back.
    """
    rollups = (
        await session.execute(
            select(
                AdDaily.date,
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.date, AdDaily.campaign_id)
            .having(func.coalesce(func.sum(AdDaily.budget_consumed), 0.0) > 0)
        )
    ).all()
    conds = [BlinkitAdCampaign.tenant_id == tenant_id]
    if marketplaces is not None:
        conds.append(BlinkitAdCampaign.platform.in_(marketplaces))
    meta = {
        c.campaign_id: c
        for c in (await session.execute(select(BlinkitAdCampaign).where(*conds)))
        .scalars()
        .all()
    }
    out = [
        {
            "date": day,
            "campaign_id": cid,
            "platform": meta[cid].platform,
            "name": meta[cid].name,
            "type": meta[cid].type,
            "budget_consumed": round(float(spend), 2),
            "daily_budget": meta[cid].daily_budget,
            "ad_sales": round(float(sales), 2),
        }
        for day, cid, spend, sales in rollups
        if cid in meta
    ]
    if zepto_ads.wants_zepto(marketplaces):
        out.extend(
            await zepto_ads.campaigns_daily(session, tenant_id=tenant_id, start=start, end=end)
        )
    out.sort(key=lambda r: (r["date"], -r["budget_consumed"]))
    return out



# ⚠️ `_campaigns`, `_campaigns_settled` and `get_campaigns` carry the SAME
# parameter list, and a parameter added to one must be added to all three or it
# is silently dropped on the way through. Spelled out rather than **kwargs
# because the cache key is built by binding arguments to the signature: a
# var-keyword wrapper cannot fill in defaults a caller omitted, so every call
# would land on its own entry and nothing would ever hit.
@ttl_cache(24 * 60 * 60)
async def _campaigns_settled(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    status: str | None = None,
    sort: str = "spend",
    order: str = "desc",
    recent_only: bool = False,
) -> Page[CampaignRow]:
    """A window that has already closed. Cached: nothing a user does now can
    change what a campaign spent yesterday."""
    return await _campaigns(
        session,
        tenant_id=tenant_id,
        pagination=pagination,
        start=start,
        end=end,
        marketplaces=marketplaces,
        status=status,
        sort=sort,
        order=order,
        recent_only=recent_only,
    )


async def get_campaigns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
    status: str | None = None,
    sort: str = "spend",
    order: str = "desc",
    recent_only: bool = False,
) -> Page[CampaignRow]:
    """⚠️ A window that includes TODAY is never cached. Budgets and bids are
    written from the Campaign Manager and the caller invalidates on write, so a
    cached open window would show someone their own change being ignored. A
    window that ended before today cannot move."""
    fn = _campaigns_settled if end < date.today() else _campaigns
    return await fn(
        session,
        tenant_id=tenant_id,
        pagination=pagination,
        start=start,
        end=end,
        marketplaces=marketplaces,
        status=status,
        sort=sort,
        order=order,
        recent_only=recent_only,
    )

async def get_performance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Daily account totals (summed across campaigns) with the day's RoAS."""
    rows = (
        await session.execute(
            select(
                AdDaily.date,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.impressions), 0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.date)
            .order_by(AdDaily.date)
        )
    ).all()
    series = [
        {
            "date": d,
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for d, b, i, s in rows
    ]
    if zepto_ads.wants_zepto(marketplaces):
        z = await zepto_ads.performance(session, tenant_id=tenant_id, start=start, end=end)
        by_date: dict = {r["date"]: dict(r) for r in series}
        for r in z:
            cur = by_date.get(r["date"])
            if cur:
                cur["budget_consumed"] += r["budget_consumed"]
                cur["impressions"] += r["impressions"]
                cur["ad_sales"] += r["ad_sales"]
                # RoAS is a ratio, so recompute from the merged bases rather
                # than averaging the two marketplaces' ratios.
                cur["roas"] = _roas(cur["ad_sales"], cur["budget_consumed"])
            else:
                by_date[r["date"]] = dict(r)
        series = [by_date[k] for k in sorted(by_date)]

    if instamart_ads.wants_instamart(marketplaces):
        i = await instamart_ads.performance(session, tenant_id=tenant_id, start=start, end=end)
        by_date = {r["date"]: dict(r) for r in series}
        for r in i:
            cur = by_date.get(r["date"])
            if cur:
                cur["budget_consumed"] += r["budget_consumed"]
                cur["impressions"] += r["impressions"]
                cur["ad_sales"] += r["ad_sales"]
                cur["roas"] = _roas(cur["ad_sales"], cur["budget_consumed"])
            else:
                by_date[r["date"]] = dict(r)
        series = [by_date[k] for k in sorted(by_date)]
    return series


async def get_budget_split(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Spend + recomputed RoAS per campaign type (the denormalized `campaign_type`
    on the daily rows) — drives the budget-split donut and the by-type table."""
    rows = (
        await session.execute(
            select(
                AdDaily.campaign_type,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.campaign_type)
        )
    ).all()
    out = [
        {
            "campaign_type": t,
            "budget_consumed": round(float(b), 2),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for t, b, s in rows
    ]
    out.sort(key=lambda r: r["budget_consumed"], reverse=True)
    return out


async def get_keywords(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    campaign_id: int | None = None,
    marketplaces: list[str] | None = None,
    target_type: str | None = None,
    sort: str = "spend",
    order: str = "desc",
    recent_only: bool = False,
) -> Page[KeywordRow]:
    """Keyword / asset performance from the latest detail snapshot per campaign.

    `BlinkitAdCampaignDetail` is a range-aggregate snapshot (not daily), so we keep
    only each campaign's most recent `snapshot_date` rather than summing across
    snapshots.

    ONE row per (campaign, target, match_type). Blinkit reports a keyword once per
    SUB-campaign, so the raw snapshot can hold the same keyword 30 times for one campaign
    (seen 2026-09-16); every list built on this endpoint showed it 30 times, each with a
    slice of the numbers. Counts and money are summed; ROAS is recomputed from the sums;
    position is the best held. A keyword Blinkit did not split keeps its reported ratios
    untouched — Blinkit's `cpm` is not spend/impressions (351 reported vs 358 derived), so
    a merged CPM is the impression-weighted mean of the reported ones, not a derivation.

    `recent_only` drops campaigns the latest catalogue scrape no longer returns (the
    pre-migration account's), same rule as `/ads/campaigns?recent_only`. Their last
    snapshot is still "latest" for them, and they mostly share names with their
    replacements, so without it every keyword picker lists each campaign twice.

    ⚠️ The latest-snapshot pick, sort, count and page slice all happen in SQL. This used
    to load every detail row for the tenant (51k, growing ~700/day) and do them in
    Python — ~9 s and ~200 MB per page, and the Automations picker fetches pages in
    parallel, which exhausted the Supabase pooler (2026-09-11). Now only the page leaves
    the database (~44 ms server-side)."""
    conds = [Detail.tenant_id == tenant_id]
    if campaign_id is not None:
        conds.append(Detail.campaign_id == campaign_id)
    if marketplaces is not None:
        conds.append(Detail.platform.in_(marketplaces))
    if target_type:
        conds.append(Detail.target_type == target_type)
    if recent_only:
        cutoff = await _recent_campaign_cutoff(session, tenant_id)
        if cutoff:
            conds.append(
                Detail.campaign_id.in_(
                    select(BlinkitAdCampaign.campaign_id).where(
                        BlinkitAdCampaign.tenant_id == tenant_id,
                        BlinkitAdCampaign.scraped_at >= cutoff,
                    )
                )
            )

    # Each campaign's latest snapshot date under the SAME filters as the rows, so e.g.
    # target_type='keyword' picks each campaign's latest *keyword* snapshot. Every row on
    # that date is kept (a snapshot holds many keywords) — hence a join, not DISTINCT ON.
    latest = (
        select(Detail.campaign_id, func.max(Detail.snapshot_date).label("snapshot_date"))
        .where(*conds)
        .group_by(Detail.campaign_id)
        .subquery()
    )

    n = func.count()
    spend = func.sum(Detail.budget_consumed)
    impressions = func.sum(Detail.impressions)
    direct_sales = func.sum(Detail.direct_sales)
    indirect_sales = func.sum(Detail.indirect_sales)

    def _merged_ratio(reported, derived):
        # Unsplit → Blinkit's own figure; split → recomputed from the sums, rounded like
        # Blinkit's (2 dp), 0.0 on no spend as the stored rows do.
        return case(
            (n == 1, func.max(reported)),
            else_=func.coalesce(
                func.round(cast(derived / func.nullif(spend, 0), Numeric), 2), 0.0
            ),
        )

    merged = (
        select(
            Detail.campaign_id,
            func.max(Detail.campaign_type).label("campaign_type"),
            Detail.target_type,
            Detail.target,
            Detail.match_type,
            impressions.label("impressions"),
            spend.label("budget_consumed"),
            case(
                (n == 1, func.max(Detail.cpm)),
                else_=func.coalesce(
                    func.sum(Detail.cpm * Detail.impressions) / func.nullif(impressions, 0),
                    func.max(Detail.cpm),
                ),
            ).label("cpm"),
            func.sum(Detail.direct_atc).label("direct_atc"),
            func.sum(Detail.indirect_atc).label("indirect_atc"),
            direct_sales.label("direct_sales"),
            indirect_sales.label("indirect_sales"),
            func.sum(Detail.new_users_acquired).label("new_users_acquired"),
            func.min(Detail.most_viewed_position).label("most_viewed_position"),
            _merged_ratio(Detail.direct_roas, direct_sales).label("direct_roas"),
            _merged_ratio(Detail.total_roas, direct_sales + indirect_sales).label("total_roas"),
            latest.c.snapshot_date,
        )
        .join(
            latest,
            (Detail.campaign_id == latest.c.campaign_id)
            & (Detail.snapshot_date == latest.c.snapshot_date),
        )
        .where(*conds)
        .group_by(
            Detail.campaign_id,
            Detail.target_type,
            Detail.target,
            Detail.match_type,
            latest.c.snapshot_date,
        )
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(merged)) or 0

    sort_cols = {
        "spend": merged.c.budget_consumed,
        "roas": merged.c.total_roas,
        "sales": merged.c.direct_sales + merged.c.indirect_sales,
        "impressions": merged.c.impressions,
    }
    col = sort_cols.get(sort, sort_cols["spend"])
    # The group key breaks ties so paging is stable. Without it, rows with equal values come
    # back in arbitrary order and pages fetched in parallel can repeat or skip a row.
    rows = (
        await session.execute(
            select(merged)
            .order_by(
                col.asc() if order == "asc" else col.desc(),
                merged.c.campaign_id,
                merged.c.target,
                merged.c.match_type,
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).mappings().all()

    items = [KeywordRow.model_validate(dict(r)) for r in rows]
    return Page.build(items, total, pagination)


async def get_sponsored_sov(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[BlinkitSponsoredSOV]:
    conds = [
        BlinkitSponsoredSOV.tenant_id == tenant_id,
        BlinkitSponsoredSOV.date >= start,
        BlinkitSponsoredSOV.date <= end,
    ]
    if marketplaces is not None:
        conds.append(BlinkitSponsoredSOV.platform.in_(marketplaces))
    rows = (
        await session.execute(
            select(BlinkitSponsoredSOV)
            .where(*conds)
            .order_by(BlinkitSponsoredSOV.keyword, BlinkitSponsoredSOV.date.desc())
            .distinct(BlinkitSponsoredSOV.keyword)
        )
    ).scalars().all()
    rows.sort(key=lambda r: r.sov, reverse=True)
    return rows


async def get_visibility_plans(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitVisibilityPlan]:
    return (
        await session.execute(
            select(BlinkitVisibilityPlan)
            .where(BlinkitVisibilityPlan.tenant_id == tenant_id)
            .order_by(BlinkitVisibilityPlan.budget.desc())
        )
    ).scalars().all()


async def get_collections(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[BlinkitBrandCollection]:
    return (
        await session.execute(
            select(BlinkitBrandCollection)
            .where(BlinkitBrandCollection.tenant_id == tenant_id)
            .order_by(BlinkitBrandCollection.number_of_products.desc())
        )
    ).scalars().all()


async def _mp_ad_metrics(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> dict:
    """Ad metric set for a single marketplace, current vs previous window."""
    mp = [slug]
    spend, impr, sales = await _ads_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=mp
    )
    p_spend, p_impr, p_sales = await _ads_agg(
        session, tenant_id=tenant_id, start=prev_start, end=prev_end, marketplaces=mp
    )
    return {
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(sales, p_sales),
        "roas": _metric(_blended_roas(sales, spend), _blended_roas(p_sales, p_spend)),
        "impressions": _metric(impr, p_impr),
    }


async def get_marketplace_breakdown(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> list[dict]:
    """One row per marketplace with its ad slice. Connected marketplaces carry
    metrics; unconnected ones are bare (connected=False) so the UI shows a 'Not
    connected' card instead of faking data. Lets 'All' be visibly split per MP
    rather than only a combined total."""
    marketplaces = await reference_service.list_marketplaces(session)
    rows: list[dict] = []
    for mp in marketplaces:
        row = {
            "slug": mp["slug"],
            "name": mp["name"],
            "color": mp["color"],
            "connected": mp["connected"],
        }
        if mp["connected"]:
            row.update(
                await _mp_ad_metrics(
                    session,
                    tenant_id=tenant_id,
                    slug=mp["slug"],
                    start=start,
                    end=end,
                    prev_start=prev_start,
                    prev_end=prev_end,
                )
            )
        rows.append(row)
    return rows
