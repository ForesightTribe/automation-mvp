from typing import Any
from urllib.parse import quote

import httpx
from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.cities import CITIES
from scraper.utils.search_result import HEADERS_COMMON, dig_list, norm_price

_HEADERS = {
    **HEADERS_COMMON,
    "Referer": "https://www.zepto.now/",
    "Origin": "https://www.zepto.now",
}


async def _fetch_api(keyword: str) -> list[dict]:
    url = (
        f"https://api.zepto.now/api/v1/search"
        f"?query={quote(keyword)}&layout=SEARCH&page=1&pageSize=30"
    )
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers=_HEADERS)
            if r.status_code == 200:
                body = r.json()
                items = dig_list(body, ["data", "products", "items", "searchResults", "results"])
                products = []
                for i, obj in enumerate(items[:30]):
                    name = (
                        obj.get("productName") or obj.get("name") or obj.get("title") or ""
                    )
                    price = norm_price(str(
                        obj.get("price") or obj.get("discountedPrice") or obj.get("sellingPrice") or ""
                    ))
                    if name:
                        products.append({"name": name, "price": price, "position": i + 1, "in_stock": True})
                if products:
                    return products
        except Exception:
            pass
    return []


async def _fetch_playwright(keyword: str, lat: float, lon: float) -> list[dict]:
    products = []
    url = f"https://www.zepto.now/search?query={quote(keyword)}"
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
            intercepted: list[dict] = []

            async def _on_resp(resp):
                if any(x in resp.url for x in ["search", "catalog", "product"]) and \
                   "json" in resp.headers.get("content-type", ""):
                    try:
                        intercepted.append(await resp.json())
                    except Exception:
                        pass

            page.on("response", _on_resp)
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(3000)
            except PWTimeout:
                pass

            for body in intercepted:
                items = dig_list(body, ["data", "products", "items", "results"])
                for i, obj in enumerate(items[:30]):
                    name = obj.get("productName") or obj.get("name") or ""
                    if name:
                        products.append({
                            "name": name,
                            "price": norm_price(str(obj.get("price", ""))),
                            "position": i + 1,
                            "in_stock": True,
                        })
                if products:
                    break

            if not products:
                for sel in [
                    '[class*="ProductCard"]',
                    '[class*="product-card"]',
                    '[data-testid="product-card"]',
                ]:
                    els = await page.query_selector_all(sel)
                    for i, el in enumerate(els[:30]):
                        try:
                            name_el = await el.query_selector('h3, [class*="name"], [class*="Name"]')
                            name = (await name_el.inner_text()).strip() if name_el else ""
                            if name:
                                products.append({"name": name, "price": 0.0, "position": i + 1, "in_stock": True})
                        except Exception:
                            pass
                    if products:
                        break

            await browser.close()
    except Exception as e:
        logger.warning(f"Zepto Playwright failed for '{keyword}': {e}")
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

    products = await _fetch_api(keyword)
    if not products:
        logger.info(
            f"Zepto API empty for '{keyword}' in {city['name']}"
            f"{f'/{zone}' if zone else ''}, trying Playwright"
        )
        products = await _fetch_playwright(keyword, _lat, _lon)
    if not products:
        logger.warning(
            f"Zepto: no products found for '{keyword}' in {city['name']}"
            f"{f'/{zone}' if zone else ''}"
        )

    return {
        "platform": "zepto",
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
