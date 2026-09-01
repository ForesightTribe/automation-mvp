import asyncio
from datetime import date, timedelta

import httpx

from scraper.platforms.zepto.dashboard_data.seller import endpoints as ep
from app.utils.logger import logger


# ── ID discovery ─────────────────────────────────────────────────────────────
# Zepto's Sales Analytics API rejects calls that don't specify brand/city/
# subcategory IDs ("At least one City id is required") — these are specific
# to each tenant's own account, so they can't be hardcoded for a general
# scraper. Re-discovered fresh on every call (not cached) — same "no caching"
# choice Blinkit's own Scorecard scraper makes for its manufacturer_id, after
# weighing it against a cached-mapping design that risked silently missing
# newly-added cities/brands/categories. Both calls are plain httpx, no
# browser, same as validate() above.

async def discover_ids(client) -> dict:
    city_resp = await client.request(
        "GET", ep.CITY_LIST_API, brand_analytics=True, retry_writes=False
    )
    brand_resp = await client.request(
        "GET", ep.BRAND_CATEGORY_MAPPING_API, brand_analytics=True, retry_writes=False
    )
    city_resp.raise_for_status()
    brand_resp.raise_for_status()

    city_list = city_resp.json()["data"]["cityList"]
    city_ids = [c["cityID"] for c in city_list]

    brand_list = brand_resp.json()["data"]["brandCategoryList"]
    if not brand_list:
        raise RuntimeError("brand-category-mapping returned no brands for this account")
    brand = brand_list[0]  # one brand per seller account, per what we've observed

    subcategory_ids: list[str] = []
    subcategory_names: list[str] = []
    for category in brand.get("categoryList", []):
        for sub in category.get("subcategoryList", []):
            subcategory_ids.append(sub["subcategoryID"])
            subcategory_names.append(sub["subcategoryName"])

    result = {
        "brand_id": brand["brandID"],
        "brand_name": brand["brandName"],
        "subcategory_ids": subcategory_ids,
        "subcategory_names": subcategory_names,
        "city_ids": city_ids,
        # Full {cityID, cityName} objects — the per-city sales split needs
        # the names, and re-fetching the list to get them would be wasteful.
        "city_list": city_list,
    }
    logger.info(
        f"Zepto IDs discovered: brand={result['brand_name']} "
        f"({len(subcategory_ids)} subcategories, {len(city_ids)} cities)"
    )
    return result


# ── Browser fallback ─────────────────────────────────────────────────────────
# Only reached for 401/403 (auth-shaped) failures on an otherwise-healthy
# session — a 400/429/500/timeout can't be fixed by touching a browser, so
# those are never routed here (see classify_sales_error / the caller in
# cli/commands/scrape.py). Kept as a rare exception path, not the routine
# daily behavior, given the WAF-challenge risk observed from browser page
# loads on this site.

async def _get_with_auth_fallback(client, url: str, params: dict, label: str) -> dict:
    """GET one Sales-Analytics endpoint through the shared Zepto client.

    The client owns recovery, and it distinguishes the two failures that look
    alike but are not:

      401       identity gone   -> re-login (bounded, see MAX_REAUTH_PER_RUN)
      202/429   browser proof gone -> re-mint the WAF token

    This replaces a browser-relaunch fallback that could only fix the first and
    burned ~15s doing it. It also matters more than it used to: on a shared Zepto
    account the session is evicted mid-run routinely — three times in ten minutes
    on 2026-09-01 — so recovering per-CALL rather than per-RUN is the difference
    between finishing and dying halfway.

    `brand_analytics=True` sends `x-proxy-target` and NO WAF token; these paths
    were measured returning 200 without one.
    """
    path = url.replace(ep.BASE_URL, "", 1)
    resp = await client.request(
        "GET", path, brand_analytics=True, params=params, retry_writes=False
    )
    if resp.status_code >= 400:
        logger.debug(f"{label}: HTTP {resp.status_code}")
    resp.raise_for_status()
    # `data` is null — not an error object — when a filter window matches
    # nothing (verified 2026-08-31: grn/filter for 30..31 Aug returned
    # HTTP 200 `{"success":true,"data":null}`). Returning {} lets callers
    # read an empty list instead of raising AttributeError on None.
    return resp.json().get("data") or {}


