"""Zepto public search scraper.

Flow: open one browser session per location, resolve that coordinate to its dark
store ONCE, then run many keyword searches by replaying the session-bound headers.
The session is reused across keywords — the browser warmup is paid once per
location, not once per search.

`scraper.py` returns raw extracted fields; `parser.py` types/classifies them.

TWO THINGS THAT MAKE ZEPTO DIFFERENT FROM BLINKIT
-------------------------------------------------
1. A search binds to a store by HEADER, not by coordinate. Sending lat/lon is
   accepted and silently ignored: you get a valid 200 carrying a generic catalog.
   The provider interface hands us lat/lon, so `_make_session` resolves it to a
   store id via get_page once, caches it on the session, and every search replays
   that. Resolving per search would spend get_page's separate, independently
   rate-limited budget on every call.

2. Zepto enforces a per-IP VOLUME cap, not just a rate. Blinkit's transient 403s
   self-resolve on backoff; Zepto's blocks are real, and retrying into one
   prolongs it. So `_replay_fetch` retries transport failures but returns
   immediately on a block status, and the caller is expected to back off.
   See endpoints.py for the measurements behind every tunable.
"""
import asyncio
import json
from typing import Any

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.cities import CITIES
from scraper.utils.search_result import HEADERS_COMMON
from scraper.platforms.zepto.public_data import endpoints as ep


# ── Extraction ───────────────────────────────────────────────────────────────

def _num(v, divisor: int = 1):
    """Zepto's numerics arrive as ints (prices in paise), or occasionally None."""
    try:
        return float(v) / divisor if v is not None else None
    except (TypeError, ValueError):
        return None


def _extract_product(item: dict) -> dict | None:
    """One search item -> flat raw dict in the SHARED key names the provider
    contract requires. None for anything without a product payload.

    Translating Zepto's vocabulary into the shared names happens here, never in a
    caller — that is the contract in scraper/public/providers.py.
    """
    pr = item.get("productResponse") or {}
    if not pr:
        return None
    prod = pr.get("product") or {}
    pv = pr.get("productVariant") or {}
    name = prod.get("name") or ""
    if not name:
        return None

    rat = pv.get("ratingSummary") or {}
    # availableQuantity lives on productResponse itself, alongside price/mrp —
    # NOT on productVariant. Reading it off `pv` silently returned None for
    # every row (confirmed: 577/577 existing sku_snapshots rows have inventory
    # IS NULL), which in turn made `in_stock` always default to True below.
    qty = pr.get("availableQuantity")
    # position is 0-BASED in the payload; the shared contract is 1-based.
    pos_raw = item.get("position")
    position = (pos_raw + 1) if isinstance(pos_raw, int) else None

    images = prod.get("images")
    image_url = ""
    if isinstance(images, list) and images and isinstance(images[0], dict):
        image_url = images[0].get("path") or ""

    return {
        "product_id": str(prod.get("id") or pr.get("id") or ""),
        "variant_id": str(pv.get("id") or ""),
        "name": name,
        "brand": (prod.get("brand") or "").strip(),
        "price": _num(pr.get("discountedSellingPrice") or pr.get("sellingPrice"),
                      ep.PRICE_DIVISOR),
        "mrp": _num(pv.get("mrp") or pr.get("mrp"), ep.PRICE_DIVISOR),
        "unit": pv.get("formattedPacksize") or "",
        "inventory": qty,
        # Zepto states this explicitly (`outOfStock`) rather than leaving it to
        # be inferred from quantity — more direct, and doesn't depend on `qty`
        # being present. Missing the field defaults to in-stock, same fallback
        # as before, for whatever fraction of responses might omit it.
        "in_stock": not pr.get("outOfStock", False),
        "rating": _num(rat.get("averageRating")),
        "rating_count": rat.get("totalRatings"),
        "position": position,
        # Zepto is store-grain: each product names its fulfilling store (Q4).
        "merchant_id": str(pr.get("storeId") or ""),
        # No express/longtail tiering on Zepto — the column would be a constant.
        "merchant_type": "",
        "image_url": image_url,
        "category": {"l0": None, "l1": None,
                     "l2": (prod.get("l3CategoryIds") or [None])[0]},
    }


