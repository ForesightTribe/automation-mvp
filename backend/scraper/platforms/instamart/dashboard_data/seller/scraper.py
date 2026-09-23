"""Ask the Brand Portal for a Sales report, wait for it, download it.

Three steps, and only the first two are signed:

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
"""
import asyncio
import datetime as dt
import uuid
from pathlib import Path

import httpx

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller.session import (
    PortalError, PortalSession,
)

# The portal's own window: IST midnight-to-midnight, expressed in UTC.
_IST_OFFSET = dt.timedelta(hours=5, minutes=30)


def _interval(date_from: dt.date, date_to: dt.date) -> dict:
    """{start_time, end_time} as the report endpoint wants them: an inclusive
    range of IST days, written as UTC ISO with milliseconds."""
    start = dt.datetime.combine(date_from, dt.time.min) - _IST_OFFSET
    end = dt.datetime.combine(date_to, dt.time.max) - _IST_OFFSET
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
    logger.info(f"Instamart report requested for {date_from}..{date_to}: {name}")
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
    deadline = asyncio.get_event_loop().time() + ep.POLL_TIMEOUT_S
    attempt = 0
    while asyncio.get_event_loop().time() < deadline:
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
                logger.info(f"Instamart report ready after {attempt} poll(s): "
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
    logger.info(f"Instamart report downloaded: {path.name} ({len(r.content):,} B)")
    return path


async def fetch_sales_report(portal: PortalSession, brand_account_id: str,
                             date_from: dt.date, date_to: dt.date,
                             dest_dir: str | Path) -> Path:
    """All three steps: ask, wait, download. Returns the xlsx path."""
    requested_after = dt.datetime.utcnow()
    await request_report(portal, brand_account_id, date_from, date_to)
    report = await await_report(portal, date_from, date_to, requested_after)
    return await download_report(report, dest_dir)