async def _post_with_auth_fallback(client, url: str, body: dict, label: str) -> dict:
    """POST twin of the above, for the /vendor PO endpoints.

    `retry_writes=False`: these are filter/search POSTs and idempotent in
    practice, but the flag is about intent — a timeout is never safe to replay
    blindly, because the call may have landed and only the answer was lost.
    """
    path = url.replace(ep.BASE_URL, "", 1)
    resp = await client.request(
        "POST", path, brand_analytics=True, json=body, retry_writes=False
    )
    if resp.status_code >= 400:
        logger.debug(f"{label}: HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.json().get("data") or {}


# Retry wrapper for the PO-app endpoints.
#
# These are slow and variable — measured 2026-08-30, asn/filter returned in
# anywhere from 4.8s to 21s for the SAME 31-day window. When Zepto's own
# upstream exceeds its gateway timeout the gateway answers 500, so the failure
# arrives as a server error rather than a client timeout. Roughly 4 failures in
# 18 attempts that day, randomly distributed: not the window size (a 31-day
# window succeeded 5/5), not the payload (every variant worked), not the call
# order (it failed alone and succeeded after po+grn).
#
# Without this, one blip discarded an entire dataset. `_scrape_zepto_po`'s
# `_try` guard catches the exception so a flaky endpoint cannot kill the whole
# run — correct, but it has no retry, so a single 500 wrote ZERO ASNs while the
# API held 76. Silent except for one warning line.
#
# Only 5xx is retried. A 4xx will not fix itself, and auth errors already have
# their own browser fallback inside _post_with_auth_fallback.
#
# The waits are deliberately long. The endpoint does not fail in isolated blips:
# measured the same day, four consecutive attempts each timed out at ~23s and
# the whole 103s stretch failed, then the next two calls succeeded in 15.7s and
# 5.2s. So a bad patch outlasts a short backoff. 5/15/45 spans ~160s of waiting
# plus ~90s of attempts, which cleared it in testing.
#
# This makes a bad run slow, not fatal, and a PO scrape is not latency-critical.
# A total failure still costs only the ASN dataset for that run: the upsert
# writes nothing when the list is empty, so previously stored ASNs survive.
_PO_RETRY_WAITS_S = (5, 15, 45)


async def _post_5xx_retry(
    client: dict, url: str, payload: dict, label: str
) -> dict:
    last: Exception | None = None
    for attempt, wait in enumerate((*_PO_RETRY_WAITS_S, None)):
        try:
            return await _post_with_auth_fallback(client, url, payload, label)
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or wait is None:
                raise
            last = e
            logger.warning(
                f"{label} got {e.response.status_code} "
                f"(attempt {attempt + 1}), retrying in {wait}s"
            )
            await asyncio.sleep(wait)
    raise last  # unreachable; the final iteration re-raises


async def _fetch_po_paged(
    client: dict, api: str, body: dict, list_key: str, label: str
) -> list[dict]:
    """Page through one PO-app endpoint until `hasNext` is false.

    All three (po/grn/asn) share this shape: offset/limit in, `{list_key: [...],
    total, hasNext}` out. PO_MAX_PAGES bounds the loop so a misreported
    `hasNext` cannot spin forever.
    """
    out: list[dict] = []
    for page in range(ep.PO_MAX_PAGES):
        payload = {**body, "offset": page * ep.PO_PAGE_SIZE, "limit": ep.PO_PAGE_SIZE}
        data = await _post_5xx_retry(
            client, f"{ep.BASE_URL}{api}", payload, f"{label} p{page + 1}"
        )
        rows = data.get(list_key) or []
        out.extend(rows)
        if not data.get("hasNext"):
            break
        await asyncio.sleep(0.4)
    logger.info(f"Zepto {label}: {len(out)} row(s)")
    return out


def _po_window(date_from: str, date_to: str) -> tuple[str, str]:
    """Zepto's PO filters take IST day boundaries expressed in UTC — the browser
    sends 18:30 of the previous day through 18:29:59.999 of the end day. Sending
    plain dates returns a window shifted by 5h30m, quietly dropping the first
    and last few hours of orders."""
    start = f"{(date.fromisoformat(date_from) - timedelta(days=1)).isoformat()}T18:30:00.000Z"
    end = f"{date_to}T18:29:59.999Z"
    return start, end


async def fetch_pos(
    client: dict, date_from: str, date_to: str
) -> list[dict]:
    """Purchase-order headers for the window. Line items are NOT included —
    the response carries `itemsCount` only; the lines sit behind a per-PO
    detail call that has not been captured."""
    start, end = _po_window(date_from, date_to)
    return await _fetch_po_paged(
        client, ep.PO_FILTER_API,
        {
            "vendorCodes": [], "locationCodes": [],
            "poStartDate": start, "poEndDate": end,
            # Empty = every status. The browser sends one value because the UI
            # is on a tab; see the warning in endpoints.py.
            "statusList": [], "ids": [],
            "scheduledStartDate": None, "scheduledEndDate": None,
            "expiryStartDate": None, "expiryEndDate": None,
        },
        "poList", f"po/filter [{date_from}..{date_to}]",
    )


async def fetch_grns(
    client: dict, date_from: str, date_to: str
) -> list[dict]:
    """Goods-receipt notes — what Zepto actually took in. `poQty` vs `grnQty`
    on each row is the fill rate."""
    start, end = _po_window(date_from, date_to)
    return await _fetch_po_paged(
        client, ep.GRN_FILTER_API,
        {
            "vendorCodes": [], "locationCodes": [],
            "grnStartDate": start, "grnEndDate": end,
            "statusList": [], "grnNos": [], "poIds": [],
        },
        "grnList", f"grn/filter [{date_from}..{date_to}]",
    )


async def fetch_asns(
    client: dict, date_from: str, date_to: str
) -> list[dict]:
    """Advance shipping notices — what the vendor declared as sent."""
    start, end = _po_window(date_from, date_to)
    return await _fetch_po_paged(
        client, ep.ASN_FILTER_API,
        {
            "vendorCodes": [], "locationCodes": [],
            "asnStartDate": start, "asnEndDate": end,
            "statusList": [], "asnNos": [], "extAsnNos": [],
            "poIds": [], "trackingId": "",
        },
        "asnList", f"asn/filter [{date_from}..{date_to}]",
    )


async def fetch_po_items(
    client: dict, po_ids: list[str]
) -> dict[str, list[dict]]:
    """Line items for each PO. Returns {po_id: [item, ...]}.

    One GET per PO — the filter endpoint gives `itemsCount` but not the lines.
    74 POs is 74 calls, which is fine on the vendor API (no WAF challenge, no
    volume cap observed, unlike the public search endpoint).

    A PO whose call fails is skipped with a warning rather than aborting the run:
    a single bad PO should not cost the other 73.
    """
    out: dict[str, list[dict]] = {}
    for i, po_id in enumerate(po_ids, 1):
        rows: list[dict] = []
        try:
            for page in range(ep.PO_MAX_PAGES):
                data = await _get_with_auth_fallback(
                    client,
                    f"{ep.BASE_URL}{ep.PO_ITEMS_API.format(po_id=po_id)}",
                    {"offset": page * ep.PO_PAGE_SIZE, "limit": ep.PO_PAGE_SIZE},
                    f"po/{po_id}/items p{page + 1}",
                )
                rows.extend(data.get("poItems") or [])
                if not data.get("hasNext"):
                    break
        except Exception as e:
            logger.warning(f"Zepto po items failed for {po_id}: {e}")
            continue
        if rows:
            out[po_id] = rows
        if i < len(po_ids):
            await asyncio.sleep(0.4)

    logger.info(
        f"Zepto po items: {sum(len(v) for v in out.values())} line(s) "
        f"across {len(out)}/{len(po_ids)} POs"
    )
    return out


class NoDataYet(RuntimeError):
    """Zepto accepted the request but has not computed that date range yet.

    Distinct from a failure: the session is fine, the parameters are fine, the
    day simply is not ready. Callers should report it as "try later", not as a
    broken scrape.
    """


async def fetch_sales_overview(client: dict, date_from: str, date_to: str, ids: dict) -> dict:
    """Real GMV/Units data from Zepto's Sales Analytics — direct API call,
    no browser, using freshly-discovered tenant IDs (see discover_ids)."""
    params = {
        "brandIds": ids["brand_id"],
        "brandNames": ids["brand_name"],
        "subcategoryNames": "|".join(ids["subcategory_names"]),
        "subcategoryIds": ",".join(ids["subcategory_ids"]),
        "cityIds": ",".join(ids["city_ids"]),
        "startDate": date_from,
        "endDate": date_to,
        "viewType": "BRAND",
        "aggregationLevel": "DAY",
    }
    data = await _get_with_auth_fallback(
        client, f"{ep.BASE_URL}{ep.SALES_OVERVIEW_API}", params, "Sales-overview"
    )

    # Zepto computes a day on a lag — its own dashboard footer says "Last
    # updated on <date> 8:17 am", i.e. once each morning. Ask for a day it has
    # not processed and the response is structurally different: the `headers`
    # block carrying the totals is ABSENT, and every point in `metrics` is null.
    #
    #   2026-08-28   headers present   gmv Rs 64,280   {"Brik Oven": 64280}
    #   2026-08-29   headers present   gmv Rs 54,275   {"Brik Oven": 54275}
    #   2026-08-30   headers ABSENT    gmv None        {"Brik Oven": null}
    #
    # (measured 2026-08-31 08:2x — the 30th was still not ready the next
    # morning, and Zepto's own dashboard showed nothing for it either.)
    #
    # Reading data["headers"] blind raised a bare KeyError('headers'), which
    # surfaced as `Scrape failed: 'headers'` — no indication that the only
    # problem was asking too early. The CLI defaults --to to yesterday for this
    # reason; this path is reached when that default is overridden.
    if "headers" not in data:
        raise NoDataYet(
            f"Zepto has not computed {date_from}..{date_to} yet — the response "
            f"carries no totals and every value is null. Zepto refreshes once a "
            f"morning, so a day is usually ready the following afternoon. "
            f"Re-run later, or scrape up to yesterday instead."
        )

    gmv = data["headers"]["gmv"]["value"]
    units = data["headers"]["units"]["value"]
    daily = data["metrics"]["gmv"]["data"]
    logger.info(f"Zepto sales-overview [{date_from}..{date_to}]: GMV={gmv} Units={units} ({len(daily)} days)")
    return data


async def fetch_sales_by_city(
    client: dict,
    date_from: str,
    date_to: str,
    ids: dict,
    city_ids: list[str] | None = None,
) -> dict[str, dict]:
    """Per-city GMV/units. Returns {city_id: raw sales-overview response}.

    Zepto exposes no city breakdown in a single response — `viewType=CITY` is
    rejected by the parameter's `oneof` validation — but `cityIds` accepts ONE
    id and returns that city's full daily series. So a city split means one call
    per city, each covering the whole date range.

    `city_ids` defaults to every city the account can see (138 on this one). A
    sweep on 21-Aug-2026 found sales in exactly one of them, so callers should
    normally pass the short list of cities already known to sell and only sweep
    everything occasionally.
    """
    targets = city_ids if city_ids is not None else ids["city_ids"]
    out: dict[str, dict] = {}
    for i, city_id in enumerate(targets, 1):
        params = {
            "brandIds": ids["brand_id"],
            "brandNames": ids["brand_name"],
            "subcategoryNames": "|".join(ids["subcategory_names"]),
            "subcategoryIds": ",".join(ids["subcategory_ids"]),
            "cityIds": city_id,
            "startDate": date_from,
            "endDate": date_to,
            "viewType": "BRAND",
            "aggregationLevel": "DAY",
        }
        try:
            out[city_id] = await _get_with_auth_fallback(
                client,
                f"{ep.BASE_URL}{ep.SALES_OVERVIEW_API}",
                params,
                f"Sales-by-city[{city_id[:8]}]",
            )
        except Exception as e:
            logger.warning(f"Zepto sales-by-city failed for {city_id}: {e}")
        if i < len(targets):
            await asyncio.sleep(0.6)

    logger.info(
        f"Zepto sales-by-city [{date_from}..{date_to}]: {len(out)}/{len(targets)} cities fetched"
    )
    return out


async def fetch_product_performance(
    client: dict, date_from: str, date_to: str, ids: dict, limit: int = 50
) -> list[dict]:
    """Per-SKU breakdown from Zepto's Sales Analytics — GMV, units, sales
    share, growth, and conversion metrics per product.

    NOTE ON `viewType`: the browser sends `viewType=top_selling`, which the API
    caps at the **top 5 products**. Copying that verbatim made the SKU rows sum
    ~3% under `fetch_sales_overview`'s totals. Omitting the parameter returns
    the full catalog and reconciles exactly (verified 2026-08-19: 9 selling
    SKUs summing to ₹18,31,040 / 16,882 units for 17 Jul–16 Aug, matching the
    overview to the rupee). Do not reinstate it.

    `stockOnHand` always comes back null — Stock View is subscription-gated on
    this account.
    """
    params = {
        "brandIds": ids["brand_id"],
        "brandNames": ids["brand_name"],
        "subcategoryNames": "|".join(ids["subcategory_names"]),
        "subcategoryIds": ",".join(ids["subcategory_ids"]),
        "cityIds": ",".join(ids["city_ids"]),
        "startDate": date_from,
        "endDate": date_to,
        "limit": limit,
        "offset": 0,
    }
    data = await _get_with_auth_fallback(
        client, f"{ep.BASE_URL}{ep.PRODUCT_PERFORMANCE_API}", params, "Product-performance"
    )
    # Without `viewType` the response covers the whole catalog, so it includes
    # products with no sales in the window (gmv/qtySold come back null). Those
    # are dropped: a zero-sales row adds nothing to any chart, and keeping them
    # would inflate the "Active SKUs" count with products that sold nothing.
    products = [p for p in (data["data"] or []) if p.get("gmv")]
    logger.info(f"Zepto product-performance [{date_from}..{date_to}]: {len(products)} products with sales")
    return products


async def fetch_product_performance_by_city(
    client: dict,
    date_from: str,
    date_to: str,
    ids: dict,
    city_ids: list[str] | None = None,
    limit: int = 50,
) -> dict[str, list[dict]]:
    """Per-SKU breakdown split by city. Returns {city_id: [product, ...]}.

    Same endpoint as `fetch_product_performance`, but with `cityIds` set to ONE
    city instead of all of them — which is what makes the city dimension appear.
    Verified 2026-08-26: Bengaluru returned 9 SKUs / Rs 52,215 for 25-Aug while
    three other cities returned nothing, so the filter is real and not ignored.

    This is the only way to get city and category onto the same row; no single
    Zepto response carries both.

    `city_ids` defaults to every city the account can see (138 on this account),
    which is a lot of calls. Callers should normally pass the short list of
    cities already known to sell and sweep everything only occasionally — the
    same trade-off `fetch_sales_by_city` documents. A sweep is worth running
    periodically: Hosur went unnoticed for weeks because it was not in the known
    list (found 2026-08-26, Rs 220 on 21-Aug).
    """
    targets = city_ids if city_ids is not None else ids["city_ids"]
    out: dict[str, list[dict]] = {}
    for i, city_id in enumerate(targets, 1):
        params = {
            "brandIds": ids["brand_id"],
            "brandNames": ids["brand_name"],
            "subcategoryNames": "|".join(ids["subcategory_names"]),
            "subcategoryIds": ",".join(ids["subcategory_ids"]),
            "cityIds": city_id,
            "startDate": date_from,
            "endDate": date_to,
            "limit": limit,
            "offset": 0,
        }
        try:
            data = await _get_with_auth_fallback(
                client,
                f"{ep.BASE_URL}{ep.PRODUCT_PERFORMANCE_API}",
                params,
                f"Product-performance/city[{city_id[:8]}]",
            )
            rows = [p for p in (data["data"] or []) if p.get("gmv")]
            if rows:
                out[city_id] = rows
        except Exception as e:
            logger.warning(f"Zepto product-performance failed for city {city_id}: {e}")
        if i < len(targets):
            await asyncio.sleep(0.6)

    logger.info(
        f"Zepto product-performance by city [{date_from}..{date_to}]: "
        f"{len(out)}/{len(targets)} cities with sales"
    )
    return out


# ── Ads (`ads-bff`) ──────────────────────────────────────────────────────────
# Unlike the analytics endpoints above, ads-bff will not accept the saved
# session's WAF token — it answers 202, an AWS WAF challenge. Only a live
# browser produces a token it accepts, so ads scraping harvests headers from
# one short page load and then makes plain HTTP calls with them, the same
# shape as blinkit/dashboard_data/seller/scraper.py::_capture_headers.
#
# Header set matters too: the request must look like the app's own. Sending
# `accept: application/json, text/plain, */*` (httpx-ish) or omitting
# referer/user-agent also draws a 202, even with a good token.

_ADS_HEADER_KEYS = frozenset(
    {"accept", "accept-language", "authorization", "referer", "user-agent",
     "waf-enabled", "x-aws-waf-token"}
)


async def capture_ads_headers(client) -> dict:
    """Headers for `/ads-bff/*` — the client already holds both credentials.

    This used to drive a logged-in browser to the ads page and steal the headers
    off its first ads-bff request, which needed session COOKIES. platform_auth
    stores none: the JWT travels in a header.

    Unlike Sales Analytics, `/ads-bff/*` genuinely needs the WAF token AND
    `waf-enabled: false` — either alone gets a 429, which reads like rate
    limiting and is not. `headers(brand_analytics=False)` sends that pair.
    """
    logger.info("Zepto ads headers ready (jwt + waf)")
    return client.headers(brand_analytics=False)


async def fetch_ad_campaigns(
    headers: dict, brand_id: str, date_from: str, date_to: str, category: str
) -> list[dict]:
    """Every campaign in one category for a window, following pagination.

    The response carries `total_count` and `has_next`; rows come 10 at a time,
    so a brand with 26 campaigns is three calls.
    """
    by_id: dict = {}
    total = None
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            # `page`, 1-based. Verified by elimination: offset / skip / page_no
            # / pageNumber / page_number are all silently ignored and return
            # page 1 again, which is how the first version of this loop spun to
            # offset=920 and drew a 429.
            params = {
                "selectedBrand": brand_id,
                "brand_id": brand_id,
                "from_date": date_from,
                "to_date": date_to,
                "categoryType": category,
                "page": page,
            }
            resp = await client.get(
                f"{ep.BASE_URL}{ep.ADS_CAMPAIGNS_API}", headers=headers, params=params, timeout=30
            )
            if resp.status_code == 202:
                raise RuntimeError(
                    "ads-bff answered 202 (WAF challenge) — the captured token was rejected; retry the header capture"
                )
            resp.raise_for_status()
            data = resp.json()["data"] or {}
            rows = data.get("campaigns") or []
            if total is None:
                total = data.get("total_count") or 0

            # Bound the loop on total_count and on actually seeing new ids —
            # NOT on has_next alone. `has_next` stayed true even once every
            # campaign had been returned, so trusting it spun to offset=920
            # and drew a 429. Duplicate ids mean the offset param is being
            # ignored, in which case paging further is pointless.
            before = len(by_id)
            for r in rows:
                cid = r.get("campaign_id")
                if cid is not None:
                    by_id[cid] = r
            if not rows or len(by_id) == before or len(by_id) >= total:
                break

            page += 1
            await asyncio.sleep(1.5)

    out = list(by_id.values())
    if total and len(out) < total:
        logger.warning(
            f"Zepto ad campaigns [{category}]: got {len(out)} of {total} — pagination stopped early"
        )

    # ads-bff sometimes answers with the campaign list intact but every metric
    # set to "-", then returns real figures for the same window moments later
    # (observed repeatedly on 2026-08-20). Storing that quietly would write a
    # day of zeros over good data, so say so — the caller decides whether to
    # retry rather than this function looping on its own.
    if out and not any(_has_metrics(c) for c in out):
        logger.warning(
            f"Zepto ad campaigns [{category}] [{date_from}]: {len(out)} campaigns but every "
            "metric is empty — ads-bff often does this transiently; treat as not-yet-ready, not as zero spend"
        )

    logger.info(f"Zepto ad campaigns [{category}] [{date_from}..{date_to}]: {len(out)} of {total}")
    return out


def _has_metrics(c: dict) -> bool:
    """True if a campaign row carries any real figure. Zepto writes "-" (not 0
    or null) where it has nothing."""
    for key in ("spend", "impressions", "clicks"):
        v = c.get(key)
        if v in (None, "", "-", "0"):
            continue
        try:
            if float(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def fetch_ad_daily_metrics(
    headers: dict, brand_id: str, date_from: str, date_to: str, category: str
) -> dict[str, list[dict]]:
    """Per-day brand-level ad metrics for one category.

    `breakdown: true` is what returns the time series; `summary: true` would
    give only window totals. Metrics are requested one at a time because that
    is how the portal itself asks — a combined request returns the series for
    just one of them.

    Note the grain: this is per brand per day, NOT per campaign per day (which
    is what Blinkit's blinkit_ad_campaign_daily holds). Zepto exposes no
    per-campaign time series that we have found.
    """
    series: dict[str, list[dict]] = {}
    async with httpx.AsyncClient() as client:
        for metric in ep.ADS_METRIC_NAMES:
            body = {
                "from": f"{date_from} 00:00:00",
                "to": f"{date_to} 23:59:59",
                "interval": "day",
                "campaign_category": category,
                "metrics": [metric],
                "breakdown": True,
                "brand_id": brand_id,
            }
            resp = await client.post(
                f"{ep.BASE_URL}{ep.ADS_METRICS_API}",
                headers={**headers, "content-type": "application/json"},
                json=body,
                timeout=30,
            )
            if resp.status_code == 202:
                raise RuntimeError("ads-bff answered 202 (WAF challenge) — retry the header capture")
            resp.raise_for_status()
            m = ((resp.json().get("data") or {}).get("metrics") or {}).get(metric) or {}
            series[metric] = m.get("interval_breakdown") or []
            await asyncio.sleep(1.5)

    days = max((len(v) for v in series.values()), default=0)
    logger.info(f"Zepto ad daily metrics [{category}] [{date_from}..{date_to}]: {days} days")
    return series


async def fetch_ads_tabular(
    headers: dict,
    brand_id: str,
    date_from: str,
    date_to: str,
    view: str,
    category: str = "sponsored_products",
) -> list[dict]:
    """One of the Analytics page's performance tables, following pagination.

    `view` is an ep.ADS_VIEW_* value. Every view shares a metric set prefixed
    with its dimension (campaign_revenue, keyword_revenue, ...), so callers
    strip the prefix rather than special-casing each one.

    Prefer this over `fetch_ad_campaigns` for performance figures: it reports
    revenue, add-to-carts and the FOC-excluded RoAS (`robas`), none of which
    the Campaign Management endpoint returns. `fetch_ad_campaigns` remains the
    source for operational fields — daily budget, base bid, targeting, dates.

    Date-aware — verified 20-Aug-2026 on campaign 2127644, where every figure
    scaled with the window (1 day / 6 days / 31 days): spend 2,598 / 13,154 /
    73,023, revenue 7,580 / 40,210 / 199,020, atc 29 / 150 / 730, orders
    73 / 389 / 1,915. Safe to store per day.

    Note `orders` here is NOT the `orders` on the campaigns endpoint, which is
    a lifetime figure that ignores the range entirely (stuck at 158 for every
    window). Same name, different behaviour — take orders from this view.
    """
    out: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            body = {
                "from": f"{date_from} 00:00:00",
                "to": f"{date_to} 23:59:59",
                "view": view,
                "size": ep.ADS_TABULAR_PAGE_SIZE,
                "page": page,
                "campaign_category": category,
                "brand_id": brand_id,
            }
            resp = await client.post(
                f"{ep.BASE_URL}{ep.ADS_TABULAR_API}",
                headers={**headers, "content-type": "application/json"},
                json=body,
                timeout=30,
            )
            if resp.status_code == 202:
                raise RuntimeError("ads-bff answered 202 (WAF challenge) — retry the header capture")
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            rows = data.get("rows") or []
            out.extend(rows)
            total = data.get("total_count") or 0
            # Bounded by total_count, not has_next — the campaigns endpoint's
            # has_next stayed true forever and spun a loop to 92 requests.
            if not rows or len(out) >= total:
                break
            page += 1
            await asyncio.sleep(1.5)

    logger.info(f"Zepto ads {view} [{date_from}..{date_to}]: {len(out)} rows")
    return out
