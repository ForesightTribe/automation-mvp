"""Live calls against the Supply Portal's three confirmed endpoints (see
`endpoints.py`'s module docstring for the captured request/response shapes).

Plain httpx, no browser needed per call (session.py handles minting the
token once). No throttling was observed during investigation, unlike the
Brand Portal's near-constant 403s — but that is what was SEEN, not a
documented guarantee, so a short backoff-and-retry still guards every call
here rather than assuming it can never happen.
"""
import asyncio

import httpx

from app.utils.logger import logger
from scraper.platforms.instamart.dashboard_data.supply import endpoints as ep

RETRY_WAITS_S = (5, 15, 30)
PAGE_SIZE = 100
# Verified live 2026-09-25: 5 CONCURRENT listPurchaseOrderLines calls got an
# immediate raw-HTML 403 on every one of them (an edge/WAF burst block, not
# an app-level rejection -- searchPurchaseOrder took zero retries across 22
# pages moments earlier). Sequential with a floor between calls avoided it.
LINE_ITEM_CONCURRENCY = 1
LINE_ITEM_GAP_S = 0.3

# ── searchPurchaseOrder pagination is NON-DETERMINISTIC (verified live
# 2026-09-28) ────────────────────────────────────────────────────────────────
# The endpoint honours NO sort key — passing sort_by=created_at (or any other
# field) returns rows in an undefined, unstable order, so page N is not a fixed
# slice: across a full 22-page sweep, ~27% of rows come back as duplicates of a
# PO already seen on an earlier page, and the same count of DISTINCT POs never
# appear on ANY page. The total record count stays rock-stable (2133 on every
# page, unchanged for the whole sweep), so this is not live data mutating under
# us — it is the server slicing an unordered set differently each request.
#
# A single sweep therefore silently drops ~25% of POs. The fix is to sweep
# REPEATEDLY with a rotating sort hint and UNION the results by id: each sweep
# returns a different ~75-95% random subset, so the union converges on the full
# set fast. Measured live: 4 sweeps -> 2133/2133, zero missing. The rotation
# order below is the one that converged fastest in that test (pending_qty alone
# already yields ~96% in one sweep).
SORT_ROTATION = ("pending_qty", "created_at", "purchase_order_id",
                 "expiry_date", None, "po_date", "id")
MAX_SWEEPS = 10          # safety cap; convergence is typically 4
STALL_LIMIT = 2          # consecutive sweeps adding zero new POs -> give up early


class SupplyFetchError(RuntimeError):
    """A Supply Portal call failed after retries."""


async def _post(client: httpx.AsyncClient, token: str, path: str, body: dict) -> dict:
    """Retries on a 403/429 status AND on a network-level failure (timeout,
    reset connection, DNS blip) — verified live 2026-09-25: a lone
    httpx.ReadError mid-way through a 2122-call sequential run killed the
    whole batch because only HTTP status codes were being retried."""
    headers = {"abacus-token": token, "content-type": "application/json"}
    last = ""
    for attempt in range(1, len(RETRY_WAITS_S) + 2):
        try:
            r = await client.post(ep.DATA + path, headers=headers, json=body)
        except httpx.TransportError as e:
            last = f"transport error: {e}"
            if attempt <= len(RETRY_WAITS_S):
                wait = RETRY_WAITS_S[attempt - 1]
                logger.warning(f"{path} -> {last}; waiting {wait}s and retrying ({attempt}/{len(RETRY_WAITS_S)})")
                await asyncio.sleep(wait)
                continue
            break
        if r.status_code == 200:
            return r.json()
        last = f"{r.status_code}: {r.text[:200]}"
        if r.status_code in (403, 429) and attempt <= len(RETRY_WAITS_S):
            wait = RETRY_WAITS_S[attempt - 1]
            logger.warning(f"{path} -> {r.status_code}; waiting {wait}s and retrying ({attempt}/{len(RETRY_WAITS_S)})")
            await asyncio.sleep(wait)
            continue
        break
    raise SupplyFetchError(f"{path} returned {last}")


