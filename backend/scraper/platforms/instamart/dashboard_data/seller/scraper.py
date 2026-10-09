"""Brand Portal fetches — HTTP only, every call signed through `PortalSession`.

SALES: ask the portal for a Sales report, wait for it, download it. Three
steps, and only the first two are signed:

    1. POST /api/v1/sales/report   ->  a long-running operation, not the report
    2. POST /api/v1/sales/reports  ->  poll the list until ours is COMPLETED
    3. GET  <downloadUrl>          ->  a presigned S3 link: NO auth, NO signature

Step 3 is why this marketplace is cheap to scrape despite the signing: the file
itself is an ordinary download, so it comes straight to Python.

TIMING. The portal only has data up to YESTERDAY ("Last Refreshed at 10:00 AM
Today"), and ad-side figures reconcile for up to 86 hours. So a daily run asks
for yesterday, and a weekly catch-up re-asks for a trailing window — the upsert
key makes re-loading the same dates harmless.

EXPIRY. Reports are deleted after 24 hours and the presigned link lasts the
same, so a report must be downloaded in the run that asked for it. Nothing is
recoverable later.

ADS: campaigns (lifetime totals), the account-wide daily series, product and
keyword performance per campaign per day, and the product catalogue. Each is a
plain signed POST; their parsers are in parser.py.
"""
import asyncio
import datetime as dt
import uuid
from pathlib import Path

import httpx

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.common import IST_OFFSET, epoch_s
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.session import (
    PortalError, PortalSession,
)


def _interval(date_from: dt.date, date_to: dt.date) -> dict:
    """{start_time, end_time} as the report endpoint wants them: an inclusive
    range of IST days, written as UTC ISO with milliseconds."""
    # The portal's own window: IST midnight-to-midnight, expressed in UTC.
    start = dt.datetime.combine(date_from, dt.time.min) - IST_OFFSET
    end = dt.datetime.combine(date_to, dt.time.max) - IST_OFFSET
    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    return {
        "start_time": start.strftime(fmt)[:-3] + "Z",
        "end_time": end.strftime(fmt)[:-3] + "Z",
    }


def _request_time() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def request_report(portal: PortalSession, brand_account_id: str,
                         date_from: dt.date, date_to: dt.date) -> str:
    """Step 1. Returns the operation name, which embeds the file's timestamp."""
    span = (date_to - date_from).days + 1
    if span > ep.MAX_REPORT_DAYS:
        raise ValueError(
            f"{span} days requested; the portal allows at most "
            f"{ep.MAX_REPORT_DAYS} consecutive days per report."
        )
    body = {
        "account_id": portal.account_id,
        "request_context": {
            "request_id": str(uuid.uuid4()),
            "client_id": ep.DATA_CLIENT_ID,
            "request_time": _request_time(),
        },
        "sales_metrics_query": {
            "dimensions": ep.REPORT_DIMENSIONS,
            "filters": {
                "field_filter": {
                    "comparison_operator": ep.OPERATOR_EQUAL,
                    "key": ep.BRAND_ACCOUNT_FILTER,
                    "values": [{"s_value": brand_account_id}],
                }
            },
            "interval": _interval(date_from, date_to),
            "metrics": ep.REPORT_METRICS,
        },
        # The portal wants BRAND here, not the JWT's USER_POOL_BRAND spelling.
        "user": {**portal.user_block(), "user_pool": "BRAND"},
    }
    data = await portal.signed_post(ep.SALES_REPORT, body)
    name = (data.get("operation") or {}).get("name", "")
    logger.debug(f"Instamart report requested for {date_from}..{date_to}: {name}")
    return name


async def list_reports(portal: PortalSession) -> list[dict]:
    """Step 2 (one page). Newest first."""
    body = {
        "account_id": portal.account_id,
        "pagination": {"offset": "", "size": ep.REPORTS_PAGE_SIZE},
        "request_context": {
            "request_id": str(uuid.uuid4()),
            "client_id": ep.DATA_CLIENT_ID,
            "request_time": _request_time(),
        },
        "user": portal.user_block(),
    }
    return (await portal.signed_post(ep.SALES_REPORTS, body)).get("reports") or []


def _matches(report: dict, date_from: dt.date, date_to: dt.date) -> bool:
    rng = report.get("dateRange") or {}
    start, end = rng.get("startDate") or {}, rng.get("endDate") or {}
    try:
        return (dt.date(start["year"], start["month"], start["day"]) == date_from
                and dt.date(end["year"], end["month"], end["day"]) == date_to)
    except (KeyError, TypeError, ValueError):
        return False