def _extract_products(body: dict, include_oos: bool = False) -> tuple[list[dict], bool]:
    """(products, hit_break) for one response page.

    `include_oos` adds the sold-out widget (see ep.PRODUCT_WIDGETS). It is OFF by
    default because the two scrapes want different answers from the same response:
    the targeted own-catalogue scrape needs the stockouts (a sold-out SKU is a supply
    problem, and dropping it makes the store look like it never stocked the product),
    while the keyword scrape measures rank and share of voice, where sold-out items
    sit in a separate below-the-fold block and are not part of the organic ranking.
    Turning it on unconditionally would silently move every SoV number.

    `or []`, NOT a .get default: Zepto sends "layout": null on a page past the end
    of the results. The key IS present, so .get("layout", []) hands back None and
    iterating it raises — a bug that spent two days being misread as a rate-limit
    block, because the exception was swallowed and the store reported as throttled.
    See docs/zepto_phase0_handover.md.

    `hit_break` is True when a section header ended the results. The caller must
    then STOP PAGING: once a response runs out of real matches, later pages
    continue the recommendation carousel rather than the search, and a 9-result
    query produced positions into the 60s.
    """
    out: list[dict] = []
    for w in (body.get(ep.LAYOUT_KEY) or []):
        wid = w.get("widgetId")
        # A section header ends the search results — what follows is a "Similar
        # Products" carousel, not ranks. See SECTION_BREAK_WIDGETS.
        if wid in ep.SECTION_BREAK_WIDGETS:
            return out, True
        wanted = ep.PRODUCT_WIDGETS if include_oos else {ep.PRODUCT_GRID_WIDGET}
        resolver = ((w.get("data") or {}).get("resolver") or {}).get("data") or {}
        if wid not in wanted:
            # Loud, because the cost of the OOS_SEARCH_WIDGET bug was not the missing
            # widget — it was that dropping it left no trace anywhere, so a whole
            # class of product looked like it had never existed. A new Zepto widget
            # carrying real items must announce itself, not vanish.
            n = len(resolver.get("items") or [])
            if (
                n
                and wid not in ep.PRODUCT_WIDGETS
                and wid not in ep.EXCLUDED_PRODUCT_WIDGETS
            ):
                logger.warning(
                    f"Zepto: unrecognised widget {wid!r} carrying {n} product(s) — "
                    f"dropped. Add it to endpoints.PRODUCT_WIDGETS if these are real "
                    f"results."
                )
            continue
        for it in (resolver.get("items") or []):
            p = _extract_product(it)
            if p:
                out.append(p)
    return out, False


def _pagination(page_no: int, collected: int, cap: int) -> int | None:
    """Next page number, or None to stop.

    Zepto pages by a body field rather than a next_url, and returns no total, so
    the stop conditions are the cap, MAX_PAGES, or an empty page (handled by the
    caller). Observed page size is 12-27, so a search normally costs 2-3 requests.
    """
    if collected >= cap or page_no + 1 >= ep.MAX_PAGES:
        return None
    return page_no + 1


# ── Fetch ────────────────────────────────────────────────────────────────────

# Zepto has no Cloudflare-class challenge (Q3), so Blinkit's in-page fetch() is
# not needed. Raw httpx IS blocked, but headers captured from a real browser
# session replay fine through Playwright's request context — ~0.33s per call
# versus ~3s for a page reload. The provider interface is identical either way;
# that is the point of D2.

async def _replay_fetch(session: dict, url: str, headers: dict, body: dict) -> dict:
    """POST with a hard per-attempt timeout, retrying TRANSPORT failures only.

    A block status returns immediately and is never retried: Zepto's cap is real,
    and retrying into an active block extends it. The timeout is enforced twice —
    the request's own, plus an asyncio.wait_for around it — so a wedged context can
    never hang a worker.
    """
    resp: dict = {"status": 0}
    for delay in (0.0,) + ep.RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            r = await asyncio.wait_for(
                session["context"].request.post(
                    url, headers=headers, data=json.dumps(body),
                    timeout=int(ep.FETCH_TIMEOUT_S * 1000)),
                timeout=ep.FETCH_TIMEOUT_S + 5,
            )
        except asyncio.TimeoutError:
            resp = {"status": 0, "error": "request timeout (context wedged)"}
            continue
        except Exception as e:
            resp = {"status": 0, "error": str(e)[:120]}
            continue

        if r.status in ep.BLOCK_STATUSES:
            return {"status": r.status, "body": None, "blocked": True,
                    "error": f"HTTP {r.status} (rate limited)"}
        if r.status == 200:
            try:
                return {"status": 200, "body": await r.json()}
            except Exception:
                # A 200 that will not parse is not a result. Keep retrying.
                resp = {"status": 200, "body": None, "error": "non-JSON body"}
                continue
        resp = {"status": r.status, "body": None, "error": f"HTTP {r.status}"}
    return resp


