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

from sqlalchemy import Numeric, case, cast, distinct, func, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)

from app.dependencies import Pagination
from app.models.blinkit_marketing import (
    BlinkitAdCampaign,
    BlinkitAdCampaignDaily,
    BlinkitAdCampaignDetail,
    BlinkitAdCampaignDetailDaily,
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

# The marketplaces with ad data, each read from its own tables (Blinkit's daily backbone,
# `zepto_ads`, `instamart_ads`). Splits iterate these when no marketplace filter is given.
AD_MARKETPLACES = ("blinkit", "zepto", "instamart")

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


# Raw status words of a marketplace with no engine vocabulary (Instamart's are mapped to
# these in `instamart_ads._STATUS_MAP`) → the canonical state, so one status filter covers
# every marketplace. Blinkit's and Zepto's go through `canonical_status`, which the engines
# share; this only fills in what that leaves unmapped.
_FALLBACK_STATE = {
    "ACTIVE": "running",
    "SCHEDULED": "running",
    "PAUSED": "paused",
    "STOPPED": "paused",
    "ON_HOLD": "held",
    "DAILY_BUDGET_EXHAUSTED": "held",
    "COMPLETED": "ended",
    "ENDED": "ended",
    "DRAFT": "draft",
}
_CANONICAL_STATES = {"running", "paused", "held", "ended", "draft"}


def _ui_state(platform: str, status: str | None) -> str | None:
    """`CampaignRow.state`: the engines' canonical state where the marketplace has a
    vocabulary, else the raw word mapped by `_FALLBACK_STATE`, else the raw word as-is."""
    state = canonical_status(platform, status)
    if state in _CANONICAL_STATES or not status:
        return state
    return _FALLBACK_STATE.get(status.strip().upper(), state)


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
    `active_campaigns` = distinct campaigns that RAN in the window (any daily row — Blinkit's
    table only holds rows for campaigns that spent). Labelled "Campaigns that ran" in the UI
    since 2026-10-07: "Active" read like "status = active now" (BLINKIT-NOTES B3)."""
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


async def latest_ad_day(
    session: AsyncSession, *, tenant_id: uuid.UUID, end: date, marketplaces: list[str]
) -> date | None:
    """The newest day on or before `end` that any of `marketplaces` has ad data for — in ONE
    query across each marketplace's daily table. None when there is none.

    Ads are scraped the next morning, so a window ending today almost always ends on a day
    with nothing in it yet (N1, 2026-10-08)."""
    from app.models.instamart_ads import InstamartAdAccountDaily
    from app.models.zepto_seller import ZeptoAdCampaignDaily

    parts = []
    if "blinkit" in marketplaces:
        parts.append(select(func.max(AdDaily.date).label("d")).where(
            AdDaily.tenant_id == tenant_id, AdDaily.date <= end, AdDaily.platform == "blinkit"))
    if zepto_ads.SLUG in marketplaces:
        parts.append(select(func.max(ZeptoAdCampaignDaily.date).label("d")).where(
            ZeptoAdCampaignDaily.tenant_id == tenant_id, ZeptoAdCampaignDaily.date <= end))
    if "instamart" in marketplaces:
        parts.append(select(func.max(InstamartAdAccountDaily.date).label("d")).where(
            InstamartAdAccountDaily.tenant_id == tenant_id, InstamartAdAccountDaily.date <= end))
    if not parts:
        return None
    days = union_all(*parts).subquery()
    return (await session.execute(select(func.max(days.c.d)))).scalar()


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
    """KPI strip — each tile vs a previous window of the same number of DATA days.

    ⚠️ N1 (2026-10-08): the window ends on the newest day with ad data, not on the picker's
    end. Ads are scraped the next morning, so the default "last 7 days" ends today with
    nothing in it: the tiles compared 6 days of spend with 7 and read ~14% low. Now 2–7 Oct
    is compared with 26 Sep–1 Oct. The window actually used comes back as `period`, so the
    page can say "data up to 7 Oct" and draw its comparisons over the same days.

    Each marketplace is aggregated once and the tiles are their sum (A2: 20 queries → ~9; the
    current window used to be aggregated twice, once whole and once per marketplace)."""
    scope = [m for m in (marketplaces if marketplaces is not None else AD_MARKETPLACES)
             if m in AD_MARKETPLACES]
    picked_end = end
    data_end = await latest_ad_day(session, tenant_id=tenant_id, end=end, marketplaces=scope)
    if data_end is not None and start <= data_end < end:
        n = (data_end - start).days + 1
        end, prev_end, prev_start = data_end, start - timedelta(days=1), start - timedelta(days=n)

    parts = {
        mp: await _summary_agg(session, tenant_id=tenant_id, start=start, end=end, marketplaces=[mp])
        for mp in scope
    }
    spend, impr, sales, atc, units, camps = (
        sum(p[i] for p in parts.values()) if parts else 0 for i in range(6))
    if scope:
        p_spend, p_impr, p_sales, p_atc, p_units, p_camps = await _summary_agg(
            session, tenant_id=tenant_id, start=prev_start, end=prev_end, marketplaces=scope)
    else:
        p_spend = p_impr = p_sales = p_atc = p_units = p_camps = 0
    # Each marketplace's share of the tiles, current window only (the split under each one).
    by_mp = [
        {
            "platform": mp, "ad_spend": round(float(m_spend), 2), "ad_sales": round(float(m_sales), 2),
            "impressions": int(m_impr), "atc": int(m_atc),
            # Instamart's units figure is unreliable (confirmed 2026-09-30) — the Insights
            # table already withholds it; the split must not show it either.
            "units_sold": None if mp == "instamart" else int(m_units),
            "active_campaigns": int(m_camps),
        }
        for mp, (m_spend, m_impr, m_sales, m_atc, m_units, m_camps) in parts.items()
    ]
    return {
        "ad_spend": _metric(spend, p_spend),
        "ad_sales": _metric(sales, p_sales),
        "roas": _metric(_blended_roas(sales, spend), _blended_roas(p_sales, p_spend)),
        "acos": _metric(_acos(spend, sales), _acos(p_spend, p_sales)),
        "impressions": _metric(impr, p_impr),
        "atc": _metric(atc, p_atc),
        "units_sold": _metric(units, p_units),
        "active_campaigns": _metric(camps, p_camps),
        "by_marketplace": by_mp,
        # The windows the tiles were actually computed over. `end` < `picked_end` when the
        # last picked days have no ad data yet.
        "period": {"start": start, "end": end, "prev_start": prev_start,
                   "prev_end": prev_end, "picked_end": picked_end},
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
    automation: bool = True,
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
    # `automation=False` (Ads Insights, which shows no automation controls) skips these
    # lookups — a catalogue query per marketplace on every page load (A3, 2026-10-08).
    for mp in ({r["platform"] for r in page} if automation else ()):
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
        **r, "state": _ui_state(r["platform"], r.get("status")),
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
    catalogue row (its metadata) to be listed. A day's `daily_budget` is the one recorded on
    that day's row (B8), else the current one. Only days with spend come back.
    """
    rollups = (
        await session.execute(
            select(
                AdDaily.date,
                AdDaily.campaign_id,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
                # The day's own budget where the scrape recorded one (B8, from 2026-10-08).
                func.max(AdDaily.daily_budget),
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
            # That day's budget; the current one for days before budgets were recorded.
            "daily_budget": day_budget if day_budget is not None else meta[cid].daily_budget,
            "ad_sales": round(float(sales), 2),
        }
        for day, cid, spend, sales, day_budget in rollups
        if cid in meta
    ]
    if zepto_ads.wants_zepto(marketplaces):
        out.extend(
            await zepto_ads.campaigns_daily(session, tenant_id=tenant_id, start=start, end=end)
        )
    if instamart_ads.wants_instamart(marketplaces):
        out.extend(
            await instamart_ads.campaigns_daily(session, tenant_id=tenant_id, start=start, end=end)
        )
    out.sort(key=lambda r: (r["date"], -r["budget_consumed"]))
    return out



# ⚠️ `_campaigns`, `_campaigns_settled` and `get_campaigns` carry the SAME
# parameter list, and a parameter added to one must be added to all three or it
# is silently dropped on the way through. Spelled out rather than **kwargs
# because the cache key is built by binding arguments to the signature: a
# var-keyword wrapper cannot fill in defaults a caller omitted, so every call
# would land on its own entry and nothing would ever hit.
# ⚠️ Short despite the window being closed. A user cannot change what a
# campaign spent yesterday, but the MARKETING SCRAPE re-scrapes the last seven
# days, so those figures are revised overnight. A day-long entry would serve
# the pre-revision numbers well past the correction.
@ttl_cache(30 * 60)
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
    automation: bool = True,
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
        automation=automation,
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
    automation: bool = True,
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
        automation=automation,
    )

async def get_performance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Daily account totals (summed across campaigns and marketplaces) with the day's RoAS,
    and each day split by marketplace (`by_marketplace`) for the "By marketplace" view.

    Each marketplace's series comes from its own daily table; the day's total is the sum of
    its slices, and RoAS is rebuilt from the merged bases (never an average of ratios)."""
    slices: dict[str, list[dict]] = {}
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
    if rows:
        slices["blinkit"] = [
            {"date": d, "budget_consumed": round(float(b), 2), "impressions": int(i),
             "ad_sales": round(float(s), 2)}
            for d, b, i, s in rows
        ]
    if zepto_ads.wants_zepto(marketplaces):
        slices[zepto_ads.SLUG] = await zepto_ads.performance(
            session, tenant_id=tenant_id, start=start, end=end)
    if instamart_ads.wants_instamart(marketplaces):
        slices["instamart"] = await instamart_ads.performance(
            session, tenant_id=tenant_id, start=start, end=end)

    by_date: dict = {}
    for mp, series in slices.items():
        for r in series:
            day = by_date.setdefault(r["date"], {
                "date": r["date"], "budget_consumed": 0.0, "impressions": 0, "ad_sales": 0.0,
                "by_marketplace": {}})
            day["budget_consumed"] += r["budget_consumed"]
            day["impressions"] += r["impressions"]
            day["ad_sales"] += r["ad_sales"]
            day["by_marketplace"][mp] = {
                "budget_consumed": r["budget_consumed"], "impressions": r["impressions"],
                "ad_sales": r["ad_sales"]}
    series = [by_date[k] for k in sorted(by_date)]
    # ⚠️ Every day's RoAS rebuilt here, after the merge. Zepto's and Instamart's own series
    # return None on a zero-spend day (a paused brand's blank day is saved as zero), and a day
    # only ONE marketplace has kept that None — which `AdPerformancePoint.roas: float`
    # refused, so a Zepto-only window over a paused day 500'd (Brik Oven 19–28 Sep).
    for r in series:
        r["budget_consumed"] = round(r["budget_consumed"], 2)
        r["ad_sales"] = round(r["ad_sales"], 2)
        r["roas"] = _roas(r["ad_sales"], r["budget_consumed"])
    return series


async def get_budget_split(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Spend + recomputed RoAS per (marketplace, campaign type) — the Insights "Where the
    spend goes" donut, which groups these by type or by marketplace.

    Every marketplace in scope, each from its own daily table (Blinkit's denormalized
    `campaign_type` on the daily rows; `zepto_ads.budget_split`; `instamart_ads.budget_split`).
    Types are each marketplace's own words (PRODUCT_LISTING / PLA / ITEM) and are never
    merged across marketplaces — `platform` keeps them apart. Until 2026-10-08 this read
    Blinkit only, and Zepto and Instamart each had their own donut and endpoint."""
    rows = (
        await session.execute(
            select(
                AdDaily.platform,
                AdDaily.campaign_type,
                func.coalesce(func.sum(AdDaily.budget_consumed), 0.0),
                func.coalesce(func.sum(AdDaily.ad_sales), 0.0),
            )
            .where(*_ad_conds(tenant_id, start, end, marketplaces))
            .group_by(AdDaily.platform, AdDaily.campaign_type)
        )
    ).all()
    out = [
        {
            "platform": p,
            "campaign_type": t,
            "budget_consumed": round(float(b), 2),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for p, t, b, s in rows
    ]
    if zepto_ads.wants_zepto(marketplaces):
        out += [{**r, "platform": zepto_ads.SLUG} for r in await zepto_ads.budget_split(
            session, tenant_id=tenant_id, start=start, end=end)]
    if instamart_ads.wants_instamart(marketplaces):
        out += [{**r, "platform": "instamart"} for r in await instamart_ads.budget_split(
            session, tenant_id=tenant_id, start=start, end=end)]
    # A type with no spend in the window is not a slice.
    out = [r for r in out if r["budget_consumed"] > 0]
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
    as_of: date | None = None,
) -> Page[KeywordRow]:
    """Keyword / asset performance from the latest detail snapshot per campaign.

    ⚠️ A snapshot is NOT a window the caller chose: the marketing scrape asks Blinkit for one
    total over `snapshot_date − 7 … snapshot_date` (BLINKIT-NOTES B6), so the rows cannot
    follow a date picker. `as_of` picks each campaign's latest snapshot ON OR BEFORE that
    date, so a picker ending 30 Sep shows 23–30 Sep rather than this week; the UI labels the
    real dates from `snapshot_date`. None = the latest snapshot.

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
        .where(*conds, *([Detail.snapshot_date <= as_of] if as_of else []))
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
            func.max(Detail.platform).label("platform"),
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


# What one Blinkit detail snapshot covers: the marketing scrape asks `today − 7 … today`
# and stores it under today (cli/commands/scrape.py, BLINKIT-NOTES B6).
BLINKIT_SNAPSHOT_SPAN = timedelta(days=7)


async def _blinkit_daily_covers(session: AsyncSession, tenant_id: uuid.UUID, start: date) -> bool:
    """Whether Blinkit's per-day keyword history (B6) reaches back to `start` — or to the
    tenant's first Blinkit ad day, when the window starts before any ads existed. Until it
    does (it starts the day the per-day scrape ships, plus whatever is backfilled), a window
    is read from the 8-day snapshot instead, labelled as such, rather than silently summing
    only the days the new table happens to hold."""
    D = BlinkitAdCampaignDetailDaily
    kw_first, ad_first = (await session.execute(select(
        select(func.min(D.date)).where(D.tenant_id == tenant_id).scalar_subquery(),
        select(func.min(AdDaily.date)).where(
            AdDaily.tenant_id == tenant_id, AdDaily.platform == "blinkit").scalar_subquery(),
    ))).one()
    if kw_first is None:
        return False
    return kw_first <= max(start, ad_first or start)


async def _blinkit_keyword_daily(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date,
    campaign_id: int | None = None, keywords_only: bool = True,
) -> list[dict]:
    """Blinkit's per-day keyword report summed over [start, end] — one row per campaign ×
    target × match type, its sub-campaign rows merged (B6). Money and counts summed, CPM the
    impression-weighted mean of Blinkit's reported figure (it is not spend ÷ impressions),
    position the best seen. `keywords_only` drops recommendation placements."""
    D = BlinkitAdCampaignDetailDaily
    conds = [D.tenant_id == tenant_id, D.date >= start, D.date <= end]
    if campaign_id is not None:
        conds.append(D.campaign_id == campaign_id)
    if keywords_only:
        conds.append(D.target_type == "keyword")
    impressions = func.coalesce(func.sum(D.impressions), 0)
    rows = (await session.execute(
        select(
            D.campaign_id, D.target_type, D.target, D.match_type,
            impressions,
            func.coalesce(func.sum(D.budget_consumed), 0.0),
            func.coalesce(func.sum(D.cpm * D.impressions), 0.0),
            func.coalesce(func.sum(D.direct_atc + D.indirect_atc), 0),
            func.coalesce(func.sum(D.direct_sales), 0.0),
            func.coalesce(func.sum(D.indirect_sales), 0.0),
            func.min(D.most_viewed_position),
        )
        .where(*conds)
        .group_by(D.campaign_id, D.target_type, D.target, D.match_type)
    )).all()
    return [
        {
            "campaign_id": cid, "target_type": ttype, "target": target, "match_type": match,
            "impressions": int(impr), "spend": round(float(spend), 2),
            "cpm": round(float(cpm_num) / impr, 2) if impr else None,
            "atc": int(atc), "direct_sales": round(float(ds), 2),
            "indirect_sales": round(float(ind), 2), "sales": round(float(ds) + float(ind), 2),
            "position": pos,
        }
        for cid, ttype, target, match, impr, spend, cpm_num, atc, ds, ind, pos in rows
    ]


async def get_campaign_keywords(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    platform: str,
    campaign_id: str,
    start: date,
    end: date,
    limit: int = 10,
) -> dict:
    """ONE campaign's top keywords by spend, from its own marketplace's per-campaign data —
    the Insights campaign drawer. Raises ValueError for an unknown marketplace (no default
    marketplace, ever) or a non-numeric id where the marketplace's ids are numbers.

    - blinkit: its per-day keyword report summed over the window (all targets — a
      recommendation campaign's rows are its placements), once that history reaches the
      window's start; before then its 8-day detail snapshot on or before `end`, flagged
      `snapshot` with its own dates.
    - zepto: `zepto_ad_campaign_detail` summed over the window (per day, so it follows it).
    - instamart: `instamart_ads.campaign_keywords`, windowed.
    """
    if platform == "blinkit" and await _blinkit_daily_covers(session, tenant_id, start):
        rows = sorted(
            await _blinkit_keyword_daily(
                session, tenant_id=tenant_id, start=start, end=end,
                campaign_id=_numeric_id(platform, campaign_id), keywords_only=False),
            key=lambda r: r["spend"], reverse=True)
        return {
            "platform": platform, "period_start": start, "period_end": end, "snapshot": False,
            "total": len(rows),
            "items": [
                {"keyword": r["target"], "match_type": r["match_type"], "spend": r["spend"],
                 "sales": r["sales"], "impressions": r["impressions"],
                 "roas": round(r["sales"] / r["spend"], 4) if r["spend"] else None,
                 "position": r["position"]}
                for r in rows[:limit]
            ],
        }
    if platform == "blinkit":
        page = await get_keywords(
            session, tenant_id=tenant_id, pagination=Pagination(page=1, limit=limit),
            campaign_id=_numeric_id(platform, campaign_id), marketplaces=["blinkit"],
            as_of=end)
        snap = page.items[0].snapshot_date if page.items else None
        return {
            "platform": platform,
            "snapshot": True,
            "period_start": snap - BLINKIT_SNAPSHOT_SPAN if snap else None,
            "period_end": snap,
            "total": page.total,
            "items": [
                {
                    "keyword": k.target,
                    "match_type": k.match_type,
                    "spend": k.budget_consumed,
                    "sales": round(k.direct_sales + k.indirect_sales, 2),
                    "impressions": k.impressions,
                    "roas": k.total_roas,
                    "position": k.most_viewed_position,
                }
                for k in page.items
            ],
        }
    if platform == zepto_ads.SLUG:
        total, items = await zepto_ads.campaign_keywords(
            session, tenant_id=tenant_id, campaign_id=_numeric_id(platform, campaign_id),
            start=start, end=end, limit=limit)
        return {"platform": platform, "period_start": start, "period_end": end,
                "total": total, "items": items}
    if platform == "instamart":
        rows = await instamart_ads.campaign_keywords(
            session, tenant_id=tenant_id, campaign_id=campaign_id, start=start, end=end,
            limit=limit)
        return {"platform": platform, "period_start": start, "period_end": end,
                "total": len(rows), "items": rows}
    raise ValueError(f"unknown marketplace {platform!r}")


async def get_keyword_insights(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> dict:
    """The Insights keyword table: every campaign × keyword × match type of every
    marketplace in scope, in one shape, plus what period each marketplace's rows cover.

    - blinkit: its per-day keyword report (B6) summed over the window, once that history
      reaches the window's start. Before then: each current campaign's 8-day detail snapshot
      on or before `end` (`snapshot_date − 7 … snapshot_date`), flagged `snapshot` with its
      own dates.
    - zepto: `zepto_ad_campaign_detail` summed over the window.

    - instamart: `instamart_ads.keyword_rows` (campaign-attributed) over the window.

    Fields a marketplace does not report are None, never 0 (Blinkit: clicks, orders; Zepto:
    position, the direct/indirect SALES split; Instamart: match type, position, orders).
    """
    periods: list[dict] = []
    items: list[dict] = []
    if (marketplaces is None or "blinkit" in marketplaces) and await _blinkit_daily_covers(
            session, tenant_id, start):
        periods.append({"platform": "blinkit", "snapshot": False, "start": start, "end": end})
        items += [
            {
                "platform": "blinkit",
                "campaign_id": r["campaign_id"],
                "keyword": r["target"],
                "match_type": r["match_type"],
                "spend": r["spend"],
                "sales": r["sales"],
                "impressions": r["impressions"],
                "atc": r["atc"],
                "direct_sales": r["direct_sales"],
                "indirect_sales": r["indirect_sales"],
                "position": r["position"],
                "cpm": r["cpm"],
            }
            for r in await _blinkit_keyword_daily(
                session, tenant_id=tenant_id, start=start, end=end)
        ]
    elif marketplaces is None or "blinkit" in marketplaces:
        page = await get_keywords(
            session, tenant_id=tenant_id, pagination=Pagination(page=1, limit=10_000),
            marketplaces=["blinkit"], target_type="keyword", recent_only=True, as_of=end)
        snaps = [k.snapshot_date for k in page.items]
        latest = max(snaps) if snaps else None
        periods.append({
            "platform": "blinkit", "snapshot": True,
            "start": latest - BLINKIT_SNAPSHOT_SPAN if latest else None, "end": latest,
        })
        items += [
            {
                "platform": "blinkit",
                "campaign_id": k.campaign_id,
                "keyword": k.target,
                "match_type": k.match_type,
                "spend": k.budget_consumed,
                "sales": round(k.direct_sales + k.indirect_sales, 2),
                "impressions": k.impressions,
                "atc": k.direct_atc + k.indirect_atc,
                "direct_sales": k.direct_sales,
                "indirect_sales": k.indirect_sales,
                "position": k.most_viewed_position,
                "cpm": k.cpm,
                "snapshot_date": k.snapshot_date,
            }
            for k in page.items
        ]
    if zepto_ads.wants_zepto(marketplaces):
        periods.append({"platform": zepto_ads.SLUG, "snapshot": False,
                        "start": start, "end": end})
        items += await zepto_ads.keyword_rows(
            session, tenant_id=tenant_id, start=start, end=end)
    if instamart_ads.wants_instamart(marketplaces):
        periods.append({"platform": "instamart", "snapshot": False,
                        "start": start, "end": end})
        items += await instamart_ads.keyword_rows(
            session, tenant_id=tenant_id, start=start, end=end)
    return {"periods": periods, "items": items}


# Which marketplaces report ad performance by product / retail category / city. Blinkit
# reports none of them (its ad data stops at campaign and keyword — BLINKIT-NOTES B7);
# Instamart reports products only. Mirrored by the frontend's explorer coverage chips.
BREAKDOWN_MARKETPLACES = {"product": ("zepto", "instamart"), "category": ("zepto",),
                          "city": ("zepto",)}


async def get_breakdowns(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    dimension: str,
    marketplaces: list[str] | None = None,
    ad_type: str | None = None,
) -> list[dict]:
    """Ad spend and return per product, retail category or city, for every marketplace in
    scope that reports it — the Insights "Breakdowns" card. Rows carry `platform`, `key`
    (stable per marketplace) and `name`; product rows also `detail` (the retail category)
    and `image_link`.

    `ad_type` is Zepto's ad type (sponsored_products / _brands / _display); it narrows
    Zepto's rows. Each dimension is a separate slicing of the SAME spend, so rows of
    different dimensions must never be added together (they used to share one "All" view).
    """
    if dimension not in BREAKDOWN_MARKETPLACES:
        raise ValueError(f"unknown dimension {dimension!r}")
    out: list[dict] = []
    if zepto_ads.wants_zepto(marketplaces):
        if dimension == "product":
            rows = await zepto_ads.products(
                session, tenant_id=tenant_id, start=start, end=end,
                campaign_category=ad_type)
            out += [
                {**r, "platform": zepto_ads.SLUG, "key": r["product_variant_id"],
                 "name": r["product_name"] or r["product_variant_id"],
                 "detail": r["product_category"]}
                for r in rows
            ]
        else:
            rows = await zepto_ads.breakdown(
                session, tenant_id=tenant_id, start=start, end=end, dimension=dimension,
                campaign_category=ad_type)
            out += [{**r, "platform": zepto_ads.SLUG, "key": r["name"]} for r in rows]
    # Instamart reports products (no ad types, so an ad-type filter leaves it out); its rows
    # carry which campaigns each total is made of.
    if dimension == "product" and not ad_type and instamart_ads.wants_instamart(marketplaces):
        out += [
            {**r, "platform": "instamart", "key": r["product_variant_id"],
             "name": r["product_name"] or r["product_variant_id"], "detail": None,
             # Instamart reports no unit count on the ad side (always 0) — not reported, not 0.
             "units_sold": None}
            for r in await instamart_ads.products(
                session, tenant_id=tenant_id, start=start, end=end)
        ]
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def _numeric_id(platform: str, campaign_id: str) -> int:
    try:
        return int(campaign_id)
    except ValueError:
        raise ValueError(f"{platform} campaign ids are numbers, got {campaign_id!r}") from None


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
