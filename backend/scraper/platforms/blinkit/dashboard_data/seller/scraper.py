import asyncio
from datetime import datetime, timezone, timedelta

import httpx
from playwright.async_api import async_playwright

from scraper.platforms.blinkit.dashboard_data.seller import endpoints as ep
from scraper.utils.browser import create_browser_context
from scraper.utils.retry import retry
from app.utils.logger import logger

_IST = timezone(timedelta(hours=5, minutes=30))

_PO_ALL_STATES = [
    "Created", "Cancelled", "Expired", "Fulfilled",
    "Cancelled post Creation", "Scheduled", "Unscheduled",
    "Rescheduled", "Delivered", "Partially Scheduled",
]


def _yesterday() -> str:
    return (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Browser header capture ────────────────────────────────────────────────────

async def _capture_headers(storage_state: dict, page_path: str, label: str) -> dict:
    captured: dict = {}

    async with async_playwright() as p:
        browser, context = await create_browser_context(
            p, headless=True, storage_state=storage_state
        )
        page = await context.new_page()

        async def on_request(request):
            if "/v1/" in request.url and not captured:
                hdrs = dict(request.headers)
                if hdrs.get("x-api-key") or hdrs.get("access_token"):
                    captured.update(hdrs)

        page.on("request", on_request)

        try:
            await page.goto(
                f"{ep.BASE_URL}{page_path}", wait_until="networkidle", timeout=60_000
            )
            if not captured:
                await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"{label} page load warning: {e}")
        finally:
            await browser.close()

    if not captured:
        raise RuntimeError(
            f"Could not capture {label} auth headers — session may be expired, try re-login"
        )

    logger.info(f"{label} browser session ready")
    return captured