# ── Session lifecycle ────────────────────────────────────────────────────────

async def _capture(page, url_part: str, nav,
                   settle_ms: int = 9000) -> tuple[dict, str | None]:
    """Capture headers (and body) from the page's OWN request to `url_part`.

    The listener must outlive the navigation: Zepto fires these AFTER
    domcontentloaded, so removing it when goto() returns captures nothing. The
    poll below is load-bearing — do not 'simplify' it away.
    """
    cap: dict[str, Any] = {"h": None, "body": None}

    async def _on_req(req):
        if url_part in req.url and cap["h"] is None:
            cap["h"] = dict(req.headers)
            try:
                cap["body"] = req.post_data
            except Exception:
                pass

    page.on("request", _on_req)
    try:
        await nav()
        waited = 0
        while cap["h"] is None and waited < settle_ms:
            await page.wait_for_timeout(250)
            waited += 250
    except PWTimeout:
        logger.debug(f"Zepto: navigation timeout capturing {url_part}")
    except Exception as e:
        logger.debug(f"Zepto: capture failed for {url_part}: {e}")
    finally:
        page.remove_listener("request", _on_req)

    if not cap["h"]:
        return {}, None
    headers = {k: v for k, v in cap["h"].items()
               if k.lower() not in ep.DROP_HEADER_KEYS}
    return headers, cap["body"]


async def _resolve_store(session: dict, lat: float,
                         lon: float) -> tuple[str, tuple[str, ...]]:
    """Coordinate -> (store_id, secondary_ids). Called ONCE per session.

    Zepto binds searches by store id and the provider interface hands us a
    coordinate, so this bridges the two. Doing it per search would spend
    get_page's separate rate-limit budget on every call — which is exactly how an
    earlier version ran out of get_page budget while search was perfectly healthy.
    """
    try:
        r = await session["context"].request.get(
            ep.get_page_url(lat, lon), headers=session["gp_headers"],
            timeout=int(ep.FETCH_TIMEOUT_S * 1000))
        if r.status != 200:
            return "", ()
        d = await r.json()
        sr = d.get("storeServiceableResponse") or {}
        return str(sr.get("storeId") or ""), tuple(sr.get("secondaryStoreIds") or ())
    except Exception as e:
        logger.debug(f"Zepto: store resolve failed at {lat},{lon}: {e}")
        return "", ()


async def _make_session(browser, lat: float, lon: float) -> dict | None:
    """Isolated context on `browser`, warmed up, headers captured, coordinate
    resolved to a store. Returns the session dict or None."""
    ctx = await browser.new_context(
        user_agent=HEADERS_COMMON["User-Agent"], locale="en-IN")
    page = await ctx.new_page()
    session: dict[str, Any] = {"context": ctx, "page": page}

    gp_headers, _ = await _capture(
        page, ep.GET_PAGE_PATH,
        lambda: page.goto(ep.HOMEPAGE_URL, wait_until="domcontentloaded",
                          timeout=30000))
    session["gp_headers"] = gp_headers

    headers, raw_body = await _capture(
        page, ep.SEARCH_PATH,
        lambda: page.goto(ep.WARMUP_SEARCH_URL, wait_until="domcontentloaded",
                          timeout=30000))
    if not headers:
        logger.warning("Zepto: no session headers captured")
        await ctx.close()
        return None
    session["headers"] = headers
    # Keep the browser's own body so session fields (userSessionId) survive.
    try:
        session["body"] = json.loads(raw_body) if raw_body else dict(ep.SEARCH_BODY)
    except Exception:
        session["body"] = dict(ep.SEARCH_BODY)

    # Best-effort only. A caller that passes merchant_id per search never needs
    # this, and get_page has its own rate-limit budget — failing the whole session
    # here killed a worker for the rest of the run, losing 20% of a 5-worker pool
    # permanently. An unresolved store is fine; search() will set one.
    sid, secondaries = await _resolve_store(session, lat, lon)
    if not sid:
        logger.debug(f"Zepto: no store resolved at {lat},{lon} — session opens "
                     f"anyway; search() must supply merchant_id")
    session["store_id"] = sid
    session["secondary_ids"] = secondaries
    # Which coordinate the cached store belongs to. search() re-resolves when it is
    # handed a different one — see the note there.
    session["coord"] = (lat, lon)
    return session


async def open_session(pw, lat: float, lon: float) -> dict | None:
    """Launch a browser + one session (ad-hoc / single-worker use). The session
    OWNS the browser; close_session shuts it down."""
    browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
    session = await _make_session(browser, lat, lon)
    if not session:
        await browser.close()
        return None
    session["browser"] = browser  # owned
    return session