async def await_report(portal: PortalSession, date_from: dt.date, date_to: dt.date,
                       requested_after: dt.datetime) -> dict:
    """Step 2. Poll until the report we asked for is COMPLETED.

    Matched on its date range plus `requestedTime`, because the name is only
    minute-resolution and the client may already hold an older report for the
    same range.
    """
    # Asking and immediately polling wastes a signed call against the throttle.
    await asyncio.sleep(ep.POLL_INITIAL_WAIT_S)
    deadline = asyncio.get_running_loop().time() + ep.POLL_TIMEOUT_S
    attempt = 0
    while asyncio.get_running_loop().time() < deadline:
        attempt += 1
        for report in await list_reports(portal):
            if not _matches(report, date_from, date_to):
                continue
            raw = (report.get("requestedTime") or "").replace("Z", "+00:00")
            try:
                when = dt.datetime.fromisoformat(raw).replace(tzinfo=None)
            except ValueError:
                continue
            if when < requested_after - dt.timedelta(minutes=2):
                continue                      # an older report for the same range
            status = report.get("reportStatus")
            if status == ep.STATUS_COMPLETED and report.get("downloadUrl"):
                logger.debug(f"Instamart report ready after {attempt} poll(s): "
                            f"{report.get('name')}")
                return report
            if status == ep.STATUS_FAILED:
                raise PortalError(f"The portal failed to build the report: {report}")
        await asyncio.sleep(ep.POLL_INTERVAL_S)
    raise PortalError(
        f"Report for {date_from}..{date_to} was not ready within "
        f"{ep.POLL_TIMEOUT_S}s ({attempt} polls)."
    )