async def fetch_purchase_metrics(client: httpx.AsyncClient, token: str, brand_company_id: str,
                                  *, start_epoch_s: int, end_epoch_s: int) -> dict:
    """Account-wide PO KPIs (open PO count, fill rate, GRN count, ...) — not
    parsed into a table yet, kept for a future KPI-strip addition."""
    return await _post(client, token, ep.PURCHASE_METRICS, {
        "mask": "po_metrics",
        "filters": {"supplier_id": "", "brand_company_id": brand_company_id},
        "interval": {"start_time": start_epoch_s, "end_time": end_epoch_s},
    })


async def _sweep_purchase_orders(client: httpx.AsyncClient, token: str,
                                  brand_company_id: str, sort_key: str | None,
                                  ) -> tuple[list[dict], int]:
    """One full page-by-page sweep of searchPurchaseOrder with a given sort
    hint. Returns (rows, total). The rows may contain duplicates and be an
    incomplete subset — see SORT_ROTATION's note; the caller unions sweeps."""
    from scraper.platforms.instamart.dashboard_data.supply.parser import parse_purchase_orders

    rows: list[dict] = []
    total = 0
    page_no = 1
    while True:
        body = {
            "filters": {"brand_company_id": brand_company_id, "selling_party.id": ""},
            "pagination": {"page_number": page_no, "size": PAGE_SIZE},
            "query": {"id": "", "ship_to_party.name": ""},
        }
        if sort_key:
            body["sort"] = [{"sort_by": sort_key, "sort_order": "DESC"}]
        raw = await _post(client, token, ep.SEARCH_PURCHASE_ORDER, body)
        page = parse_purchase_orders(raw)
        rows.extend(page)
        total = (raw.get("data") or {}).get("total_number_of_purchase_order_records") or total
        if len(page) < PAGE_SIZE:
            break
        page_no += 1
    return rows, total


async def fetch_all_purchase_orders(client: httpx.AsyncClient, token: str,
                                     brand_company_id: str) -> list[dict]:
    """Every PO the account has ever raised — no date filter, matching the
    "get everything, window at read time" pattern the rest of this codebase's
    PO/GRN tables follow.

    ⚠️ searchPurchaseOrder's pagination is NON-DETERMINISTIC (it honours no
    sort key), so a single sweep silently drops ~25% of POs — see the
    SORT_ROTATION note above for the full diagnosis. This unions REPEATED
    sweeps with a rotating sort hint until the collected set reaches the
    server's reported total (measured live: 4 sweeps -> complete), keeping the
    freshest copy of each PO. It stops early if two sweeps in a row add nothing
    new (converged), and hard-caps at MAX_SWEEPS so a permanently-unreachable
    PO can't loop forever — in which case it returns what it has and logs the
    gap rather than raising, so the rest of the scrape (line items, export
    sync) still runs on the POs we did get.
    """
    collected: dict[str, dict] = {}
    target = 0
    stall = 0
    for sweep_no in range(1, MAX_SWEEPS + 1):
        sort_key = SORT_ROTATION[(sweep_no - 1) % len(SORT_ROTATION)]
        rows, total = await _sweep_purchase_orders(client, token, brand_company_id, sort_key)
        target = max(target, total)          # count can drift 2131<->2133; aim at the high-water mark
        before = len(collected)
        for po in rows:
            collected[po["purchase_order_id"]] = po   # last write wins = freshest copy
        added = len(collected) - before
        logger.info(
            f"Instamart PO sweep {sweep_no} (sort={sort_key or 'none'}): "
            f"{len(rows)} row(s) -> {len(collected)}/{target} unique (+{added})"
        )
        if target and len(collected) >= target:
            break
        stall = stall + 1 if added == 0 else 0
        if stall >= STALL_LIMIT:
            logger.warning(
                f"Instamart PO: {STALL_LIMIT} sweeps added no new POs; stopping at "
                f"{len(collected)}/{target} — {target - len(collected)} PO(s) unreachable this run"
            )
            break
    else:
        logger.warning(
            f"Instamart PO: hit MAX_SWEEPS={MAX_SWEEPS} at {len(collected)}/{target} — "
            f"{target - len(collected)} PO(s) not collected this run"
        )
    return list(collected.values())


