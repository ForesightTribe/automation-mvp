"""Overview-page aggregations that span both data planes. The marketplace
breakdown reuses the per-window aggregate helpers from analytics_service, scoping
each metric to a single marketplace."""
import uuid
from datetime import date, timedelta

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoGRN, ZeptoPO
from app.models.blinkit_seller import (
    BlinkitSOH,
    BlinkitPO,
    BlinkitScorecardKeySku,
    BlinkitScorecardWeekly,
)
from app.models.job import JobStatus, ScrapeJob
from app.models.search import SkuSnapshot
from app.utils.time import now_ist
from app.services import analytics_service, reference_service, watchlist_service
from app.services.analytics_service import (
    _ads_agg,
    _market_agg,
    _metric,
    _roas,
    _sales_agg,
)

async def _tenant_marketplace_data(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> set[str]:
    """Every platform THIS tenant has at least one successful scrape for.

    `reference_service.list_marketplaces` answers a different, global question
    ("does anyone have data for this marketplace") — deliberately, since
    `/reference/marketplaces` isn't client-scoped. Overview needs the narrower,
    tenant-scoped answer: Brik Oven has Zepto rows, Dobra does not, and Dobra's
    breakdown must not claim Zepto is connected just because some other tenant's
    data exists.

    Reads `scrape_jobs`, not `search_snapshots` — a `data_scope="full"`
    marketplace's revenue/RoAS numbers come from the PRIVATE plane (Blinkit's
    seller-panel jobs), which never touches `search_snapshots` at all. Checking
    the public-only table would flip Blinkit to "not connected" the moment its
    public keyword scrape lagged, hiding real revenue that was never actually
    missing. `scrape_jobs` is written by both planes (see `loader.py` for the
    public side, `scraper/utils/jobs.py` for the private side), so this is the
    one signal that's correct for every `data_scope`.

    One query for every marketplace, not one per marketplace — see
    `get_marketplace_breakdown`.
    """
    rows = (
        await session.execute(
            select(ScrapeJob.platform)
            .where(
                ScrapeJob.tenant_id == tenant_id,
                ScrapeJob.status == JobStatus.success,
            )
            .distinct()
        )
    ).scalars().all()
    return set(rows)


async def _marketplace_metrics(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    data_scope: str,
    own_brands: list[str],
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> dict:
    """The metric set for a single (connected) marketplace, current vs previous
    window. `marketplaces=[slug]` scopes both the private (platform) and public
    (mp_slug) queries to just this marketplace.

    `data_scope == "public"` means there is no seller-panel integration for this
    marketplace — revenue/ad spend/RoAS/units sold are not just zero, they are
    structurally unavailable (no order or ads feed exists to compute them from).
    Those keys are omitted entirely rather than sent as zero, so the UI can tell
    "not tracked here" apart from "tracked, and happens to be zero."
    """
    mp = [slug]
    sov, rank = await _market_agg(
        session, own_brands=own_brands, start=start, end=end, marketplaces=mp
    )
    p_sov, p_rank = await _market_agg(
        session,
        own_brands=own_brands,
        start=prev_start,
        end=prev_end,
        marketplaces=mp,
    )
    metrics = {
        "visibility": _metric(sov, p_sov),
        "avg_rank": _metric(rank, p_rank),
    }
    if data_scope != "full":
        return metrics

    rev, units, _ = await _sales_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=mp
    )
    p_rev, p_units, _ = await _sales_agg(
        session, tenant_id=tenant_id, start=prev_start, end=prev_end, marketplaces=mp
    )
    spend, _, ad_sales = await _ads_agg(
        session, tenant_id=tenant_id, start=start, end=end, marketplaces=mp
    )
    p_spend, _, p_ad_sales = await _ads_agg(
        session, tenant_id=tenant_id, start=prev_start, end=prev_end, marketplaces=mp
    )
    organic = None if rev is None or ad_sales is None else max(0.0, rev - ad_sales)
    p_organic = (
        None if p_rev is None or p_ad_sales is None else max(0.0, p_rev - p_ad_sales)
    )
    metrics.update(
        revenue=_metric(rev, p_rev),
        roas=_metric(_roas(ad_sales, spend), _roas(p_ad_sales, p_spend)),
        ad_spend=_metric(spend, p_spend),
        ad_sales=_metric(ad_sales, p_ad_sales),
        organic_revenue=_metric(organic, p_organic),
        units_sold=_metric(units, p_units),
    )
    return metrics


async def get_marketplace_breakdown(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> list[dict]:
    """One row per marketplace. Marketplaces THIS tenant has real data for carry
    metrics; the rest are returned bare (connected=False, metrics None) so the UI
    can show them as 'coming soon' without faking data.

    `mp["connected"]` (from reference_service) is a global signal — some tenant,
    somewhere, has data for this marketplace. It is ANDed with a tenant-scoped
    check here, because a marketplace can be globally real (Zepto has data for
    Brik Oven) while this specific tenant has none (Dobra) — that tenant must
    still see 'coming soon', not a blank metrics grid.
    """
    marketplaces = await reference_service.list_marketplaces(session)
    own = await watchlist_service.get_brands_by_relationship(
        session, tenant_id, "own"
    )
    tenant_platforms = await _tenant_marketplace_data(session, tenant_id=tenant_id)

    rows: list[dict] = []
    for mp in marketplaces:
        connected = mp["connected"] and mp["slug"] in tenant_platforms
        row = {
            "slug": mp["slug"],
            "name": mp["name"],
            "color": mp["color"],
            "connected": connected,
            "data_scope": mp["data_scope"],
        }
        if connected:
            row.update(
                await _marketplace_metrics(
                    session,
                    tenant_id=tenant_id,
                    slug=mp["slug"],
                    data_scope=mp["data_scope"],
                    own_brands=own,
                    start=start,
                    end=end,
                    prev_start=prev_start,
                    prev_end=prev_end,
                )
            )
        rows.append(row)
    return rows


async def get_marketplace_trends(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    marketplaces: list[str] | None = None,
) -> list[dict]:
    """Daily revenue per connected marketplace, one series each.

    Built by asking `get_trends` once per marketplace rather than grouping a
    query by platform: revenue for the three marketplaces comes from three
    different tables, and that merge already lives in `get_trends`. One HTTP
    request either way — the fan-out is here, not in the browser.

    Only `data_scope == "full"` marketplaces appear. A public-only marketplace
    has no order feed, so its series would be a flat line at zero rather than a
    channel that sold nothing.
    """
    all_marketplaces = await reference_service.list_marketplaces(session)
    tenant_platforms = await _tenant_marketplace_data(session, tenant_id=tenant_id)

    out: list[dict] = []
    for mp in all_marketplaces:
        if mp["data_scope"] != "full" or not (
            mp["connected"] and mp["slug"] in tenant_platforms
        ):
            continue
        if marketplaces is not None and mp["slug"] not in marketplaces:
            continue
        rows = await analytics_service.get_trends(
            session,
            tenant_id=tenant_id,
            start=start,
            end=end,
            marketplaces=[mp["slug"]],
        )
        out.append(
            {
                "slug": mp["slug"],
                "name": mp["name"],
                "color": mp["color"],
                "points": [
                    {"date": r["date"], "revenue": r["revenue"]} for r in rows
                ],
            }
        )
    return out




async def get_freshness(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """Latest scrape per dashboard (DISTINCT ON dashboard, newest first), with
    its age — for the 'synced Xh ago' chips."""
    rows = (
        await session.execute(
            select(ScrapeJob)
            .where(ScrapeJob.tenant_id == tenant_id)
            .order_by(ScrapeJob.dashboard, ScrapeJob.created_at.desc())
            .distinct(ScrapeJob.dashboard)
        )
    ).scalars().all()

    now = now_ist()
    out = []
    for j in rows:
        ts = j.completed_at or j.started_at or j.created_at
        age = round((now - ts).total_seconds() / 3600, 1) if ts else None
        out.append(
            {
                "dashboard": j.dashboard,
                "platform": j.platform,
                # .value, not the enum: str(JobStatus.running) renders as
                # "JobStatus.running" and no consumer matches on that.
                "status": getattr(j.status, "value", j.status),
                "last_synced_at": ts,
                "age_hours": age,
            }
        )
    return out