async def open_context_session(browser, lat: float, lon: float) -> dict | None:
    """One session as an isolated context on a SHARED browser (the worker pool).
    Does NOT own the browser — close_session only closes the context."""
    return await _make_session(browser, lat, lon)


async def close_session(session: dict) -> None:
    try:
        await session["context"].close()
        if session.get("browser"):  # only ad-hoc sessions own the browser
            await session["browser"].close()
    except Exception:
        pass


# ── Search ───────────────────────────────────────────────────────────────────

async def search(
    session: dict, keyword: str, cap: int = ep.RESULT_CAP,
    lat: float | None = None, lon: float | None = None,
    merchant_id: str | None = None,
    follow_similarity: bool = False,
    include_oos: bool = False,
) -> dict:
    """One keyword search in an open session, paging up to `cap`.

    RE-TARGETING. The worker pool opens one session per worker from a seed
    coordinate and then walks many stores through it, so the session's store must
    follow the store it is handed. Without that, every store in the run returns the
    SEED store's catalog — the Q2 silent failure: a valid 200 carrying the wrong
    store's data, with nothing in the response to say so.

    Prefer `merchant_id`: the caller is iterating catalog rows, so it already knows
    the store id and no lookup is needed. Falling back to `lat`/`lon` costs a
    get_page per store, and get_page has its OWN rate-limit budget — draining it
    while search is healthy is a failure mode this project has already hit once.

    `follow_similarity` is accepted and unused: Zepto has no basic->similarity
    relevance switch (Q6), so there is no tail to follow.

    Returns {products, total_results, merchant_id, ok, error, blocked}.
    """
    if merchant_id and merchant_id != session.get("store_id"):
        # Free: the catalog row IS the store. No get_page, no second budget.
        session["store_id"] = merchant_id
        session["secondary_ids"] = ()
        session["coord"] = (lat, lon)
    elif (not merchant_id and lat is not None and lon is not None
            and (lat, lon) != session.get("coord")):
        sid, secondaries = await _resolve_store(session, lat, lon)
        if not sid:
            return {"products": [], "total_results": 0, "merchant_id": "",
                    "ok": False, "blocked": False,
                    "error": f"no store resolved at {lat},{lon}"}
        session["store_id"] = sid
        session["secondary_ids"] = secondaries
        session["coord"] = (lat, lon)

    headers = {**session["headers"],
               **ep.store_headers(session["store_id"], session["secondary_ids"])}
    url = ep.search_url()

    products: list[dict] = []
    seen: set[str] = set()
    ok, error, blocked = False, "", False
    page_no: int | None = 0

    while page_no is not None and len(products) < cap:
        body = ep.search_body(keyword, page_no, session.get("body"))
        resp = await _replay_fetch(session, url, headers, body)
        if resp.get("blocked"):
            blocked = True
            error = resp.get("error", "blocked")
            break
        if resp.get("status") != 200 or resp.get("body") is None:
            error = resp.get("error") or f"HTTP {resp.get('status')}"
            logger.debug(f"Zepto search '{keyword}': {error}")
            break
        ok = True

        page_rows, hit_break = _extract_products(resp["body"], include_oos)
        if not page_rows:
            break  # genuinely nothing more for this term
        # Keep the FIRST sighting — it carries the true (best) rank.
        for p in page_rows:
            pid = p.get("variant_id") or p.get("product_id")
            if pid:
                if pid in seen:
                    continue
                seen.add(pid)
            products.append(p)

        # The results ended inside this page — anything further is the "Similar
        # Products" carousel, so there is no next page of search results to fetch.
        page_no = None if hit_break else _pagination(page_no, len(products), cap)

    products = products[:cap]
    # Fall back to running order where Zepto gave no position.
    for i, p in enumerate(products, 1):
        if p.get("position") is None:
            p["position"] = i
    return {
        "products": products,
        "total_results": len(products),
        # The session's store IS the merchant here — unlike Blinkit, where it has
        # to be read back off the products because one response spans several.
        "merchant_id": session.get("store_id", ""),
        "ok": ok, "error": error, "blocked": blocked,
    }


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
    The orchestrator reuses one session across keywords instead."""
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
        logger.warning(f"Zepto scrape failed for '{keyword}': {e}")

    if not products:
        logger.warning(
            f"Zepto: no products for '{keyword}' in {city['name']}"
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
        "merchant_id": merchant_id,
        "total_results": total_results,
        "products": products,
    }
