"""Instamart ad campaigns — `POST /api/v1/campaigns` on the same signed data
host and session as the sales report (see `session.py`). One call returns
campaign identity and metrics together, LIFETIME-to-date: the response's only
per-day dimension carries a single uptime-efficiency figure, nothing resembling
a daily GMV/spend/impressions series. So there is no daily table here, and no
window filtering — `fetch_campaigns` returns every campaign the account has,
as of the moment scraped. See `app/models/instamart_ads.py`.

Captured live 2026-09-24 against Brik Oven; verified the existing sales signer
(app_version 1.4.136) authenticates this endpoint too — same key, no new
signing work, even though the live portal itself was observed on 1.4.137.
"""
import uuid
from datetime import datetime, timezone

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.session import PortalSession

# CAMPAIGN_SEARCH_FILTER_TYPE_START_TIME/END_TIME narrow the returned
# GMV/impressions/ROI/CTR to that window when present (verified: with the
# filter, one campaign showed GMV 5,610 over a 3-day range; with NO filter,
# the same campaign showed GMV 137,070 -- its true lifetime total). Spend
# (METRIC_TYPE_BUDGET_BURNT) is the one exception: it came back byte-identical
# (16,668.83) both ways -- it is always lifetime-cumulative, filter or not.
# This module deliberately omits the filter and takes the unambiguous
# lifetime read for everything, rather than a mix where spend silently
# ignores whatever window the rest of the row respects.
PAGE_SIZE = 50

_REQUESTED_METRICS = [
    "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS", "METRIC_TYPE_CTR",
    "METRIC_TYPE_ADD_TO_CART_COUNT", "METRIC_TYPE_CONVERSIONS",
    "METRIC_TYPE_CONVERSION_RATE", "METRIC_TYPE_GMV", "METRIC_TYPE_ROI",
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_BUDGET_BURNT_REALTIME",
]


def _body(account_id: str, offset: int) -> dict:
    return {
        "account_id": account_id,
        "metrics": [{"name": m} for m in _REQUESTED_METRICS],
        "filters": {
            "logical_operator": "LOGICAL_OPERATOR_AND",
            "filters": [
                {
                    "campaign_search_filter": "CAMPAIGN_SEARCH_FILTER_TYPE_ACCOUNT_ID",
                    "comparison_operator": "COMPARISON_OPERATOR_EQUAL",
                    "values": [{"s_value": account_id}],
                },
            ],
        },
        "pagination_context": {"offset": str(offset), "size": PAGE_SIZE},
        "sort": {
            "sort_order": "SORT_ORDER_DESC",
            "ads_campaign_attribute": "ADS_CAMPAIGN_ATTRIBUTE_END_DATE",
        },
    }


async def fetch_campaigns(portal: PortalSession, account_id: str) -> list[dict]:
    """All campaigns for this account, paging until a page comes back short.

    `pagination_context.offset` on THIS endpoint is a 1-based PAGE NUMBER, not a
    row offset (verified live: sending 0/1/2 returns pages of 50/50/30 = the
    account's real totalCampaigns; the response even echoes back offset+1 each
    time). Incrementing by PAGE_SIZE, as the sibling advertiser/metrics endpoint
    needs, instead jumps straight to "page 50" and returns an empty page after
    page 1 -- silently truncating any account with more than one page.
    """
    out: list[dict] = []
    page_no = 0
    while True:
        data = await portal.signed_post(ep.CAMPAIGNS, _body(account_id, page_no))
        page = data.get("campaignDetails") or []
        out.extend(page)
        logger.info(f"Instamart campaigns: page {page_no} -> {len(page)} row(s)")
        if len(page) < PAGE_SIZE:
            break
        page_no += 1
    return out


def _money(m: dict | None) -> float | None:
    if not m:
        return None
    return float(m.get("units") or 0) + float(m.get("nanos") or 0) / 1e9


