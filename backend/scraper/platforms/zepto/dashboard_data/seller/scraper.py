import asyncio
from datetime import date, timedelta

import httpx

from scraper.platforms.zepto.dashboard_data.seller import endpoints as ep
from scraper.utils.retry import retry_call
from platform_auth.errors import AuthError
from app.utils.logger import logger
from app.utils.time import now_ist


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
    logger.debug(
        f"Zepto IDs discovered: brand={result['brand_name']} "
        f"({len(subcategory_ids)} subcategories, {len(city_ids)} cities)"
    )
    return result


# ── Requests (sales analytics + the /vendor PO app) ─────────────────────────

async def _get(client, url: str, params: dict, label: str) -> dict:
    """GET one Sales-Analytics endpoint through the shared Zepto client, -> `data`.

    The client owns recovery, and it distinguishes the two failures that look
    alike but are not:

      401       identity gone   -> re-login (bounded, see MAX_REAUTH_PER_RUN)
      202/429   browser proof gone -> re-mint the WAF token

    Per-CALL recovery matters on a shared Zepto account: the session is evicted
    mid-run routinely — three times in ten minutes on 2026-09-01. (This replaced a
    browser-relaunch fallback that could only fix the first and burned ~15 s.)

    `brand_analytics=True` sends `x-proxy-target` and NO WAF token; these paths
    were measured returning 200 without one.
    """
    path = url.replace(ep.BASE_URL, "", 1)
    resp = await client.request("GET", path, brand_analytics=True, params=params)
    if resp.status_code >= 400:
        logger.debug(f"{label}: HTTP {resp.status_code}")
    resp.raise_for_status()
    # `data` is null — not an error object — when a filter window matches
    # nothing (verified 2026-08-31: grn/filter for 30..31 Aug returned
    # HTTP 200 `{"success":true,"data":null}`). Returning {} lets callers
    # read an empty list instead of raising AttributeError on None.
    return resp.json().get("data") or {}


async def _post(client, url: str, body: dict, label: str) -> dict:
    """POST twin of `_get`, for the /vendor PO endpoints (filter/search POSTs —
    reads, despite the verb). The client never replays a timeout."""
    path = url.replace(ep.BASE_URL, "", 1)
    resp = await client.request("POST", path, brand_analytics=True, json=body)
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
# Without this, one blip discarded an entire dataset. run_po's `_try` guard
# catches the exception so a flaky endpoint cannot kill the whole run — correct,
# but it has no retry, so a single 500 wrote ZERO ASNs while the API held 76.
#
# Only 5xx is retried. A 4xx will not fix itself, and a 401 is already handled
# inside the shared Zepto client (re-login, resend once).
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


def _is_5xx(e: Exception) -> bool:
    """The one failure class these endpoints recover from on their own."""
    return (isinstance(e, httpx.HTTPStatusError) and e.response is not None
            and e.response.status_code >= 500)


async def _post_5xx_retry(client, url: str, payload: dict, label: str) -> dict:
    return await retry_call(
        lambda: _post(client, url, payload, label),
        waits=_PO_RETRY_WAITS_S, retry_if=_is_5xx, label=label,
    )