async def download_report(report: dict, dest_dir: str | Path) -> Path:
    """Step 3. The presigned S3 link needs no auth and no signature."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{report.get('name', 'IMSales')}.xlsx"
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        r = await http.get(report["downloadUrl"])
    if r.status_code != 200:
        raise PortalError(f"Download failed ({r.status_code}) for {report.get('name')}")
    path.write_bytes(r.content)
    logger.debug(f"Instamart report downloaded: {path.name} ({len(r.content):,} B)")
    return path


async def fetch_sales_report(portal: PortalSession, brand_account_id: str,
                             date_from: dt.date, date_to: dt.date,
                             dest_dir: str | Path) -> Path:
    """All three steps: ask, wait, download. Returns the xlsx path."""
    requested_after = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    await request_report(portal, brand_account_id, date_from, date_to)
    report = await await_report(portal, date_from, date_to, requested_after)
    return await download_report(report, dest_dir)


# ── ads: campaigns ───────────────────────────────────────────────────────────

# CAMPAIGN_SEARCH_FILTER_TYPE_START_TIME/END_TIME narrow the returned
# GMV/impressions/ROI/CTR to that window when present (verified: with the
# filter, one campaign showed GMV 5,610 over a 3-day range; with NO filter,
# the same campaign showed GMV 137,070 -- its true lifetime total). Spend
# (METRIC_TYPE_BUDGET_BURNT) is the one exception: it came back byte-identical
# (16,668.83) both ways -- it is always lifetime-cumulative, filter or not.
# So the filter is deliberately omitted: an unambiguous lifetime read for
# everything, rather than a mix where spend silently ignores the window the
# rest of the row respects.
_CAMPAIGN_METRICS = [
    "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS", "METRIC_TYPE_CTR",
    "METRIC_TYPE_ADD_TO_CART_COUNT", "METRIC_TYPE_CONVERSIONS",
    "METRIC_TYPE_CONVERSION_RATE", "METRIC_TYPE_GMV", "METRIC_TYPE_ROI",
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_BUDGET_BURNT_REALTIME",
]


def _campaigns_body(account_id: str, page_no: int) -> dict:
    return {
        "account_id": account_id,
        "metrics": [{"name": m} for m in _CAMPAIGN_METRICS],
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
        "pagination_context": {"offset": str(page_no), "size": ep.CAMPAIGNS_PAGE_SIZE},
        "sort": {
            "sort_order": "SORT_ORDER_DESC",
            "ads_campaign_attribute": "ADS_CAMPAIGN_ATTRIBUTE_END_DATE",
        },
    }


async def fetch_campaigns(portal: PortalSession, account_id: str) -> list[dict]:
    """All campaigns for this account — LIFETIME totals, no window — paging
    until a page comes back short.

    `pagination_context.offset` on THIS endpoint is a 1-based PAGE NUMBER, not a
    row offset (verified live: sending 0/1/2 returns pages of 50/50/30 = the
    account's real totalCampaigns; the response even echoes back offset+1 each
    time). Incrementing by the page size, as /advertiser/metrics would need,
    jumps straight to "page 50" and returns an empty page after page 1 --
    silently truncating any account with more than one page.
    """
    out: list[dict] = []
    page_no = 0
    while True:
        data = await portal.signed_post(ep.CAMPAIGNS, _campaigns_body(account_id, page_no))
        page = data.get("campaignDetails") or []
        out.extend(page)
        logger.debug(f"Instamart campaigns: page {page_no} -> {len(page)} row(s)")
        if len(page) < ep.CAMPAIGNS_PAGE_SIZE:
            break
        page_no += 1
    return out


# ── ads: account-wide daily series ───────────────────────────────────────────
# The endpoint the portal's own trend chart uses. Unlike /campaigns, spend
# genuinely respects the date filter here: verified live, 8 days summed matched
# the portal's windowed dashboard exactly on GMV, impressions AND spend
# (₹1,04,434.39, 3,08,311, ₹3,04,272 -- all exact). One call covers the whole
# range, so a backfill is a single request, not N.

_ACCOUNT_DAILY_METRICS = [
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS",
    "METRIC_TYPE_CTR", "METRIC_TYPE_ROI", "METRIC_TYPE_CONVERSION_RATE",
    "METRIC_TYPE_GMV", "METRIC_TYPE_CONVERSIONS", "METRIC_TYPE_ADD_TO_CART_COUNT",
]


def _date_filter(start: dt.date, end: dt.date) -> dict:
    return {
        "metric_filter": "METRIC_FILTER_TYPE_DATE",
        "comparison_operator": "COMPARISON_OPERATOR_BETWEEN",
        "values": [
            {"i_value": epoch_s(start)},
            {"i_value": epoch_s(end, end_of_day=True)},
        ],
    }


def _account_daily_body(account_id: str, start: dt.date, end: dt.date) -> dict:
    return {
        "account_id": account_id,
        "advertiser_metrics_queries": [
            {
                "query_id": "GRAPH_QUERY",
                "metrics": [{"name": m} for m in _ACCOUNT_DAILY_METRICS],
                "dimensions": ["DIMENSION_TYPE_DAY"],
                "filters": {
                    "logical_operator": "LOGICAL_OPERATOR_AND",
                    "filters": [_date_filter(start, end)],
                },
                "sort": {"sort_order": "SORT_ORDER_ASC", "dimension": "DIMENSION_TYPE_DAY"},
            }
        ],
    }


async def fetch_account_daily(portal: PortalSession, account_id: str,
                              start: dt.date, end: dt.date) -> list[dict]:
    """Every day's account total in the range, one call."""
    data = await portal.signed_post(
        ep.ADVERTISER_METRICS_BATCH, _account_daily_body(account_id, start, end)
    )
    for q in data.get("getAdvertiserMetricsResponse") or []:
        if q.get("queryId") == "GRAPH_QUERY":
            return q.get("metricsOnDimensionsList") or []
    return []


# ── ads: product / keyword performance ───────────────────────────────────────
# Account-wide, split by DIMENSION_TYPE_AD_CANDIDATE (a product) or
# DIMENSION_TYPE_KEYWORD, each paired with DIMENSION_TYPE_CAMPAIGN and
# DIMENSION_TYPE_DAY. Found by driving the campaign-detail page's own traffic:
# it makes these calls scoped to one campaign; dropping the campaign FILTER
# (keeping campaign as a DIMENSION) widens the totals to the whole account
# while still attributing each row to its campaign.
#
# ⚠️ There is no ad-type (campaign_type) filter or breakdown. The
# METRIC_FILTER_TYPE_CAMPAIGN_TYPE filter was verified live to narrow the
# breakdown once, then — after a session re-login the same day — to NOT
# discriminate at all (ITEM/BANNER/COLLECTION_ADS returned byte-identical
# totals; stored by-type rows triple-counted real spend). Unreliable at the API
# level, so the whole by-type breakdown was removed; `git log` has it if the
# filter becomes reliable again. DIMENSION_TYPE_CAMPAIGN is a dimension, not a
# filter, and reconciles exactly against the unfiltered total (verified live:
# 2-dim spend=15241.69 == 3-dim-with-campaign spend=15241.69), so campaign
# ATTRIBUTION is safe.
#
# `candidate_id` is the same id `sku_snapshots.platform_product_id` carries
# for Instamart (verified: AEYU74I37R is the public scraper's Artisanal
# Sourdough Bread too).

