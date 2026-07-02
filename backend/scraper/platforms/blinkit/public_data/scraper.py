"""Blinkit public search scraper.

Flow: open one headless-browser session per location (captures Cloudflare
clearance + the session-bound headers once), then run many keyword searches as
in-page fetch() calls, paginating via Blinkit's own next_url. The session is
reused across keywords — the expensive browser warmup is paid once per location,
not once per search.

`scraper.py` returns raw extracted fields; `parser.py` types/classifies them.
"""
import asyncio
from typing import Any
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.cities import CITIES
from scraper.utils.search_result import HEADERS_COMMON, dig
from scraper.platforms.blinkit.public_data import endpoints as ep


# ── Extraction ───────────────────────────────────────────────────────────────

def _extract_product(snippet: dict) -> dict | None:
    """Pull one product card into a flat raw dict. Returns None for non-product
    snippets (banners, recommendations, etc.).

    Primary source is the typed `cart_item` (numeric price/mrp/inventory + brand);
    rank/category come from the sibling `tracking.common_attributes`.
    """
    data = snippet.get("data") or {}
    cart_item = dig(data, "atc_action", "add_to_cart", "cart_item")
    if not cart_item or not cart_item.get("product_name"):
        return None

    common = dig(snippet, "tracking", "common_attributes") or {}
    pos_raw = common.get("product_position")
    try:
        position = int(pos_raw) if pos_raw not in (None, "") else None
    except (TypeError, ValueError):
        position = None

    inventory = cart_item.get("inventory")
    in_stock = not data.get("is_sold_out", False) and bool(inventory)

    return {
        "product_id": str(cart_item.get("product_id") or ""),
        "name": cart_item.get("product_name") or "",
        "brand": cart_item.get("brand") or "",
        "price": cart_item.get("price"),
        "mrp": cart_item.get("mrp"),
        "unit": cart_item.get("unit") or "",
        "inventory": inventory,
        "in_stock": in_stock,
        "position": position,
        "group_id": cart_item.get("group_id"),
        "merchant_id": str(cart_item.get("merchant_id") or ""),
        "merchant_type": cart_item.get("merchant_type") or "",
        "image_url": cart_item.get("image_url") or "",
        "ptype": common.get("ptype"),
        "category": {
            "l0": common.get("l0_category"),
            "l1": common.get("l1_category"),
            "l2": common.get("l2_category"),
        },
        "match_reason": common.get("reason"),
    }


def _extract_products(body: dict) -> list[dict]:
    snippets = dig(body, "response", "snippets") or []
    out = []
    for sn in snippets:
        p = _extract_product(sn)
        if p:
            out.append(p)
    return out


def _pagination(body: dict) -> tuple[str | None, str | None, int | None]:
    """(next_url, search_method, search_count) from a response. The method and
    total live in the next_url query string."""
    next_url = dig(body, "response", "pagination", "next_url")
    if not next_url:
        return None, None, None
    qs = parse_qs(urlparse(next_url).query)
    method = (qs.get("search_method") or [None])[0]
    count_raw = (qs.get("search_count") or [None])[0]
    count = int(count_raw) if count_raw and count_raw.isdigit() else None
    return next_url, method, count


# ── In-page fetch (Cloudflare bypass) ────────────────────────────────────────

# AbortController caps the in-browser fetch so a stalled connection can't hang the
# worker forever — it aborts and surfaces as a normal transient failure for retry.
_FETCH_JS = """async ({url, h, b, timeoutMs}) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        const opts = {method: "POST", headers: h, credentials: "include", signal: ctrl.signal};
        if (b !== null) opts.body = JSON.stringify(b);
        const r = await fetch(url, opts);
        const text = await r.text();
        try {
            return {status: r.status, body: JSON.parse(text)};
        } catch (_) {
            // Non-JSON body: almost always a Cloudflare/HTML challenge. Keep the
            // real HTTP status so the retry loop + logs see it for what it is.
            return {status: r.status, body: null, error: "non-JSON body (Cloudflare?)"};
        }
    } catch (e) {
        return {status: 0, body: null, error: e.toString()};
    } finally {
        clearTimeout(t);
    }
}"""


# Transient 403/429/5xx/network blips happen mid-sweep and self-resolve, so
# retry with backoff. A 200 (even empty) is a real result and returns immediately.
_RETRY_DELAYS = (0.5, 1.5, 3.0)

# Per-attempt fetch ceiling. The JS AbortController enforces it in-browser; the
# asyncio.wait_for is a belt-and-suspenders guard for a wedged page process (the
# evaluate itself hanging), so the worker always unblocks.
_FETCH_TIMEOUT_S = 20.0


async def _in_page_fetch(page, url: str, headers: dict, body: dict | None) -> dict:
    """In-page fetch with a hard per-attempt timeout + retry/backoff on transient
    failures. Returns on the first 200; otherwise the last response after retries."""
    resp: dict = {"status": 0}
    payload = {"url": url, "h": headers, "b": body, "timeoutMs": int(_FETCH_TIMEOUT_S * 1000)}
    for delay in (0.0,) + _RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await asyncio.wait_for(
                page.evaluate(_FETCH_JS, payload),
                timeout=_FETCH_TIMEOUT_S + 5,
            )
        except asyncio.TimeoutError:
            resp = {"status": 0, "error": "evaluate timeout (page wedged)"}
            continue
        except Exception as e:
            resp = {"status": 0, "error": str(e)}
            continue
        # A 200 with a non-JSON body (Cloudflare challenge) is not a real result —
        # keep retrying rather than accepting it as an empty page.
        if resp.get("status") == 200 and resp.get("body") is not None:
            return resp
    return resp


# ── Session lifecycle ────────────────────────────────────────────────────────