async def submit_po_export(client: httpx.AsyncClient, token: str, brand_company_id: str) -> None:
    """Triggers a fresh bulk CSV export ("Bulk Download"), same job the
    portal UI's button submits -- see endpoints.py's docstring. Fire-and-
    forget: the job runs server-side, poll `fetch_po_export_url` for it."""
    body = {
        "job_definition_name": ep.PO_EXPORT_JOB,
        "filters": {"brand_company_id": brand_company_id,
                    "order_dates.release_date": 1787682600000},
        "tags": [
            {"key": "order_dates.release_date", "value": "Last 30 Days"},
            {"key": "brand_company_id", "value": brand_company_id},
        ],
    }
    await _post(client, token, ep.BATCH_SUBMIT, body)


async def fetch_po_export_url(client: httpx.AsyncClient, token: str, *,
                               max_wait_s: int = 120, poll_gap_s: int = 5) -> str | None:
    """Polls `batch/list` until the most recent export job completes, then
    returns its pre-signed CSV URL. None if it doesn't finish within
    `max_wait_s` (live, it took ~45s) -- the caller should just skip this
    scrape's export step rather than block the whole run indefinitely."""
    body = {
        "filters": {"job_definition_name": ep.PO_EXPORT_JOB, "order_dates.release_date": None},
        "pagination": {"page_number": 1, "size": 1},
        "sort": {"sort_order": "DESC", "sort_by": "UploadedTimestampMs"},
    }
    waited = 0
    while waited <= max_wait_s:
        raw = await _post(client, token, ep.BATCH_LIST, body)
        jobs = raw.get("batch_jobs") or []
        if jobs and jobs[0].get("state") == "STATE_COMPLETED":
            files = jobs[0].get("output_files") or []
            return files[0]["file_url"] if files else None
        await asyncio.sleep(poll_gap_s)
        waited += poll_gap_s
    logger.warning(f"Instamart PO export: job did not complete within {max_wait_s}s, skipping")
    return None


async def fetch_po_export_csv(client: httpx.AsyncClient, file_url: str) -> str:
    """The pre-signed S3 URL needs no auth -- a plain GET."""
    r = await client.get(file_url, timeout=60)
    r.raise_for_status()
    return r.text


async def fetch_po_lines(client: httpx.AsyncClient, token: str, purchase_order_id: str) -> dict:
    return await _post(client, token, ep.LIST_PURCHASE_ORDER_LINES, {
        "filters": {"purchase_order_id": purchase_order_id},
    })


async def fetch_all_po_lines(client: httpx.AsyncClient, token: str,
                             purchase_order_ids: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Line items for every given PO — one call per PO, sequential (see
    LINE_ITEM_CONCURRENCY's note: concurrent calls here trip an edge WAF).

    One PO failing after its own retries is isolated rather than aborting
    the whole batch — verified live 2026-09-25 that a single mid-run network
    blip otherwise threw away everything already fetched in a ~2000-call
    sequential loop. Returns (results, failed_ids) so the caller can save
    what it has and report exactly what's missing, same shape as
    `_scrape_zepto_po`'s per-endpoint isolation.
    """
    results: dict[str, dict] = {}
    failed: list[str] = []
    total = len(purchase_order_ids)
    for i, po_id in enumerate(purchase_order_ids, start=1):
        try:
            results[po_id] = await fetch_po_lines(client, token, po_id)
        except SupplyFetchError as e:
            failed.append(po_id)
            logger.warning(f"Instamart PO lines: {po_id} failed, skipping: {e}")
        if i % 200 == 0 or i == total:
            logger.info(f"Instamart PO lines: {i}/{total} PO(s) processed ({len(failed)} failed)")
        await asyncio.sleep(LINE_ITEM_GAP_S)
    return results, failed