_ASSET_METRICS = [
    "METRIC_TYPE_GMV", "METRIC_TYPE_IMPRESSIONS", "METRIC_TYPE_CLICKS",
    "METRIC_TYPE_BUDGET_BURNT", "METRIC_TYPE_ADD_TO_CART_COUNT",
]
PRODUCT_DIMENSION = "DIMENSION_TYPE_AD_CANDIDATE"
KEYWORD_DIMENSION = "DIMENSION_TYPE_KEYWORD"

# `pagination_context.offset` does not advance past ASSET_PAGE_SIZE on this
# endpoint -- verified live: a 30-day keyword query returned exactly 500 rows
# (silently only ~10 of the 30 days) and offset=500 came back empty. So each
# request covers a window small enough to land under one page. With the
# campaign dimension, keywords run ~59 rows/day on Brik Oven (products ~10):
# 7 days would sit near ~413/500, too close; 4 days keeps real margin (~236).
ASSET_CHUNK_DAYS = 4


def _asset_body(account_id: str, dimension: str, start: dt.date, end: dt.date) -> dict:
    return {
        "account_id": account_id,
        "advertiser_metrics_query": {
            "metrics": [{"name": m} for m in _ASSET_METRICS],
            "dimensions": [dimension, "DIMENSION_TYPE_CAMPAIGN", "DIMENSION_TYPE_DAY"],
            "filters": {"logical_operator": "LOGICAL_OPERATOR_AND",
                        "filters": [_date_filter(start, end)]},
            "pagination_context": {"offset": "0", "size": ep.ASSET_PAGE_SIZE},
        },
    }


def chunk_bounds(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[(chunk_start, chunk_end), ...] covering [start, end], each at most
    ASSET_CHUNK_DAYS wide."""
    bounds: list[tuple[dt.date, dt.date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=ASSET_CHUNK_DAYS - 1), end)
        bounds.append((cur, chunk_end))
        cur = chunk_end + dt.timedelta(days=1)
    return bounds


async def _fetch_assets(portal: PortalSession, account_id: str, dimension: str,
                        start: dt.date, end: dt.date) -> list[dict]:
    out: list[dict] = []
    for chunk_start, chunk_end in chunk_bounds(start, end):
        data = await portal.signed_post(
            ep.ADVERTISER_METRICS, _asset_body(account_id, dimension, chunk_start, chunk_end)
        )
        page = data.get("metricsOnDimensionsList") or []
        logger.debug(f"Instamart {dimension} {chunk_start}..{chunk_end}: {len(page)} row(s)")
        if len(page) >= ep.ASSET_PAGE_SIZE:
            logger.warning(
                f"Instamart {dimension} {chunk_start}..{chunk_end}: hit the "
                f"{ep.ASSET_PAGE_SIZE}-row cap -- some rows in this window were "
                f"dropped. Narrow ASSET_CHUNK_DAYS if this keeps happening."
            )
        out.extend(page)
    return out


async def fetch_products_daily(portal: PortalSession, account_id: str,
                               start: dt.date, end: dt.date) -> list[dict]:
    return await _fetch_assets(portal, account_id, PRODUCT_DIMENSION, start, end)


async def fetch_keywords_daily(portal: PortalSession, account_id: str,
                               start: dt.date, end: dt.date) -> list[dict]:
    return await _fetch_assets(portal, account_id, KEYWORD_DIMENSION, start, end)


# ── ads: product catalogue ───────────────────────────────────────────────────

async def fetch_product_catalog(portal: PortalSession, candidate_ids: list[str]) -> list[dict]:
    """Product name + image for a set of candidate ids (the request carries no
    account id)."""
    body = {
        "request_context": {
            "request_id": str(uuid.uuid4()),
            "request_time": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "client_id": ep.DATA_CLIENT_ID,
        },
        "ids": candidate_ids,
    }
    data = await portal.signed_post(ep.PRODUCTS_BATCH, body)
    return data.get("products") or []
