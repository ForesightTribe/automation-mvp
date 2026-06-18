from typing import Any
from urllib.parse import quote

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.cities import CITIES
from scraper.utils.search_result import HEADERS_COMMON, norm_price

# Headers Blinkit attaches to every /v1/layout/search request — session-bound,
# captured from the browser's own request and replayed via in-page fetch().
_SEARCH_HEADER_KEYS = (
    "accept", "accept-language", "app_client", "app_version", "auth_key",
    "content-type", "device_id", "session_uuid", "web_app_version",
    "rn_bundle_version", "lat", "lon", "access_token",
)
_SEARCH_BODY = {"applied_filters": None, "sort": ""}


def _parse_snippets(body: dict) -> list[dict]:
    """Parse a /v1/layout/search response — products are snippets with atc_action."""
    products = []
    snippets = (body.get("response") or {}).get("snippets", [])
    for sn in snippets:
        d = sn.get("data", {})
        if "atc_action" not in d or "name" not in d:
            continue
        name = (d.get("name") or {}).get("text", "")
        price_text = (d.get("normal_price") or {}).get("text", "")
        inventory = d.get("inventory", 0)
        if name:
            products.append({
                "name": name,
                "price": norm_price(price_text),
                "position": len(products) + 1,
                "in_stock": inventory != 0,
            })
    return products


async def _fetch_playwright(keyword: str, lat: float, lon: float) -> list[dict]:
    """
    Open blinkit.com with lat/lon in the URL to establish location context.
    Capture the session-bound request headers from Blinkit's own /v1/layout/search
    call, then replay them via in-page fetch() — requests originate from the real
    browser session so Cloudflare passes them.
    """
    products = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            ctx = await browser.new_context(
                user_agent=HEADERS_COMMON["User-Agent"],
                locale="en-IN",
                geolocation={"latitude": lat, "longitude": lon},
                permissions=["geolocation"],
            )
            page = await ctx.new_page()
            captured: dict[str, str] = {}

            async def _on_req(req):
                if "blinkit.com/v1/layout/search" in req.url and not captured:
                    captured.update(req.headers)

            page.on("request", _on_req)

            # ── 1. Homepage with lat/lon sets Blinkit's location context ─────
            try:
                await page.goto(
                    f"https://blinkit.com/?lat={lat}&lon={lon}",
                    wait_until="networkidle", timeout=20000,
                )
                await page.wait_for_timeout(1000)
                logger.debug(f"Blinkit PW: homepage loaded, title='{await page.title()}'")
            except PWTimeout:
                logger.debug("Blinkit PW: homepage timeout")

            # ── 2. Warmup search triggers a real /v1/layout/search request ───
            # We navigate to capture the session headers; the results are discarded.
            try:
                await page.goto(
                    "https://blinkit.com/s/?q=water",
                    wait_until="networkidle", timeout=20000,
                )
                await page.wait_for_timeout(1500)
                logger.debug(f"Blinkit PW: warmup search done, captured={len(captured)} headers")
            except PWTimeout:
                logger.debug("Blinkit PW: warmup search timeout")

            page.remove_listener("request", _on_req)

            fetch_headers = {k: captured[k] for k in _SEARCH_HEADER_KEYS if k in captured}
            logger.debug(f"Blinkit PW: session headers captured: {list(fetch_headers.keys())}")

            if not fetch_headers:
                logger.warning("Blinkit PW: no session headers captured — cannot make in-page fetch")
                await browser.close()
                return []

            # Override lat/lon for this specific zone
            fetch_headers["lat"] = str(lat)
            fetch_headers["lon"] = str(lon)

            # ── 3. In-page POST — bypasses Cloudflare, uses browser session ──
            url = f"https://blinkit.com/v1/layout/search?q={quote(keyword)}&search_type=type_to_search"
            resp = await page.evaluate(
                """async ({url, h, b}) => {
                    try {
                        const r = await fetch(url, {
                            method: "POST",
                            headers: h,
                            credentials: "include",
                            body: JSON.stringify(b),
                        });
                        return {status: r.status, body: await r.json()};
                    } catch (e) {
                        return {status: 0, body: null, error: e.toString()};
                    }
                }""",
                {"url": url, "h": fetch_headers, "b": _SEARCH_BODY},
            )

            status = resp.get("status")
            body = resp.get("body") or {}
            logger.debug(f"Blinkit PW search: status={status} body_keys={list(body.keys())[:6]}")

            if status == 200:
                products = _parse_snippets(body)
                logger.debug(f"Blinkit PW: {len(products)} products from /v1/layout/search")
            else:
                logger.warning(
                    f"Blinkit PW: in-page fetch returned {status} "
                    f"error={resp.get('error', '')}"
                )

            await browser.close()
    except Exception as e:
        logger.warning(f"Blinkit Playwright failed for '{keyword}': {e}")
    return products


async def scrape(
    keyword: str,
    brand_slug: str,
    city_slug: str = "bengaluru",
    zone: str = "",
    pincode: str = "",
    lat: float | None = None,
    lon: float | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    city = CITIES.get(city_slug, CITIES["bengaluru"])
    _lat = lat if lat is not None else city["lat"]
    _lon = lon if lon is not None else city["lon"]
    _pincode = pincode or city["pincode"]

    products = await _fetch_playwright(keyword, _lat, _lon)
    if not products:
        logger.warning(
            f"Blinkit: no products found for '{keyword}' in {city['name']}"
            f"{f'/{zone}' if zone else ''}"
        )

    return {
        "platform": "blinkit",
        "keyword": keyword,
        "brand_slug": brand_slug,
        "city": city_slug,
        "zone": zone,
        "pincode": _pincode,
        "lat": _lat,
        "lon": _lon,
        "aliases": aliases,
        "products": products,
    }
