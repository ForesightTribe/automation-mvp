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
from app.services import reference_service, watchlist_service
from app.services.analytics_service import (
    _ads_agg,
    _market_agg,
    _metric,
    _roas,
    _sales_agg,
)

# Severity sort order for the attention feed (lower = more urgent).
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


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
    metrics.update(
        revenue=_metric(rev, p_rev),
        roas=_metric(_roas(ad_sales, spend), _roas(p_ad_sales, p_spend)),
        ad_spend=_metric(spend, p_spend),
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


def _month_spine(months: int) -> list[str]:
    """Last `months` months as 'YYYY-MM', oldest first (includes current month)."""
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


async def get_monthly_trends(
    session: AsyncSession, *, tenant_id: uuid.UUID, months: int = 3
) -> list[dict]:
    """Month-on-month operations trends for the Overview: OSA % (SOH), fill rate %
    (scorecard), and PO value. Aligned on a month spine; None where a source has
    no data that month. Tenant-wide (not day-range / marketplace scoped)."""
    spine = _month_spine(months)
    start = date(int(spine[0][:4]), int(spine[0][5:7]), 1)

    # OSA: per-day in-stock ratio from SOH, then averaged per month.
    soh_rows = (
        await session.execute(
            select(
                BlinkitSOH.date,
                func.count(distinct(BlinkitSOH.item_id)),
                func.count(distinct(BlinkitSOH.item_id)).filter(
                    BlinkitSOH.frontend_inv_qty > 0
                ),
            )
            .where(BlinkitSOH.tenant_id == tenant_id, BlinkitSOH.date >= start)
            .group_by(BlinkitSOH.date)
        )
    ).all()
    osa_by_month: dict[str, list[float]] = {}
    for d, total, in_stock in soh_rows:
        if total:
            osa_by_month.setdefault(d.strftime("%Y-%m"), []).append(
                in_stock / total * 100
            )
    osa_map = {k: sum(v) / len(v) for k, v in osa_by_month.items() if v}

    # Fill rate: weekly scorecard, averaged per month.
    sc_rows = (
        await session.execute(
            select(
                BlinkitScorecardWeekly.from_date_ist,
                BlinkitScorecardWeekly.overall,
            ).where(
                BlinkitScorecardWeekly.tenant_id == tenant_id,
                BlinkitScorecardWeekly.from_date_ist >= start,
            )
        )
    ).all()
    fr_by_month: dict[str, list[float]] = {}
    for fdate, overall in sc_rows:
        fr = (overall or {}).get("fill_rate")
        if fr is not None:
            fr_by_month.setdefault(fdate.strftime("%Y-%m"), []).append(float(fr))
    fr_map = {k: sum(v) / len(v) for k, v in fr_by_month.items() if v}

    # PO: total amount + count per issue-date month.
    po_month = func.to_char(func.date_trunc("month", BlinkitPO.issue_date), "YYYY-MM")
    po_rows = (
        await session.execute(
            select(
                po_month,
                func.coalesce(func.sum(BlinkitPO.total_po_amount), 0.0),
                func.count(),
            )
            .where(BlinkitPO.tenant_id == tenant_id, BlinkitPO.issue_date >= start)
            .group_by(po_month)
        )
    ).all()
    po_map = {m: (float(amt), int(cnt)) for m, amt, cnt in po_rows}

    # ── Zepto: on-shelf availability ─────────────────────────────────────────
    # Different plane from the Blinkit figure above, and worth being explicit
    # about: `blinkit_soh` is warehouse stock the platform reports to us, while
    # this counts SHELVES across 163 stores that we scraped ourselves. Both
    # answer "is it available", but Blinkit's is a supplier-side view and this is
    # a shopper-side one, so the two are not strictly comparable in one chart.
    #
    # Raw SQL because it needs DISTINCT ON (product, store) — one row per shelf,
    # newest first — which is the same rule every Inventory read uses. Counting
    # raw rows would inflate any day scraped twice (26-Aug was, by ~45%).
    osa_rows = (
        await session.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (scraped_at::date, platform_product_id, merchant_id)
                           scraped_at::date AS d, in_stock
                    FROM sku_snapshots
                    WHERE mp_slug = 'zepto'
                      AND tenant_id = :tid
                      AND merchant_id <> ''
                      AND scraped_at >= :start
                    ORDER BY scraped_at::date, platform_product_id, merchant_id,
                             scraped_at DESC
                ),
                daily AS (
                    SELECT d,
                           100.0 * count(*) FILTER (WHERE in_stock) / count(*) AS pct
                    FROM latest GROUP BY d
                )
                SELECT to_char(d, 'YYYY-MM') AS ym, avg(pct) AS osa
                FROM daily GROUP BY 1
                """
            ),
            {"tid": tenant_id, "start": start},
        )
    ).all()
    for ym, pct in osa_rows:
        if pct is None:
            continue
        # Average with Blinkit's when a tenant has both, same as fill rate.
        osa_map[ym] = (osa_map[ym] + float(pct)) / 2 if ym in osa_map else float(pct)

    # ── Zepto ────────────────────────────────────────────────────────────────
    # Zepto publishes no seller scorecard, so its fill rate is computed from the
    # GRN rows, where ordered and received sit on the same row. That is the same
    # quantity Blinkit's scorecard reports, arrived at from the raw receipts
    # instead of the platform's own summary.
    #
    # NOT read from `zepto_po.total_grn_qty`: Zepto returns that null on every PO
    # header (verified 2026-08-27, 74 POs), so the field exists but never fills.
    #
    # This function is tenant-wide and ignores the marketplace picker, so for a
    # client on BOTH platforms these merge into one bar. Quantities are summed
    # before dividing rather than averaging two percentages — a weighted figure
    # is the honest one, but the combined bar is still a blend of two different
    # supply relationships. Revisit if a dual-platform client appears.
    # Bound once and reused: building the same expression twice emits different
    # bind parameters, and Postgres then rejects the GROUP BY as not matching.
    grn_month = func.to_char(func.date_trunc("month", ZeptoGRN.grn_date), "YYYY-MM")
    z_grn = (
        await session.execute(
            select(
                grn_month,
                func.coalesce(func.sum(ZeptoGRN.po_qty), 0),
                func.coalesce(func.sum(ZeptoGRN.grn_qty), 0),
            )
            .where(
                ZeptoGRN.tenant_id == tenant_id,
                ZeptoGRN.grn_date >= start,
                ZeptoGRN.po_qty > 0,
            )
            .group_by(grn_month)
        )
    ).all()
    for month, ordered, received in z_grn:
        if not ordered:
            continue
        pct = 100.0 * float(received) / float(ordered)
        # Average with Blinkit's if both exist; otherwise Zepto stands alone.
        fr_map[month] = (fr_map[month] + pct) / 2 if month in fr_map else pct

    zpo_month = func.to_char(func.date_trunc("month", ZeptoPO.po_date), "YYYY-MM")
    z_po = (
        await session.execute(
            select(
                zpo_month,
                func.coalesce(func.sum(ZeptoPO.total_value), 0.0),
                func.count(),
            )
            .where(ZeptoPO.tenant_id == tenant_id, ZeptoPO.po_date >= start)
            .group_by(zpo_month)
        )
    ).all()
    for month, amount, count in z_po:
        prev = po_map.get(month, (0.0, 0))
        po_map[month] = (prev[0] + float(amount), prev[1] + int(count))

    out = []
    for ym in spine:
        po = po_map.get(ym)
        out.append(
            {
                "month": ym,
                "osa_pct": round(osa_map[ym], 1) if ym in osa_map else None,
                "fill_rate": round(fr_map[ym], 1) if ym in fr_map else None,
                "po_amount": round(po[0], 2) if po else None,
                "po_count": po[1] if po else None,
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
                "status": j.status,
                "last_synced_at": ts,
                "age_hours": age,
            }
        )
    return out


async def get_alerts(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[dict]:
    """Attention feed: scrape failures, out-of-stock, and fill-loss signals.
    Each generator contributes only when there's something to report, so an
    empty list legitimately means 'all clear'."""
    alerts: list[dict] = []

    # 1. Recent scrape failures.
    failed = (
        await session.execute(
            select(ScrapeJob.dashboard, ScrapeJob.error)
            .where(ScrapeJob.tenant_id == tenant_id, ScrapeJob.status == "failed")
            .order_by(ScrapeJob.created_at.desc())
            .limit(5)
        )
    ).all()
    for dashboard, error in failed:
        alerts.append(
            {
                "severity": "critical",
                "category": "scrape",
                "title": f"{dashboard} scrape failed",
                "detail": (error or "").strip()[:160] or None,
            }
        )

    # 2. Out-of-stock SKUs on the latest stock snapshot.
    latest_soh = (
        await session.execute(
            select(func.max(BlinkitSOH.date)).where(
                BlinkitSOH.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if latest_soh:
        oos = (
            await session.execute(
                select(func.count(distinct(BlinkitSOH.item_id))).where(
                    BlinkitSOH.tenant_id == tenant_id,
                    BlinkitSOH.date == latest_soh,
                    BlinkitSOH.frontend_inv_qty == 0,
                )
            )
        ).scalar_one()
        if oos:
            alerts.append(
                {
                    "severity": "warning",
                    "category": "stock",
                    "title": f"{oos} SKU(s) out of stock (front-end)",
                    "detail": f"As of the {latest_soh} stock snapshot.",
                }
            )

    # 3. Potential fill loss on the latest scorecard week.
    latest_week = (
        await session.execute(
            select(func.max(BlinkitScorecardKeySku.from_date_ist)).where(
                BlinkitScorecardKeySku.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if latest_week:
        loss_sum, loss_count = (
            await session.execute(
                select(
                    func.coalesce(func.sum(BlinkitScorecardKeySku.potential_loss), 0.0),
                    func.count(),
                ).where(
                    BlinkitScorecardKeySku.tenant_id == tenant_id,
                    BlinkitScorecardKeySku.from_date_ist == latest_week,
                    BlinkitScorecardKeySku.potential_loss > 0,
                )
            )
        ).one()
        if loss_count:
            alerts.append(
                {
                    "severity": "warning",
                    "category": "fill",
                    "title": f"₹{int(loss_sum):,} potential fill loss",
                    "detail": f"Across {loss_count} key SKU(s), week of {latest_week}.",
                }
            )

    # 4. Own-brand SKUs out of stock on the public shelf (from sku_snapshots).
    # Window is ~8 days to reliably catch the latest weekly/on-demand scrape.
    own = await watchlist_service.get_brands_by_relationship(
        session, tenant_id, "own"
    )
    if own:
        since = now_ist() - timedelta(days=8)
        shelf_oos = (
            await session.execute(
                select(func.count(distinct(SkuSnapshot.platform_product_id))).where(
                    SkuSnapshot.tenant_id == tenant_id,
                    SkuSnapshot.brand_slug.in_(own),
                    SkuSnapshot.scraped_at >= since,
                    SkuSnapshot.in_stock.is_(False),
                )
            )
        ).scalar_one()
        if shelf_oos:
            alerts.append(
                {
                    "severity": "warning",
                    "category": "visibility",
                    "title": f"{shelf_oos} SKU(s) out of stock on shelf",
                    "detail": "Own-brand SKUs marked unavailable in the latest public scrape.",
                }
            )

    alerts.sort(key=lambda a: _SEVERITY_ORDER.get(a["severity"], 9))
    return alerts
