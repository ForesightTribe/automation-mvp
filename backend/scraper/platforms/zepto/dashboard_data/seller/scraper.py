import httpx
from playwright.async_api import async_playwright

from scraper.platforms.zepto.dashboard_data.seller import endpoints as ep
from scraper.utils.browser import create_browser_context
from app.utils.logger import logger


def _extract_auth(storage_state: dict) -> tuple[str, str] | None:
    """Pull the JWT and WAF token straight out of the saved cookies — no
    browser needed. Confirmed live (DevTools + captured requests) that
    Zepto's frontend sends these cookie values verbatim as the `authorization`
    and `x-aws-waf-token` headers on every API call, so replaying them here
    is equivalent to what the real page does."""
    jwt = None
    waf_token = None
    for c in storage_state.get("cookies", []):
        name = c.get("name", "")
        if name.endswith("_AUTH_TOKEN"):
            jwt = c.get("value")
        elif name == "aws-waf-token":
            waf_token = c.get("value")
    if not jwt or not waf_token:
        return None
    return jwt, waf_token


def _headers_for(jwt: str, waf_token: str) -> dict:
    return {
        "authorization": jwt,
        "x-aws-waf-token": waf_token,
        "x-proxy-target": "brand-analytics",
        "accept": "application/json",
    }


async def validate(storage_state: dict) -> tuple[bool, str | None]:
    """Cheap, browser-free check: is this saved session still accepted by
    Zepto's API? Deliberately avoids launching a browser at all — a headless
    page load was observed (live) to trigger AWS WAF's bot-challenge flow,
    so routine health checks use a single plain HTTP request instead, which
    looks like any other API call rather than a fresh browser session."""
    auth = _extract_auth(storage_state)
    if not auth:
        return False, "Saved session is missing the auth or WAF-token cookie"
    jwt, waf_token = auth

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{ep.BASE_URL}{ep.USER_INFO_API}", headers=_headers_for(jwt, waf_token), timeout=15)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if resp.status_code == 200:
        logger.info("Zepto seller session validation: OK")
        return True, None

    error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    logger.warning(f"Zepto seller session validation failed: {error}")
    return False, error


# ── ID discovery ─────────────────────────────────────────────────────────────
# Zepto's Sales Analytics API rejects calls that don't specify brand/city/
# subcategory IDs ("At least one City id is required") — these are specific
# to each tenant's own account, so they can't be hardcoded for a general
# scraper. Re-discovered fresh on every call (not cached) — same "no caching"
# choice Blinkit's own Scorecard scraper makes for its manufacturer_id, after
# weighing it against a cached-mapping design that risked silently missing
# newly-added cities/brands/categories. Both calls are plain httpx, no
# browser, same as validate() above.

async def discover_ids(storage_state: dict) -> dict:
    auth = _extract_auth(storage_state)
    if not auth:
        raise RuntimeError("Saved session is missing the auth or WAF-token cookie")
    jwt, waf_token = auth
    headers = _headers_for(jwt, waf_token)

    async with httpx.AsyncClient() as client:
        city_resp, brand_resp = await client.get(
            f"{ep.BASE_URL}{ep.CITY_LIST_API}", headers=headers, timeout=15
        ), await client.get(
            f"{ep.BASE_URL}{ep.BRAND_CATEGORY_MAPPING_API}", headers=headers, timeout=15
        )
    city_resp.raise_for_status()
    brand_resp.raise_for_status()

    city_ids = [c["cityID"] for c in city_resp.json()["data"]["cityList"]]

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

async def _recapture_auth_via_browser(storage_state: dict) -> tuple[str, str] | None:
    captured: dict = {}

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=True, storage_state=storage_state)
        page = await context.new_page()

        async def on_request(request):
            if "fcc.zepto.co.in" in request.url and not captured:
                hdrs = dict(request.headers)
                if hdrs.get("authorization") and hdrs.get("x-aws-waf-token"):
                    captured.update(hdrs)

        page.on("request", on_request)
        try:
            await page.goto(
                f"https://brands.zepto.co.in{ep.SALES_ANALYTICS_PAGE}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if not captured:
                import asyncio
                await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"Browser fallback page load warning: {e}")
        finally:
            await browser.close()

    if not captured:
        return None
    return captured["authorization"], captured["x-aws-waf-token"]


def classify_sales_error(status_code: int) -> str:
    """Auth-shaped failures (401/403) are the only ones a browser fallback
    could plausibly fix — everything else (bad params, rate limit, server
    error, timeout) needs a different response, not a browser touch."""
    if status_code in (401, 403):
        return "auth"
    return "other"


async def _get_with_auth_fallback(storage_state: dict, url: str, params: dict, label: str) -> dict:
    """Shared GET-with-fallback logic for every Sales Analytics call: try
    browser-free first, and only if it comes back 401/403 (auth-shaped),
    retry once via a live browser header re-capture. Any other error surfaces
    immediately — no fallback, since a browser touch can't fix a bad
    parameter, a rate limit, a server error, or a timeout."""
    auth = _extract_auth(storage_state)
    if not auth:
        raise RuntimeError("Saved session is missing the auth or WAF-token cookie")
    jwt, waf_token = auth

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers_for(jwt, waf_token), params=params, timeout=30)

    if resp.status_code >= 400:
        error_kind = classify_sales_error(resp.status_code)
        if error_kind == "auth":
            logger.warning(f"{label} got {resp.status_code}, attempting browser fallback re-capture...")
            recaptured = await _recapture_auth_via_browser(storage_state)
            if recaptured:
                jwt, waf_token = recaptured
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers=_headers_for(jwt, waf_token), params=params, timeout=30)
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"Session appears genuinely dead — re-login required "
                        f"(browser fallback also failed: HTTP {resp.status_code})"
                    )
            else:
                raise RuntimeError(
                    "Session appears genuinely dead — re-login required "
                    "(browser fallback could not capture fresh auth headers)"
                )
        else:
            resp.raise_for_status()  # not auth-shaped — surface the real error, no fallback

    resp.raise_for_status()
    return resp.json()["data"]


async def fetch_sales_overview(storage_state: dict, date_from: str, date_to: str, ids: dict) -> dict:
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
        storage_state, f"{ep.BASE_URL}{ep.SALES_OVERVIEW_API}", params, "Sales-overview"
    )
    gmv = data["headers"]["gmv"]["value"]
    units = data["headers"]["units"]["value"]
    daily = data["metrics"]["gmv"]["data"]
    logger.info(f"Zepto sales-overview [{date_from}..{date_to}]: GMV={gmv} Units={units} ({len(daily)} days)")
    return data


async def fetch_product_performance(
    storage_state: dict, date_from: str, date_to: str, ids: dict, limit: int = 50
) -> list[dict]:
    """Per-SKU breakdown from Zepto's Sales Analytics — GMV, units, sales
    share, growth, and conversion metrics per product. NOTE: observed live
    that the returned products' GMV doesn't fully reconcile against
    fetch_sales_overview's total (~3% gap seen in one test) — likely at
    least one SKU/variant excluded from this list for an unknown reason.
    stockOnHand always came back null, consistent with the Stock View
    paywall found elsewhere in the portal."""
    params = {
        "viewType": "top_selling",
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
        storage_state, f"{ep.BASE_URL}{ep.PRODUCT_PERFORMANCE_API}", params, "Product-performance"
    )
    products = data["data"]
    logger.info(f"Zepto product-performance [{date_from}..{date_to}]: {len(products)} products")
    return products