# ── Sales ─────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=1.0)
async def _fetch_sales(
    client: httpx.AsyncClient,
    headers: dict,
    date_from: str,
    date_to: str,
    offset: int,
    limit: int,
) -> tuple[list, int]:
    payload = {
        "filters": {"created_at__gte": date_from, "created_at__lte": date_to},
        "order_by": [],
    }
    resp = await client.post(
        f"{ep.BASE_URL}{ep.SALES_DETAILS_API}",
        headers=headers,
        params={"offset": offset, "limit": limit},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["data"], data["total_count"]


async def _fetch_all_sales(
    client: httpx.AsyncClient,
    headers: dict,
    date_from: str,
    date_to: str,
) -> list:
    _, total_count = await _fetch_sales(client, headers, date_from, date_to, offset=0, limit=1)
    if total_count == 0:
        return []
    all_rows, _ = await _fetch_sales(client, headers, date_from, date_to, offset=0, limit=total_count)
    offset = len(all_rows)
    while offset < total_count:
        rows, _ = await _fetch_sales(client, headers, date_from, date_to, offset=offset, limit=total_count - offset)
        if not rows:
            break
        all_rows.extend(rows)
        offset = len(all_rows)
    return all_rows


async def _fetch_sales_summary(
    client: httpx.AsyncClient,
    headers: dict,
    date_from: str,
    date_to: str,
) -> dict:
    payload = {"filters": {"created_at__gte": date_from, "created_at__lte": date_to}}

    skus_resp, cats_resp, item_resp = await asyncio.gather(
        client.post(f"{ep.BASE_URL}{ep.DISTINCT_SKUS_API}", headers=headers, json=payload, timeout=30),
        client.post(f"{ep.BASE_URL}{ep.DISTINCT_CATEGORIES_API}", headers=headers, json=payload, timeout=30),
        client.post(f"{ep.BASE_URL}{ep.MAX_SELLING_ITEM_API}", headers=headers, json=payload, timeout=30),
    )

    skus_resp.raise_for_status()
    cats_resp.raise_for_status()

    max_sell_item = None
    if item_resp.status_code != 404:
        item_resp.raise_for_status()
        max_sell_item = item_resp.json()["data"].get("max_sell_item")

    return {
        "distinct_skus": skus_resp.json()["data"]["distinct_skus"],
        "distinct_categories": cats_resp.json()["data"]["distinct_categories"],
        "max_sell_item": max_sell_item,
    }


async def scrape(
    storage_state: dict,
    date: str | None = None,
) -> dict:
    if date is None:
        date = _yesterday()

    headers = await _capture_headers(storage_state, ep.SALES_PAGE, "Sales")

    async with httpx.AsyncClient() as client:
        sales, summary = await asyncio.gather(
            _fetch_all_sales(client, headers, date, date),
            _fetch_sales_summary(client, headers, date, date),
        )

    logger.info(f"Scraped {len(sales)} sales rows [{date}]")

    return {
        "sales": sales,
        "date": date,
        **summary,
    }


# ── PO ────────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=1.0)
async def _fetch_pos_page(
    client: httpx.AsyncClient,
    headers: dict,
    issue_date_gte: str,
    offset: int,
    limit: int,
) -> tuple[list, int]:
    payload = {
        "order_by": ["-expiry_date"],
        "filters": {
            "po_state__in": _PO_ALL_STATES,
            "issue_date__gte": issue_date_gte,
        },
    }
    resp = await client.post(
        f"{ep.BASE_URL}{ep.PO_DETAILS_API}",
        headers=headers,
        params={"offset": offset, "limit": limit},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["data"], data["total_count"]


async def _fetch_all_pos(
    client: httpx.AsyncClient,
    headers: dict,
    issue_date_gte: str,
) -> list:
    _, total_count = await _fetch_pos_page(client, headers, issue_date_gte, offset=0, limit=1)
    if total_count == 0:
        return []
    all_rows, _ = await _fetch_pos_page(client, headers, issue_date_gte, offset=0, limit=total_count)
    offset = len(all_rows)
    while offset < total_count:
        rows, _ = await _fetch_pos_page(client, headers, issue_date_gte, offset=offset, limit=total_count - offset)
        if not rows:
            break
        all_rows.extend(rows)
        offset = len(all_rows)
    return all_rows


@retry(max_attempts=3, delay=1.0)
async def _fetch_po_summary(
    client: httpx.AsyncClient,
    headers: dict,
    issue_date_gte: str,
) -> dict:
    since = issue_date_gte

    (
        total_resp, scheduled_resp, created_resp, cancelled_resp,
        exp_unfulfilled_resp, exp_partial_resp, amount_resp, delivered_resp,
    ) = await asyncio.gather(
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state__in": _PO_ALL_STATES}}),
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state__in": ["Scheduled", "Rescheduled"]}}),
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state": "Created"}}),
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state__in": ["Cancelled", "Cancelled post Creation"]}}),
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state": "Expired", "total_grn_quantity": 0}}),
        client.post(f"{ep.BASE_URL}{ep.PO_COUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since, "po_state": "Expired", "total_grn_quantity__gt": 0}}),
        client.post(f"{ep.BASE_URL}{ep.PO_AMOUNT_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since}}),
        client.post(f"{ep.BASE_URL}{ep.ITEMS_DELIVERED_API}", headers=headers, timeout=30,
                    json={"filters": {"issue_date__gte": since}}),
    )

    for r in (total_resp, scheduled_resp, created_resp, cancelled_resp,
              exp_unfulfilled_resp, exp_partial_resp, amount_resp, delivered_resp):
        r.raise_for_status()

    return {
        "total_raised":          total_resp.json()["data"]["po_count"],
        "scheduled":             scheduled_resp.json()["data"]["po_count"],
        "created":               created_resp.json()["data"]["po_count"],
        "cancelled":             cancelled_resp.json()["data"]["po_count"],
        "expired_unfulfilled":   exp_unfulfilled_resp.json()["data"]["po_count"],
        "expired_partial":       exp_partial_resp.json()["data"]["po_count"],
        "po_amount":             amount_resp.json()["data"]["po_amount"],
        "items_delivered":       delivered_resp.json()["data"]["items_delivered"],
    }


@retry(max_attempts=3, delay=5.0)
async def _fetch_po_items(
    client: httpx.AsyncClient,
    headers: dict,
    po_number: str,
) -> tuple[str, list]:
    resp = await client.post(
        f"{ep.BASE_URL}{ep.PO_ITEMS_API}{po_number}/",
        headers=headers,
        params={"is_paginate": "false"},
        json={},
        timeout=30,
    )
    resp.raise_for_status()
    return po_number, resp.json()["data"]["data"]


async def _fetch_po_skus_batch(
    client: httpx.AsyncClient,
    headers: dict,
    po_numbers: list[str],
) -> dict[str, list]:
    skus: dict[str, list] = {}
    for i, pn in enumerate(po_numbers, 1):
        try:
            po_number, items = await _fetch_po_items(client, headers, pn)
            skus[po_number] = items
            if i % 10 == 0:
                logger.info(f"SKU fetch progress: {i}/{len(po_numbers)}")
        except Exception as e:
            logger.warning(f"SKU fetch failed for {pn}: {e}")
    return skus


async def scrape_po(
    storage_state: dict,
    po_days_back: int = 90,
    known_po_numbers: set[str] | None = None,
) -> dict:
    issue_date_gte = (datetime.now(_IST) - timedelta(days=po_days_back)).strftime("%Y-%m-%d")

    headers = await _capture_headers(storage_state, ep.PO_PAGE, "PO")

    async with httpx.AsyncClient() as client:
        pos, po_summary = await asyncio.gather(
            _fetch_all_pos(client, headers, issue_date_gte),
            _fetch_po_summary(client, headers, issue_date_gte),
        )

        new_po_numbers = [
            po["po_number"] for po in pos
            if po["po_number"] not in (known_po_numbers or set())
        ]

        sku_map: dict[str, list] = {}
        if new_po_numbers:
            sku_map = await _fetch_po_skus_batch(client, headers, new_po_numbers)
            logger.info(f"SKUs fetched for {len(sku_map)}/{len(new_po_numbers)} new POs")

    for po in pos:
        if po["po_number"] in sku_map:
            po["items"] = sku_map[po["po_number"]]

    logger.info(
        f"Scraped {len(pos)} POs [{issue_date_gte}→today] | "
        f"{len(new_po_numbers)} new, {len(sku_map)} SKU sets fetched"
    )

    return {
        "pos": pos,
        "po_summary": po_summary,
        "po_window_start": issue_date_gte,
    }


# ── SOH ───────────────────────────────────────────────────────────────────────

@retry(max_attempts=3, delay=1.0)
async def _fetch_soh_page(
    client: httpx.AsyncClient,
    headers: dict,
    offset: int,
    limit: int,
) -> tuple[list, int]:
    resp = await client.post(
        f"{ep.BASE_URL}{ep.SOH_DETAILS_API}",
        headers=headers,
        params={"offset": offset, "limit": limit},
        json={"filters": {}, "order_by": []},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["data"], data["total_count"]


async def _fetch_all_soh(client: httpx.AsyncClient, headers: dict) -> list:
    _, total_count = await _fetch_soh_page(client, headers, offset=0, limit=1)
    if total_count == 0:
        return []
    rows, _ = await _fetch_soh_page(client, headers, offset=0, limit=total_count)
    return rows


async def scrape_soh(storage_state: dict) -> dict:
    date = datetime.now(_IST).strftime("%Y-%m-%d")
    headers = await _capture_headers(storage_state, ep.SOH_PAGE, "SOH")

    async with httpx.AsyncClient() as client:
        rows = await _fetch_all_soh(client, headers)

    logger.info(f"Scraped {len(rows)} SOH rows [{date}]")
    return {"rows": rows, "date": date}


# ── Scorecard ─────────────────────────────────────────────────────────────────

def _latest_scorecard_monday() -> str:
    # Blinkit publishes week W's data on the Monday after week W ends.
    # So the most recently available data is always for (current_monday - 7 days).
    today = datetime.now(_IST).date()
    current_monday = today - timedelta(days=today.weekday())
    return (current_monday - timedelta(days=7)).isoformat()


async def _capture_scorecard_context(storage_state: dict) -> tuple[dict, str]:
    """Navigate to the scorecard page, capture auth headers + manufacturer_id from the first API request."""
    captured_headers: dict = {}
    captured_manufacturer_id: list[str] = []  # list so nonlocal mutation works in nested fn

    async with async_playwright() as p:
        browser, context = await create_browser_context(
            p, headless=True, storage_state=storage_state
        )
        page = await context.new_page()

        async def on_request(request):
            if ep.SCORECARD_MANUFACTURER_API in request.url and not captured_headers:
                hdrs = dict(request.headers)
                if hdrs.get("x-api-key") or hdrs.get("access_token"):
                    captured_headers.update(hdrs)
                    if not captured_manufacturer_id:
                        try:
                            body = request.post_data_json
                            mid = (body or {}).get("filters", {}).get("manufacturer_id")
                            if mid:
                                captured_manufacturer_id.append(str(mid))
                        except Exception:
                            pass

        page.on("request", on_request)

        try:
            await page.goto(
                f"{ep.BASE_URL}{ep.SCORECARD_PAGE}", wait_until="networkidle", timeout=60_000
            )
            if not captured_headers:
                await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"Scorecard page load warning: {e}")
        finally:
            await browser.close()

    if not captured_headers:
        raise RuntimeError(
            "Could not capture Scorecard auth headers — session may be expired, try re-login"
        )
    if not captured_manufacturer_id:
        raise RuntimeError(
            "Could not capture manufacturer_id from Scorecard page — page may not have loaded fully"
        )

    logger.info("Scorecard browser session ready")
    return captured_headers, captured_manufacturer_id[0]


@retry(max_attempts=3, delay=1.0)
async def _fetch_scorecard(
    client: httpx.AsyncClient,
    headers: dict,
    url: str,
    manufacturer_id: str,
    from_date: str,
    extra_params: dict | None = None,
) -> dict | list:
    payload: dict = {"filters": {"manufacturer_id": manufacturer_id, "from_date_ist": from_date}}
    if extra_params:
        payload.update(extra_params)
    resp = await client.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["data"]


async def scrape_scorecard(storage_state: dict, week: str | None = None) -> dict:
    from_date = week or _latest_scorecard_monday()
    headers, manufacturer_id = await _capture_scorecard_context(storage_state)

    async with httpx.AsyncClient() as client:
        overall_raw, best_cat_raw, categories_raw, facilities_raw, key_skus_raw = (
            await asyncio.gather(
                _fetch_scorecard(client, headers, f"{ep.BASE_URL}{ep.SCORECARD_MANUFACTURER_API}", manufacturer_id, from_date),
                _fetch_scorecard(client, headers, f"{ep.BASE_URL}{ep.SCORECARD_BEST_CATEGORY_API}", manufacturer_id, from_date),
                _fetch_scorecard(client, headers, f"{ep.BASE_URL}{ep.SCORECARD_CATEGORIES_API}", manufacturer_id, from_date),
                _fetch_scorecard(client, headers, f"{ep.BASE_URL}{ep.SCORECARD_FACILITIES_API}", manufacturer_id, from_date, {"params": {"paginate": False}}),
                _fetch_scorecard(client, headers, f"{ep.BASE_URL}{ep.SCORECARD_KEY_SKUS_API}", manufacturer_id, from_date),
            )
        )

    def _first_or_self(val):
        """If the API returned a list, extract the first item; otherwise use as-is."""
        return val[0] if isinstance(val, list) and val else (val if not isinstance(val, list) else {})

    def _ensure_list(val):
        return val if isinstance(val, list) else ([] if val is None else [val])

    overall = _first_or_self(overall_raw)
    best_category = _first_or_self(best_cat_raw)
    categories = _ensure_list(categories_raw)
    facilities = _ensure_list(facilities_raw)
    key_skus = _ensure_list(key_skus_raw)

    logger.info(
        f"Scraped scorecard [{from_date}] | "
        f"fill_rate={overall.get('fill_rate')}% "
        f"facilities={len(facilities)} key_skus={len(key_skus)}"
    )

    return {
        "from_date_ist": from_date,
        "manufacturer_id": manufacturer_id,
        "overall": overall,
        "best_category": best_category,
        "categories": categories,
        "facilities": facilities,
        "key_skus": key_skus,
    }