async def _fetch_po_paged(
    client: dict, api: str, body: dict, list_key: str, label: str,
    page_size: int | None = None,
) -> list[dict]:
    """Page through one PO-app endpoint until `hasNext` is false.

    All three (po/grn/asn) share this shape: offset/limit in, `{list_key: [...],
    total, hasNext}` out. PO_MAX_PAGES bounds the loop so a misreported
    `hasNext` cannot spin forever.

    `page_size` exists because asn/filter cannot take the same page size as its
    siblings — it 500s at 100 and answers in under a second at 50. See
    ASN_PAGE_SIZE in endpoints.py for the measurements.
    """
    size = page_size or ep.PO_PAGE_SIZE
    out: list[dict] = []
    for page in range(ep.PO_MAX_PAGES):
        payload = {**body, "offset": page * size, "limit": size}
        data = await _post_5xx_retry(
            client, f"{ep.BASE_URL}{api}", payload, f"{label} p{page + 1}"
        )
        rows = data.get(list_key) or []
        out.extend(rows)
        if not data.get("hasNext"):
            break
        await asyncio.sleep(0.4)
    logger.debug(f"Zepto {label}: {len(out)} row(s)")
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
        # The one endpoint that needs a smaller page — see ASN_PAGE_SIZE.
        page_size=ep.ASN_PAGE_SIZE,
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
                data = await _get(
                    client,
                    f"{ep.BASE_URL}{ep.PO_ITEMS_API.format(po_id=po_id)}",
                    {"offset": page * ep.PO_PAGE_SIZE, "limit": ep.PO_PAGE_SIZE},
                    f"po/{po_id}/items p{page + 1}",
                )
                rows.extend(data.get("poItems") or [])
                if not data.get("hasNext"):
                    break
        except AuthError:
            # Not a bad PO: the session is gone, and every remaining PO would fail
            # the same way. Let it reach the CLI, which exits 3 (`auth_expired`).
            raise
        except Exception as e:
            logger.warning(f"Zepto po items failed for {po_id}: {e}")
            continue
        if rows:
            out[po_id] = rows
        if i < len(po_ids):
            await asyncio.sleep(0.4)

    logger.debug(
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
    data = await _get(
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
    logger.debug(f"Zepto sales-overview [{date_from}..{date_to}]: GMV={gmv} Units={units} ({len(daily)} days)")
    return data


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

    `stockOnHand` IS returned (2026-10-05: on 561 of 625 Brik Oven rows and all
    195 Sereko rows) — it is a reading at the time of the call, not a fact about
    the sales day; see storage._KEEP_IF_NULL.
    """
    params = {
        "brandIds": ids["brand_id"],
        "brandNames": ids["brand_name"],
        "subcategoryNames": "|".join(ids["subcategory_names"]),
        "subcategoryIds": ",".join(ids["subcategory_ids"]),
        "cityIds": ",".join(ids["city_ids"]),
        "startDate": date_from,
        "endDate": date_to,
    }
    products = await _product_rows(client, params, "Product-performance", limit)
    logger.debug(f"Zepto product-performance [{date_from}..{date_to}]: {len(products)} products with sales")
    return products


# Bound on product-performance pages: 20 x 50 = 1,000 selling SKUs in one day/city.
_PRODUCT_MAX_PAGES = 20


async def _product_rows(client, params: dict, label: str, limit: int) -> list[dict]:
    """Every selling product for one product-performance query, page by page (P47).

    It used to ask for one page of `limit` and stop, so a brand with more selling
    SKUs than that on a day would have been cut short with nothing said (max seen:
    12). It now asks for the next `offset` only while a page comes back FULL, so a
    normal day still costs one call. Bounded by new rows as well as page count: if
    Zepto ignored `offset` and repeated page 1, paging stops instead of looping.

    Without `viewType` the response covers the whole catalog, including products
    with no sales in the window (gmv/qtySold null). Those are dropped: a zero-sales
    row adds nothing to any chart and would inflate "Active SKUs".
    """
    out: list[dict] = []
    seen: set = set()
    for page in range(_PRODUCT_MAX_PAGES):
        data = await _get(
            client, f"{ep.BASE_URL}{ep.PRODUCT_PERFORMANCE_API}",
            {**params, "limit": limit, "offset": page * limit}, f"{label} p{page + 1}",
        )
        rows = data.get("data") or []
        new = [r for r in rows if r.get("productVariantId") not in seen]
        seen.update(r.get("productVariantId") for r in new)
        out.extend(new)
        if len(rows) < limit or not new:
            break
    else:
        logger.error(f"Zepto {label}: stopped after {_PRODUCT_MAX_PAGES} full pages — "
                     "more products than the page bound; raise _PRODUCT_MAX_PAGES")
    return [p for p in out if p.get("gmv")]


async def fetch_product_performance_by_city(
    client: dict,
    date_from: str,
    date_to: str,
    ids: dict,
    city_ids: list[str] | None = None,
    limit: int = 50,
    failed: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Per-SKU breakdown split by city. Returns {city_id: [product, ...]}.

    A city whose call fails is skipped so the others still land — and, when the
    caller passes a `failed` list, its id is appended there. Without that list a
    failed city looked exactly like a city with no sales: absent from the result,
    the run green, a hole in the city table nobody heard about.

    Same endpoint as `fetch_product_performance`, but with `cityIds` set to ONE
    city instead of all of them — which is what makes the city dimension appear.
    Verified 2026-08-26: Bengaluru returned 9 SKUs / Rs 52,215 for 25-Aug while
    three other cities returned nothing, so the filter is real and not ignored.

    This is the only way to get city and category onto the same row; no single
    Zepto response carries both.

    `city_ids` defaults to every city the account can see (~145), one call each.
    Which cities to ask on which day is the caller's decision — see
    run._city_split (every city for the newest day, the known ones for the rest).
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
        }
        try:
            rows = await _product_rows(
                client, params, f"Product-performance/city[{city_id[:8]}]", limit)
            if rows:
                out[city_id] = rows
        except AuthError:
            raise                      # the session is gone — no other city will work either
        except Exception as e:
            logger.debug(f"Zepto product-performance failed for city {city_id}: {e}")
            if failed is not None:
                failed.append(city_id)
        if i < len(targets):
            await asyncio.sleep(0.6)

    logger.debug(
        f"Zepto product-performance by city [{date_from}..{date_to}]: "
        f"{len(out)}/{len(targets)} cities with sales"
    )
    return out


# ── Ads (`ads-bff`) ──────────────────────────────────────────────────────────
# ads-bff needs the AWS WAF token on top of the session; the shared Zepto client
# holds it and re-mints it on a 202/429 (seller/client.py),
# so these are plain HTTP calls with no browser of their own.

# ads-bff answers a small share of calls with a bare 500 and then answers the
# identical call cleanly a minute later. Measured across the 2026-09-11 backfill:
# 4 of 76 fetches on one pass, 2 of 76 on the next, 0 on the third — never the
# same table twice. Before this, one such 500 lost that table for the day, the
# ads section reported "incomplete", and the job exited 1 — three of the first
# four scheduled VM runs. Waits are short because the fault clears in seconds,
# not the minutes the PO endpoints need (_PO_RETRY_WAITS_S).
_ADS_RETRY_WAITS_S = (3, 8, 20)


async def _ads_request(client, method: str, path: str, label: str, **kw) -> httpx.Response:
    """client.request + raise_for_status, retrying 5xx. The client already
    handles 202/429 (re-mint) and 401 (re-login); this covers the one class it
    passes through untouched."""
    async def _once() -> httpx.Response:
        resp = await client.request(method, path, **kw)
        if resp.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"{resp.status_code} from {path}", request=resp.request, response=resp
            )
        resp.raise_for_status()
        return resp

    return await retry_call(_once, waits=_ADS_RETRY_WAITS_S, retry_if=_is_5xx,
                            label=f"Zepto ads {label}")


async def fetch_ad_campaigns(
    client, brand_id: str, date_from: str, date_to: str, category: str
) -> list[dict]:
    """Every campaign in one category for a window, following pagination.

    The response carries `total_count` and `has_next`; rows come 10 at a time,
    so a brand with 26 campaigns is three calls.
    """
    by_id: dict = {}
    total = None
    page = 1
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
        # Through the client: a 202/429 re-mints the WAF token and retries,
        # a 401 re-logs in and retries. This loop used to raise on 202 and
        # ask a human to re-run.
        resp = await _ads_request(
            client, "GET", ep.ADS_CAMPAIGNS_API, f"campaigns p{page}", params=params
        )
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
        logger.debug(
            f"Zepto ad campaigns [{category}] [{date_from}]: {len(out)} campaigns but every "
            "metric is empty — not computed yet, ads-bff's transient blank, or no spend at all; "
            "the caller retries once and then decides (cli _zepto_blank_ads_day)"
        )

    logger.debug(f"Zepto ad campaigns [{category}] [{date_from}..{date_to}]: {len(out)} of {total}")
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


async def fetch_ads_tabular(
    client,
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
        # A 202 that survives the client has already been retried with a
        # re-minted token, so it is a real failure rather than a stale one.
        # 5xx is retried in _ads_request.
        resp = await _ads_request(
            client, "POST", ep.ADS_TABULAR_API, f"{view} p{page}", json=body
        )
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

    logger.debug(f"Zepto ads {view} [{date_from}..{date_to}]: {len(out)} rows")
    return out


async def fetch_campaign_keywords(
    client, brand_id: str, campaign_id: int, day: str, category: str = "sponsored_products"
) -> list[dict]:
    """One campaign's keyword performance for ONE day — `keyword_table` rows (P38).

    One day per call on purpose: a longer window comes back as a single total per keyword
    (no date in the rows), and a per-day breakdown is refused — probed 2026-10-06. Only
    keywords with activity are returned, so a campaign with no impressions that day has
    nothing to fetch (the caller skips it). Paged like `fetch_ads_tabular`, bounded by
    `total_count`; a page holds 50 and one campaign-day has rarely more than a dozen.
    """
    out: list[dict] = []
    page = 1
    while True:
        body = {
            "from": f"{day} 00:00:00",
            "to": f"{day} 23:59:59",
            "view": ep.ADS_VIEW_KEYWORD,
            "size": ep.ADS_TABULAR_PAGE_SIZE,
            "page": page,
            "campaign_category": category,
            "brand_id": brand_id,
            "campaign_id": campaign_id,
        }
        resp = await _ads_request(
            client, "POST", ep.ADS_CAMPAIGN_TABULAR_API,
            f"campaign {campaign_id} keywords p{page}", json=body,
        )
        data = resp.json().get("data") or {}
        rows = data.get("rows") or []
        out.extend(rows)
        if not rows or len(out) >= (data.get("total_count") or 0):
            break
        page += 1
        await asyncio.sleep(1.5)
    logger.debug(f"Zepto campaign {campaign_id} keywords [{day}]: {len(out)} rows")
    return out


# ── Campaign reads (shared with the campaign manager) ───────────────────────
#
# The four reads the catalogue needs, defined once here. The campaign manager re-exports
# them (`campaign_manager/marketplaces/zepto/client.py`) — its write path builds every
# budget / bid PUT from `get_campaign_detail` and verifies against it — so the scrape
# owns the reads and no longer imports the campaign manager.

def unwrap(body: dict) -> dict:
    """Zepto's response envelope. Most endpoints wrap in `data`; the campaign DETAIL does
    not — a real inconsistency, handled once here rather than at every call site."""
    inner = body.get("data")
    return inner if isinstance(inner, dict) else body


# A bound, not an expectation: rows come ~10 a page, so 30 pages = ~300 campaigns.
_MAX_PAGES = 30


async def get_campaigns(client, days: int = 90) -> list[dict]:
    """Every campaign on the account (all tabs — `categoryType` is ignored), all pages.

    ⚠️ The list is DATE-SCOPED. A narrow window silently omits campaigns rather than
    erroring, so anything reading this to decide "what exists" must pass a generous
    window — the same hazard `cm sync-campaigns` guards with MIN_DAYS on Blinkit.

    ⚠️ PAGED, and `limit` is ignored: this used to ask once with `limit=200` and got the
    first page only (a recorded dashboard call: 8 of 21, `has_next: true`). Only `page`
    works (1-based). The loop stops on `total_count`, on a page that adds no new ids, or
    at `_MAX_PAGES`: `has_next` alone has been seen staying true after the last campaign.
    """
    today = now_ist().date()
    by_id: dict = {}
    total = None
    for page in range(1, _MAX_PAGES + 1):
        params = {
            "selectedBrand": client.brand_id,
            "brand_id": client.brand_id,
            "categoryType": "sponsored_products",
            "campaign_category": "sponsored_products",
            "from_date": str(today - timedelta(days=days)),
            "to_date": str(today),
            "page": str(page),
            "sort_field": "nudges",
            "sort_order": "ASC",
            "date_field": "",
            "campaign_sub_types": "",
        }
        data = unwrap(await client.get_json(ep.ADS_CAMPAIGNS_API, params=params))
        rows = data.get("campaigns") or []
        if total is None:
            total = data.get("total_count")
        before = len(by_id)
        for r in rows:
            if r.get("campaign_id") is not None:
                by_id[r["campaign_id"]] = r
        if not rows or len(by_id) == before or (total and len(by_id) >= total):
            break
    campaigns = list(by_id.values())
    if total and len(campaigns) < total:
        logger.warning(f"Zepto returned {len(campaigns)} of {total} campaigns — paging "
                       "stopped early; treat this as a partial account.")
    return campaigns


async def get_keyword_floors(client, keywords: list[tuple[str, str]]
                             ) -> dict[tuple[str, str], int]:
    """Zepto's minimum bid per `(keyword, match_type)` — one request per
    `ep.KEYWORD_CONFIG_MAX` keywords (Zepto refuses a larger list with a 400).

    `POST /ads-bff/api/v1/keyword/config` {"keywords": [{keyword, match_type}]} →
    {"keywords": [{keyword, match_type, min_bid}]}. The direct analogue of Blinkit's
    `keywords/attributes`. Answers EXACT, PHRASE and BROAD (verified 2026-09-21).

    A keyword Zepto leaves out is simply ABSENT from the result. Absent means "unknown",
    never "no floor" — `pink toffee` was once absent and a write was still refused at ₹10.
    """
    out: dict[tuple[str, str], int] = {}
    for i in range(0, len(keywords), ep.KEYWORD_CONFIG_MAX):
        batch = keywords[i:i + ep.KEYWORD_CONFIG_MAX]
        body = {"keywords": [{"keyword": k, "match_type": m} for k, m in batch]}
        r = await client.request("POST", ep.ADS_KEYWORD_CONFIG_API, json=body)
        if r.status_code != 200:
            raise RuntimeError(f"Zepto keyword/config -> {r.status_code}: {r.text[:200]}")
        for k in (r.json() or {}).get("keywords") or []:
            if k.get("keyword") and k.get("match_type") and k.get("min_bid") is not None:
                try:
                    out[(k["keyword"], k["match_type"])] = int(round(float(k["min_bid"])))
                except (TypeError, ValueError):
                    continue
    return out


async def get_campaign_detail(client, campaign_id: int) -> dict:
    """One campaign's full configuration — the input to every campaign-manager write.

    NOT wrapped in `data`, unlike most Zepto responses.
    """
    return unwrap(await client.get_json(ep.ADS_CAMPAIGN_PLA_API.format(id=campaign_id)))


async def get_targeting_options(client, *, campaign_type: str = "PLA",
                                campaign_sub_type: str = "AUCTION_UP_SELL") -> dict:
    """The brand's targeting vocabulary — `cities[{id, name}]` and categories.

    Needed by the catalogue, to turn a campaign's city ids into names, and by the campaign
    manager's `translate.to_put` (an all-cities campaign's PUT carries the full city list).

    ⚠️ The params are the dashboard's own, and ALL of them matter (ZC-A12). With only
    `brand_id` the endpoint answers 200 with `{"cities": [], "categories": []}` —
    verified live 2026-09-21: 0 cities that way, 9 this way.
    """
    return await client.get_json(ep.ADS_TARGETING_OPTIONS_API, params={
        "brand_id": client.brand_id,
        "include": "category,geo",
        "campaign_type": campaign_type or "PLA",
        "campaign_sub_type": campaign_sub_type or "AUCTION_UP_SELL",
    })


# ── Campaign CATALOGUE ──────────────────────────────────────────────────────
#
# What every campaign is configured to do NOW — for `zepto_ad_campaigns` /
# `zepto_ad_campaign_keywords`, the campaign manager's catalogue. Zepto's answer to what
# Blinkit's marketing scrape does for `blinkit_ad_campaigns`. Built from the shared reads
# above, so the list's paging, `targeting-options`' params and the detail read are the
# same ones the write path uses.

CATALOG_WINDOW_DAYS = 90          # the list is date-scoped; same window `cm sync` uses
# Between per-campaign detail reads. Was 0.4: Sereko's ~60 campaigns at that pace drew
# Zepto's own 429 "rate limit exceeded" seven times in 90 s (P53, 2026-10-05). 1.5 s matches
# the per-day pace the rest of the ads section keeps.
_CATALOG_GAP_S = 1.5


async def fetch_campaign_catalog(client) -> dict:
    """The whole account's configuration. Read-only.

    1. the campaign list (all pages) — every campaign, with its CURRENT status;
    2. for each PLA campaign, its detail — targeting, products, keywords — and one
       `keyword/config` call for its bidding keywords' minimum bids;
    3. `targeting-options` per campaign type, for city names.

    ~2 requests per PLA campaign. A detail read that fails is retried once after the rest;
    what still fails is returned in `failed` (the caller decides — the scrape fails the run
    so it alerts). Such a campaign still gets its LIST row, and keeps whatever detail the
    last good read stored.
    """
    campaigns = await get_campaigns(client, days=CATALOG_WINDOW_DAYS)
    pla = [c for c in campaigns
           if (c.get("campaign_type") or "").upper() == "PLA" and c.get("campaign_id")]

    details: dict[int, dict] = {}
    floors: dict[int, dict] = {}
    city_names: dict[str, str] = {}
    seen_types: set[tuple[str, str]] = set()

    async def _one(cid: int) -> None:
        detail = await get_campaign_detail(client, cid)
        # The bidding pairs — negatives carry no bid (as `translate.bids_from_detail`).
        pairs = sorted({(k["keyword"], k["match_type"])
                        for k in detail.get("keyword_config") or [] if not k.get("is_negative")})
        floors[cid] = await get_keyword_floors(client, pairs) if pairs else {}
        key = (detail.get("campaign_type") or "PLA",
               detail.get("campaign_sub_type") or "AUCTION_UP_SELL")
        if key not in seen_types:
            seen_types.add(key)
            opts = await get_targeting_options(client, campaign_type=key[0],
                                               campaign_sub_type=key[1])
            for c in (opts.get("data", opts) or {}).get("cities") or []:
                if c.get("id"):
                    city_names[c["id"]] = c.get("name")
        details[cid] = detail

    failed: list[int] = []
    for raw in pla:
        try:
            await _one(int(raw["campaign_id"]))
        except Exception as e:
            logger.debug(f"Zepto catalogue: campaign {raw['campaign_id']} detail failed ({e})")
            failed.append(int(raw["campaign_id"]))
        await asyncio.sleep(_CATALOG_GAP_S)

    if failed:
        await asyncio.sleep(10)
        still = []
        for cid in failed:
            try:
                await _one(cid)
            except Exception as e:
                logger.debug(f"Zepto catalogue: campaign {cid} detail failed again ({e})")
                still.append(cid)
            await asyncio.sleep(_CATALOG_GAP_S)
        failed = still

    logger.debug(f"Zepto catalogue: {len(campaigns)} campaign(s), {len(details)} with detail, "
                f"{len(failed)} detail read(s) failed")
    return {"campaigns": campaigns, "details": details, "floors": floors,
            "city_names": city_names, "failed": failed}