async def _make_session(browser, lat: float, lon: float) -> dict | None:
    """Create an isolated context on `browser`, warm it up, and capture the
    session-bound search headers. Returns {context, page, headers} or None."""
    ctx = await browser.new_context(
        user_agent=HEADERS_COMMON["User-Agent"],
        locale="en-IN",
        geolocation={"latitude": lat, "longitude": lon},
        permissions=["geolocation"],
    )
    page = await ctx.new_page()
    captured: dict[str, str] = {}

    async def _on_req(req):
        if ep.SEARCH_PATH in req.url and not captured:
            captured.update(req.headers)

    page.on("request", _on_req)

    try:
        await page.goto(ep.HOMEPAGE_URL.format(lat=lat, lon=lon),
                        wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(1000)
    except PWTimeout:
        logger.debug("Blinkit: homepage timeout")
    try:
        await page.goto(ep.WARMUP_SEARCH_URL, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(1500)
    except PWTimeout:
        logger.debug("Blinkit: warmup timeout")

    page.remove_listener("request", _on_req)

    headers = {k: captured[k] for k in ep.SEARCH_HEADER_KEYS if k in captured}
    if not headers:
        logger.warning("Blinkit: no session headers captured")
        await ctx.close()
        return None

    headers["lat"] = str(lat)
    headers["lon"] = str(lon)
    return {"context": ctx, "page": page, "headers": headers}


async def open_session(pw, lat: float, lon: float) -> dict | None:
    """Launch a headless browser + one session (ad-hoc / single-worker use). The
    session owns the browser; close_session() shuts it down."""
    browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
    session = await _make_session(browser, lat, lon)
    if not session:
        await browser.close()
        return None
    session["browser"] = browser  # owned — closed by close_session
    return session


async def open_context_session(browser, lat: float, lon: float) -> dict | None:
    """One session as an isolated context on a SHARED browser (the concurrent
    pool). Does not own the browser — close_session() only closes the context."""
    return await _make_session(browser, lat, lon)


async def close_session(session: dict) -> None:
    try:
        await session["context"].close()
        if session.get("browser"):  # only ad-hoc sessions own the browser
            await session["browser"].close()
    except Exception:
        pass


async def search(
    session: dict, keyword: str, cap: int = ep.RESULT_CAP,
    lat: float | None = None, lon: float | None = None,
) -> dict:
    """Run one keyword search in an open session, paginating Blinkit's basic
    results up to `cap`. Pass `lat`/`lon` to target a specific store without
    reopening the session — Blinkit selects the dark store from the lat/lon
    headers. Returns {products, total_results, merchant_id, ok, error}; `ok` is
    False when the first fetch didn't return 200 (failed/unserviceable, not just
    empty), and `error` carries a short reason (HTTP status / exception text).
    """
    page = session["page"]
    headers = session["headers"]
    if lat is not None and lon is not None:
        headers = {**headers, "lat": str(lat), "lon": str(lon)}

    products: list[dict] = []
    total_results: int | None = None
    ok = False
    error = ""
    url: str | None = ep.first_search_url(keyword)
    body: dict | None = ep.SEARCH_BODY

    while url and len(products) < cap:
        resp = await _in_page_fetch(page, url, headers, body)
        if resp.get("status") != 200 or resp.get("body") is None:
            err_txt = resp.get("error", "")
            error = f"HTTP {resp.get('status')}" + (f" · {err_txt}" if err_txt else "")
            logger.debug(f"Blinkit search '{keyword}': {error}")
            break
        ok = True
        page_body = resp.get("body") or {}
        products.extend(_extract_products(page_body))

        next_url, method, count = _pagination(page_body)
        if total_results is None:
            total_results = count
        if not next_url or method != ep.BASIC_SEARCH_METHOD:
            break
        url = ep.BASE_URL + next_url
        body = None  # paged requests carry no body

    products = products[:cap]
    if total_results is None:
        total_results = len(products)
    # Fall back to running order where Blinkit didn't give a position.
    for i, p in enumerate(products, 1):
        if p.get("position") is None:
            p["position"] = i
    merchant_id = products[0]["merchant_id"] if products else ""
    return {"products": products, "total_results": total_results,
            "merchant_id": merchant_id, "ok": ok, "error": error}


# ── Public entrypoint (CLI-compatible) ───────────────────────────────────────

async def scrape(
    keyword: str,
    brand_slug: str,
    city_slug: str = "bengaluru",
    zone: str = "",
    pincode: str = "",
    lat: float | None = None,
    lon: float | None = None,
    aliases: list[str] | None = None,
    cap: int | None = None,
) -> dict[str, Any]:
    """Scrape one keyword at one location (opens + closes its own session).
    The orchestrator (Phase 5) will instead reuse one session across keywords."""
    city = CITIES.get(city_slug, CITIES["bengaluru"])
    _lat = lat if lat is not None else city["lat"]
    _lon = lon if lon is not None else city["lon"]
    _pincode = pincode or city["pincode"]
    _cap = cap if cap is not None else ep.RESULT_CAP

    products: list[dict] = []
    total_results = 0
    merchant_id = ""
    try:
        async with async_playwright() as pw:
            session = await open_session(pw, _lat, _lon)
            if session:
                try:
                    res = await search(session, keyword, _cap)
                    products = res["products"]
                    total_results = res["total_results"]
                    merchant_id = res["merchant_id"]
                finally:
                    await close_session(session)
    except Exception as e:
        logger.warning(f"Blinkit scrape failed for '{keyword}': {e}")

    if not products:
        logger.warning(
            f"Blinkit: no products for '{keyword}' in {city['name']}"
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
        "merchant_id": merchant_id,
        "total_results": total_results,
        "products": products,
    }
