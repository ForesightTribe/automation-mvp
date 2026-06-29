"""Marketing / advertising data for a client (paid activity on the platform).

Metrics come from the per-campaign daily backbone (`BlinkitAdCampaignDaily`);
`BlinkitAdCampaign` supplies campaign metadata and `BlinkitAdCampaignDetail` the
keyword/asset breakdown. RoAS is always recomputed as ad_sales / spend over the
window (never an average of daily ratios). All queries are `tenant_id`-scoped and
optionally filtered to a set of marketplaces via the `platform` column (None =
every platform — today only Blinkit has ad data)."""
import uuid
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services import reference_service
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
    return (
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
            "name": c.name,
            "type": c.type,
            "status": c.status,
            **metrics.get(c.campaign_id, zeros),
        }
        for c in campaigns
    ]

    # Campaign count per client is small -> rank + paginate in memory.
    sort_key = _CAMPAIGN_SORTS.get(sort, "budget_consumed")
    rows.sort(key=lambda r: r[sort_key], reverse=(order != "asc"))
    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [CampaignRow.model_validate(r) for r in page]
    return Page.build(items, total, pagination)


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
    return [
        {
            "date": d,
            "budget_consumed": round(float(b), 2),
            "impressions": int(i),
            "ad_sales": round(float(s), 2),
            "roas": _roas(float(s), float(b)),
        }
        for d, b, i, s in rows
    ]


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
) -> Page[KeywordRow]:
    """Keyword / asset performance from the latest detail snapshot per campaign.

    `BlinkitAdCampaignDetail` is a range-aggregate snapshot (not daily), so we keep
    only each campaign's most recent `snapshot_date` rather than summing across
    snapshots."""
    conds = [Detail.tenant_id == tenant_id]
    if campaign_id is not None:
        conds.append(Detail.campaign_id == campaign_id)
    if marketplaces is not None:
        conds.append(Detail.platform.in_(marketplaces))
    if target_type:
        conds.append(Detail.target_type == target_type)
    rows = (
        await session.execute(select(Detail).where(*conds))
    ).scalars().all()

    # Keep only the latest snapshot per campaign.
    latest: dict[int, date] = {}
    for r in rows:
        if r.campaign_id not in latest or r.snapshot_date > latest[r.campaign_id]:
            latest[r.campaign_id] = r.snapshot_date
    rows = [r for r in rows if r.snapshot_date == latest[r.campaign_id]]

    sort_funcs = {
        "spend": lambda r: r.budget_consumed,
        "roas": lambda r: r.total_roas,
        "sales": lambda r: r.direct_sales + r.indirect_sales,
        "impressions": lambda r: r.impressions,
    }
    rows.sort(key=sort_funcs.get(sort, sort_funcs["spend"]), reverse=(order != "asc"))

    total = len(rows)
    page = rows[pagination.offset : pagination.offset + pagination.limit]
    items = [KeywordRow.model_validate(r) for r in page]
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