def _metrics_map(advertiser_metrics: dict) -> dict:
    """The LIFETIME rollup is the entry whose dimensions are JUST the campaign —
    every other entry adds a DAY (or other) dimension on top of it."""
    for grp in advertiser_metrics.get("metricsOnDimensionsList") or []:
        dims = grp.get("dimensions") or []
        if len(dims) == 1 and dims[0].get("name") == "DIMENSION_TYPE_CAMPAIGN":
            return {m["name"]: m.get("value") for m in grp.get("metrics") or []}
    return {}


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_campaigns(raw: list[dict]) -> list[dict]:
    """One dict per campaign, shaped for `InstamartAdCampaign`."""
    out: list[dict] = []
    for entry in raw:
        c = entry.get("campaign") or {}
        cid = c.get("id")
        if not cid:
            continue
        metrics = _metrics_map(entry.get("advertiserMetrics") or {})
        budget_obj = c.get("budget") or {}
        budget_type = budget_obj.get("budgetType")
        ad_type = entry.get("adType") or {}
        out.append({
            "campaign_id": cid,
            "name": c.get("name"),
            "status": c.get("status"),
            "campaign_type": ad_type.get("type") or c.get("type"),
            "placements": ",".join(ad_type.get("placements") or []) or None,
            "start_time": _parse_time(c.get("startTime")),
            "end_time": _parse_time(c.get("endTime")),
            "budget_type": budget_type,
            # `totalBudget` is only a PER-DAY figure when budgetType says so.
            # Every campaign observed with budgetType INVALID (119 of 130 on
            # the real account -- all legacy/stopped) has a totalBudget that
            # is clearly a LIFETIME spend cap instead (Sourdough Bread showed
            # 220,000, KBA_MAY25 showed 121,000 -- not plausible as "per
            # day"). Storing it as daily_budget there would wreck Budget
            # utilisation % (spend / (daily_budget * days)) the moment such a
            # campaign falls inside the selected window. None here matches
            # the UI's existing "not reported" fallback for a missing value.
            "daily_budget": _money(budget_obj.get("totalBudget"))
                if budget_type == "BUDGET_TYPE_DAILY" else None,
            "spend": metrics.get("METRIC_TYPE_BUDGET_BURNT")
                or metrics.get("METRIC_TYPE_BUDGET_BURNT_REALTIME") or 0.0,
            "gmv": metrics.get("METRIC_TYPE_GMV") or 0.0,
            "impressions": int(metrics.get("METRIC_TYPE_IMPRESSIONS") or 0),
            "clicks": int(metrics.get("METRIC_TYPE_CLICKS") or 0),
            "ctr": metrics.get("METRIC_TYPE_CTR"),
            "add_to_cart_count": int(metrics.get("METRIC_TYPE_ADD_TO_CART_COUNT") or 0),
            "conversions": int(metrics.get("METRIC_TYPE_CONVERSIONS") or 0),
            "conversion_rate": metrics.get("METRIC_TYPE_CONVERSION_RATE"),
            "roi": metrics.get("METRIC_TYPE_ROI"),
        })
    return out


async def save_campaigns(
    session, tenant_id: str, rows: list[dict], scrape_job_id: uuid.UUID | None = None
) -> int:
    from sqlalchemy.dialects.postgresql import insert

    from app.models import InstamartAdCampaign
    from app.utils.time import now_ist

    if not rows:
        return 0
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()
    for r in rows:
        r["tenant_id"] = tid
        r["platform"] = "instamart"
        r["scrape_job_id"] = scrape_job_id
        r["scraped_at"] = stamped
        r["upsert_key"] = f"instamart|{tid}|{r['campaign_id']}"

    update_cols = [
        c.name for c in InstamartAdCampaign.__table__.columns
        if c.name not in {"id", "upsert_key"}
    ]
    stmt = (
        insert(InstamartAdCampaign)
        .values(rows)
        .on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: insert(InstamartAdCampaign).excluded[c] for c in update_cols},
        )
    )
    await session.execute(stmt)
    logger.info(f"Instamart campaigns saved: {len(rows)} row(s)")
    return len(rows)
