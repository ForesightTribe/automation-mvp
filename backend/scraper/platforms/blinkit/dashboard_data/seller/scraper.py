import asyncio
import json
from datetime import datetime, timezone, timedelta

import httpx

from platform_auth.marketplaces.blinkit import seller as seller_auth
from scraper.platforms.blinkit.dashboard_data.seller import endpoints as ep
from scraper.utils.retry import retry
from app.utils.logger import logger

_IST = timezone(timedelta(hours=5, minutes=30))

_PO_ALL_STATES = [
    "Created", "Cancelled", "Expired", "Fulfilled",
    "Cancelled post Creation", "Scheduled", "Unscheduled",
    "Rescheduled", "Delivered", "Partially Scheduled",
]

# PO states that are settled — their line items (and GRN) won't change again, so
# once captured we never need to re-fetch their items.
_PO_TERMINAL_STATES = {
    "Fulfilled", "Delivered", "Cancelled", "Cancelled post Creation", "Expired",
}


def _yesterday() -> str:
    return (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")


# ── Auth context, read off the session ────────────────────────────────────────

# This file is a pure REST client. It never opens a browser, and it CANNOT usefully
# open one — which is worth stating, because both scrapes here used to.
#
# partnersbiz is a Firebase-authenticated SPA: it reads its refresh token from
# IndexedDB, which Playwright's `storage_state` cannot carry (cookies and localStorage
# only). Restoring a seller session into a browser lands on "Sign in via email" no
# matter how valid the token is — and `platform_auth/marketplaces/blinkit/seller.py`
# builds `storage_state` with exactly two keys, `cookies` and `origins`, so there is
# no code path that would ever produce the blob a browser needs.
#
# It worked once because sessions came from a real browser login that captured that
# blob. The 2026-08-05 platform_auth refactor made every Blinkit login browserless
# REST — "Removed obsolete Blinkit authentication scripts ... that relied on
# browser-based login" — and the projection has been un-restorable ever since.
#
# Sales/PO/SOH had already stopped opening a browser, so they never noticed. The
# scorecard still did, and broke on the next weekly run (2026-08-11), reporting an
# expired session while the session was — and still is — perfectly valid. Four weeks
# of data, lost to an error message that named the wrong cause.
#
# ⚠️ Both browser fallbacks were DELETED on 2026-09-04 rather than kept as a safety
# net, because they could not fire on any input: the fallback ran only when the
# session lacked a token or `myEntity`, and a browser restore needs strictly MORE
# from a session than the header path does, never less. What they did instead was
# lie — code that reads as a fallback, guarding an error that blames the session, is
# what made this take four weeks to find. If a browser-based seller login is ever
# reintroduced, add the fallback back deliberately; do not restore it speculatively.

def _entity_from_state(storage_state: dict) -> dict | None:
    """The seller `myEntity` blob from a stored session, or None.

    Carries more than the auth headers need — `external_id` is the manufacturer id
    the scorecard APIs filter on, which is NOT the same number as `id`
    (id=107951 vs external_id=40246 for the same account; the stored scorecard rows
    are keyed on the latter).
    """
    for origin in storage_state.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "myEntity":
                try:
                    entity = json.loads(item["value"])
                except (ValueError, KeyError, TypeError):
                    return None
                return entity if isinstance(entity, dict) else None
    return None


def _headers_from_state(storage_state: dict) -> dict | None:
    """Build the /v1/* auth headers straight from a stored session — no browser.

    The browser this replaced was only ever a header-harvesting device: it opened the
    SPA and copied `access_token` + `x-api-key` off the app's own requests. Both are
    recoverable from the session itself — the token is a cookie, the entity is
    `myEntity` in localStorage — so the whole Chromium launch (~1 GB RSS, ~13 s) is
    avoidable.

    Returns None if either piece is missing; `_capture_headers` turns that into an
    error naming the missing piece.
    """
    token = next(
        (
            c.get("value")
            for c in storage_state.get("cookies", [])
            if c.get("name") == "access_token" and "partnersbiz" in c.get("domain", "")
        ),
        None,
    )
    if not token:
        return None

    entity = _entity_from_state(storage_state)
    # The entity is not optional: /v1/* returns 403 ERROR_CODE:11 without the
    # X-Entity-Id / X-Entity-Type headers derived from it.
    if not entity or "id" not in entity or "type" not in entity:
        return None

    return seller_auth.data_headers(token, entity)


def _missing_from(storage_state: dict) -> str:
    """Which piece of the session is absent — for an error that says something.

    "Session may be expired" was the old message and it was usually FALSE: the session
    is normally fine and merely shaped unexpectedly. Name the field instead, so the
    next person checks the right thing.
    """
    if not _headers_from_state(storage_state):
        has_token = any(
            c.get("name") == "access_token" and "partnersbiz" in c.get("domain", "")
            for c in storage_state.get("cookies", [])
        )
        if not has_token:
            return "no `access_token` cookie for partnersbiz.com"
        entity = _entity_from_state(storage_state)
        if not entity:
            return "no readable `myEntity` in localStorage"
        return "`myEntity` is missing `id` or `type`"
    return "nothing — the session is complete"


def _capture_headers(storage_state: dict, page_path: str, label: str) -> dict:
    """The /v1/* auth headers for a seller scrape. Session only — no browser.

    Sync, because there is no I/O left to await. It was `async` when it drove a
    browser; leaving the keyword on a pure function would imply work it no longer does.

    `page_path` is unused and kept so each call site still documents WHICH dashboard
    page these headers were harvested from before this was a REST client.
    """
    headers = _headers_from_state(storage_state)
    if headers:
        logger.debug(f"{label} session ready (no browser)")
        return headers

    raise RuntimeError(
        f"{label}: cannot build auth headers from the session — "
        f"{_missing_from(storage_state)}. This is NOT necessarily an expired session; "
        f"check `cli auth probe blinkit_seller -t <uuid>` before re-logging in."
    )


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

    headers = _capture_headers(storage_state, ep.SALES_PAGE, "Sales")

    async with httpx.AsyncClient() as client:
        sales, summary = await asyncio.gather(
            _fetch_all_sales(client, headers, date, date),
            _fetch_sales_summary(client, headers, date, date),
        )

    logger.debug(f"Scraped {len(sales)} sales rows [{date}]")

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
                logger.debug(f"SKU fetch progress: {i}/{len(po_numbers)}")
        except Exception as e:
            logger.warning(f"SKU fetch failed for {pn}: {e}")
    return skus


def _pos_needing_items(
    pos: list[dict],
    known_pos: dict[str, tuple[str | None, int | None]],
    refetch_all: bool,
) -> list[str]:
    """PO numbers whose line items need (re)fetching.

    Item-level quantities only change while a PO is still receiving stock, and
    the header's `total_grn_quantity` is the sum of received across its items —
    so a changed (or newly non-zero) GRN, or a still-in-flight state, is the
    signal to refetch. Terminal POs with an unchanged GRN are skipped, since
    their items can no longer move. `refetch_all` forces a full backfill."""
    if refetch_all:
        return [po["po_number"] for po in pos]
    out: list[str] = []
    for po in pos:
        pn = po["po_number"]
        prev = known_pos.get(pn)
        if prev is None:                                  # never seen before
            out.append(pn)
            continue
        prev_state, prev_grn = prev
        if po.get("total_grn_quantity") != prev_grn:      # GRN moved → items moved
            out.append(pn)
        elif prev_state not in _PO_TERMINAL_STATES:       # still in flight
            out.append(pn)
    return out


async def scrape_po(
    storage_state: dict,
    po_days_back: int = 90,
    known_pos: dict[str, tuple[str | None, int | None]] | None = None,
    refetch_all_items: bool = False,
) -> dict:
    issue_date_gte = (datetime.now(_IST) - timedelta(days=po_days_back)).strftime("%Y-%m-%d")

    headers = _capture_headers(storage_state, ep.PO_PAGE, "PO")

    async with httpx.AsyncClient() as client:
        pos, po_summary = await asyncio.gather(
            _fetch_all_pos(client, headers, issue_date_gte),
            _fetch_po_summary(client, headers, issue_date_gte),
        )

        to_fetch = _pos_needing_items(pos, known_pos or {}, refetch_all_items)

        sku_map: dict[str, list] = {}
        if to_fetch:
            sku_map = await _fetch_po_skus_batch(client, headers, to_fetch)
            logger.debug(f"SKUs fetched for {len(sku_map)}/{len(to_fetch)} POs")

    for po in pos:
        if po["po_number"] in sku_map:
            po["items"] = sku_map[po["po_number"]]

    logger.debug(
        f"Scraped {len(pos)} POs [{issue_date_gte}→today] | "
        f"{len(to_fetch)} item sets refetched ({len(sku_map)} ok)"
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
    headers = _capture_headers(storage_state, ep.SOH_PAGE, "SOH")

    async with httpx.AsyncClient() as client:
        rows = await _fetch_all_soh(client, headers)

    logger.debug(f"Scraped {len(rows)} SOH rows [{date}]")
    return {"rows": rows, "date": date}


# ── Scorecard ─────────────────────────────────────────────────────────────────

def _latest_scorecard_monday() -> str:
    # Blinkit publishes week W's data on the Monday after week W ends.
    # So the most recently available data is always for (current_monday - 7 days).
    today = datetime.now(_IST).date()
    current_monday = today - timedelta(days=today.weekday())
    return (current_monday - timedelta(days=7)).isoformat()


def _scorecard_context_from_state(storage_state: dict) -> tuple[dict, str] | None:
    """(headers, manufacturer_id) straight from a stored session — no browser.

    The scorecard needed a browser for one reason the other seller scrapes did not:
    besides the headers it needs `manufacturer_id`, which it read out of the POST
    BODY the SPA sent. That is why it never got the browserless fast path when
    Sales/PO/SOH did — and why it was the only scrape left holding a dependency
    that the 2026-08-05 auth refactor had already broken (see the note at the top
    of this file).

    But the id was never browser-only: it is `myEntity.external_id`, which is in the
    session's own localStorage. Verified against the stored rows — every
    `blinkit_scorecard_*` row for this account is keyed 40246, and the session says
    `external_id: 40246`. ⚠️ NOT `myEntity.id` (107951), which is a different number
    for the same account and would silently return an empty scorecard.

    Returns None if anything is missing, so the caller can fall through and report
    what is actually wrong.
    """
    headers = _headers_from_state(storage_state)
    entity = _entity_from_state(storage_state)
    if not headers or not entity:
        return None
    manufacturer_id = entity.get("external_id")
    if manufacturer_id in (None, ""):
        return None
    return headers, str(manufacturer_id)


def _capture_scorecard_context(storage_state: dict) -> tuple[dict, str]:
    """(headers, manufacturer_id) for the scorecard APIs. Session only — no browser.

    See `_scorecard_context_from_state`. Raises with the missing field named, because
    the message this replaced ("session may be expired") was usually false and is what
    made the 2026-08 outage take four weeks to diagnose.
    """
    ctx = _scorecard_context_from_state(storage_state)
    if ctx:
        logger.debug("Scorecard session ready (no browser)")
        return ctx

    headers = _headers_from_state(storage_state)
    if not headers:
        detail = _missing_from(storage_state)
    else:
        entity = _entity_from_state(storage_state) or {}
        detail = (
            "`myEntity` has no `external_id` (it has "
            f"{sorted(entity) or 'nothing'}) — note the manufacturer id is "
            "`external_id`, NOT `id`, which is a different number for the same account"
        )
    raise RuntimeError(
        f"Scorecard: cannot build the request context from the session — {detail}. "
        "This is NOT necessarily an expired session; check "
        "`cli auth probe blinkit_seller -t <uuid>` before re-logging in."
    )


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
    headers, manufacturer_id = _capture_scorecard_context(storage_state)

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

    logger.debug(
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
