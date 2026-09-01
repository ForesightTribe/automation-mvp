"""Zepto public search scraper.

Flow: open one browser session, then run many searches by replaying the
session-bound headers, swapping the store-id headers per store. The browser
warmup is paid once, not once per search.

`scraper.py` returns raw extracted fields; `parser.py` types/classifies them.

THREE THINGS THAT MAKE ZEPTO DIFFERENT FROM BLINKIT
---------------------------------------------------
1. **A search binds to a store by HEADER, not by coordinate.** Sending lat/lon is
   accepted and silently ignored: you get a valid 200 carrying a generic catalog.
   The provider interface hands us lat/lon, so `_make_session` resolves it to a
   store once and caches it; every caller that already knows the store passes
   `merchant_id` instead, which costs nothing.

2. **Three failure modes, three remedies.** See `endpoints.py`. The one that
   matters: a `202` session is dead FOREVER, so it is re-minted immediately
   rather than waited on. `299`/`429` clear themselves in ~60 s and are simply
   retried by the caller.

3. **The WAF pass expires after 4-6 minutes** and nothing on the page refreshes
   it. `_ensure_pass` re-mints on a timer, in place, so a long run never
   discovers the expiry as a wall of 202s.

A BLOCK IS NEVER AN EMPTY RESULT
--------------------------------
`search()` returns `ok=False` on any non-200. It must never return an empty
product list for a blocked request: the caller would record "this store has no
products" — a plausible, well-formed, wrong answer, and exactly the class of bug
that made the previous build's data untrustworthy.
"""
import asyncio
import json
import time
from typing import Any

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.cities import CITIES
from scraper.utils.search_result import HEADERS_COMMON
from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import packs


# ── Extraction ───────────────────────────────────────────────────────────────

def _num(v, divisor: int = 1):
    """Zepto's numerics arrive as ints (prices in paise), or occasionally None."""
    try:
        return float(v) / divisor if v is not None else None
    except (TypeError, ValueError):
        return None


def _extract_product(item: dict) -> dict | None:
    """One search item -> flat raw dict in the SHARED key names the provider
    contract requires.

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
    # availableQuantity lives on productResponse, NOT on productVariant. Reading
    # it off `pv` silently returned None for every row in the previous build,
    # which in turn made `in_stock` always default to True.
    qty = pr.get("availableQuantity")
    # position is 0-BASED in the payload; the shared contract is 1-based.
    pos_raw = item.get("position")
    position = (pos_raw + 1) if isinstance(pos_raw, int) else None

    images = pv.get("images") or prod.get("images")
    image_url = ""
    if isinstance(images, list) and images and isinstance(images[0], dict):
        image_url = images[0].get("path") or ""

    # Pack size, normalised HERE rather than in parser.py. `targeted.py` (the
    # own-SKU scrape) calls search() and never calls parse(), so normalising in
    # the parser would fix the keyword scrape and silently leave sku_snapshots
    # broken. `unit` is a shared-contract key, so the engine owns the translation.
    raw_unit = pv.get("formattedPacksize") or ""
    uom = pv.get("unitOfMeasure") or ""
    canon_unit = packs.canonical_unit(pv.get("packsize"), uom, raw_unit)

    return {
        "product_id": str(prod.get("id") or pr.get("id") or ""),
        "variant_id": str(pv.get("id") or ""),
        "name": name,
        "brand": (prod.get("brand") or "").strip(),
        "price": _num(pr.get("discountedSellingPrice") or pr.get("sellingPrice"),
                      ep.PRICE_DIVISOR),
        "mrp": _num(pv.get("mrp") or pr.get("mrp"), ep.PRICE_DIVISOR),
        # The shared `unit` key, in pack.py's grammar so `pack_fields()` works.
        # Falls back to Zepto's raw string when nothing is derivable, which
        # `pack_fields` then stores as pack_raw with empty derived columns.
        "unit": canon_unit or raw_unit,
        # Zepto's original, verbatim. A normaliser fix is a backfill from this,
        # never a re-scrape.
        "unit_raw": raw_unit,
        # Zepto's own COMBO marker, or a multipack multiplier in the string.
        # Independent of whether the size parsed.
        "is_combo_hint": packs.is_combo(uom, raw_unit),
        "inventory": qty,
        # Zepto states this explicitly rather than leaving it to be inferred from
        # quantity — more direct, and it does not depend on `qty` being present.
        "in_stock": not pr.get("outOfStock", False),
        "rating": _num(rat.get("averageRating")),
        "rating_count": rat.get("totalRatings"),
        "position": position,
        # Zepto is store-grain: each product names its fulfilling store.
        "merchant_id": str(pr.get("storeId") or ""),
        # No express/longtail tiering on Zepto — the column would be a constant.
        "merchant_type": "",
        "image_url": image_url,
        "category": {"l0": pr.get("primaryCategoryName"),
                     "l1": pr.get("primarySubcategoryName"),
                     "l2": (prod.get("l3CategoryIds") or [None])[0]},
        # Own-SKU rows carry these into sku_snapshots.extra. Deliberately NOT
        # promoted onto search_listings: at ~212k rows per national run the cost
        # is real, and Phase 0 found every ads/ranking field zeroed for
        # anonymous clients (is_fly_wheel_ad False on 557/557).
        "extra": {
            "brand_id": prod.get("brandId"),
            "country_of_origin": prod.get("countryOfOrigin"),
            "manufacturer": prod.get("manufacturerName"),
            "super_saver_price": _num(pr.get("superSaverSellingPrice"),
                                      ep.PRICE_DIVISOR),
            "discount_percent": pr.get("discountPercent"),
            "max_allowed_qty": pv.get("maxAllowedQuantity"),
            "shelf_life_hours": pv.get("shelfLifeInHours"),
            "fssai": pv.get("fssaiLicense"),
            "atlas_score": (pr.get("meta") or {}).get("atlasScore"),
            "semantic_score": (pr.get("meta") or {}).get("semanticScore"),
            "query_bucket": (pr.get("meta") or {}).get("query_matching_bucket"),
        },
    }


def _extract_products(body: dict) -> tuple[list[dict], bool]:
    """(products, hit_break) for one response page.

    `or []`, NOT a .get default: Zepto sends "layout": null on a page past the end
    of the results. The key IS present, so .get("layout", []) hands back None and
    iterating it raises — a bug that spent two days being misread as a rate-limit
    block, because the exception was swallowed and the store reported as throttled.

    `hit_break` is True when a section header ended the results. The caller must
    then STOP PAGING: once a response runs out of real matches, later pages
    continue the recommendation carousel rather than the search.
    """
    out: list[dict] = []
    for w in (body.get(ep.LAYOUT_KEY) or []):
        wid = w.get("widgetId")
        if wid in ep.SECTION_BREAK_WIDGETS:
            return out, True
        if wid != ep.PRODUCT_GRID_WIDGET:
            continue
        resolver = ((w.get("data") or {}).get("resolver") or {}).get("data") or {}
        for it in (resolver.get("items") or []):
            p = _extract_product(it)
            if p:
                out.append(p)
    return out, False


# ── Fetch ────────────────────────────────────────────────────────────────────

def _classify(status: int) -> str:
    if status == 200:
        return "ok"
    if status == ep.GATE_STATUS:
        return "gate"
    if status == ep.CHALLENGE_STATUS:
        return "challenge"
    if status == ep.RATE_STATUS:
        return "rate"
    return f"http{status}"


async def _fetch(session: dict, url: str, headers: dict, body: dict) -> dict:
    """POST with a hard per-attempt timeout, retrying TRANSPORT failures only.

    A blocked status returns immediately and is never retried here: the remedy
    differs per mechanism and belongs to the caller. The timeout is enforced
    twice — the request's own, plus an asyncio.wait_for around it — so a wedged
    context can never hang a worker.
    """
    resp: dict = {"status": 0, "kind": "error"}
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
            resp = {"status": 0, "kind": "error",
                    "error": "request timeout (context wedged)"}
            continue
        except Exception as e:
            resp = {"status": 0, "kind": "error", "error": str(e)[:120]}
            continue

        kind = _classify(r.status)
        if kind == "ok":
            try:
                return {"status": 200, "kind": "ok", "body": await r.json()}
            except Exception:
                # A 200 that will not parse is not a result. Keep retrying.
                resp = {"status": 200, "kind": "error", "error": "non-JSON body"}
                continue
        # Keep the body: `error_code` names the mechanism for free, and the
        # previous build discarding it is why two mechanisms went undiagnosed.
        detail = ""
        try:
            detail = (await r.text())[:200]
        except Exception:
            pass
        return {"status": r.status, "kind": kind, "body": None,
                "error": f"HTTP {r.status} {detail}".strip()}
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
    get_page's separate rate-limit budget on every call.
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


async def _mint_pass(session: dict) -> bool:
    """Re-mint the AWS WAF pass IN PLACE by re-navigating the session's own page.

    The pass is the `aws-waf-token` cookie and lives 4-6 minutes; nothing on the
    page refreshes it (`window.AwsWafIntegration` is absent). Re-navigating puts a
    fresh cookie in the same context, so the session object stays valid and the
    caller never has to know. Rebuilding the whole context would also work and
    costs far more.
    """
    try:
        await session["page"].goto(ep.HOMEPAGE_URL,
                                   wait_until="domcontentloaded", timeout=30000)
        await session["page"].wait_for_timeout(2500)
        session["minted_at"] = time.monotonic()
        return True
    except Exception as e:
        logger.debug(f"Zepto: pass re-mint failed: {e}")
        return False


async def _ensure_pass(session: dict) -> None:
    """Re-mint before the pass can expire mid-search, rather than discovering it
    as a wall of 202s."""
    if time.monotonic() - session.get("minted_at", 0) >= ep.PASS_REFRESH_S:
        await _mint_pass(session)


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
    session["minted_at"] = time.monotonic()

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

    # Best effort only. A caller that passes merchant_id per search never needs
    # this, and get_page has its own rate-limit budget — failing the whole session
    # here would kill a worker for the rest of the run.
    sid, secondaries = await _resolve_store(session, lat, lon)
    if not sid:
        logger.debug(f"Zepto: no store resolved at {lat},{lon} — session opens "
                     f"anyway; search() must supply merchant_id")
    session["store_id"] = sid
    session["secondary_ids"] = secondaries
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
) -> dict:
    """One keyword search in an open session, paging up to `cap`.

    RE-TARGETING. The caller walks many stores through one session, so the
    session's store must follow the store it is handed. Without that, every store
    in the run returns the SEED store's catalog — a valid 200 carrying the wrong
    store's data, with nothing in the response to say so.

    Prefer `merchant_id`: the caller is iterating catalog rows, so it already
    knows the store id and no lookup is needed. Falling back to `lat`/`lon` costs
    a get_page per store against a separate budget.

    `follow_similarity` is accepted and unused: Zepto has no basic->similarity
    relevance switch, so there is no tail to follow.

    Returns {products, total_results, merchant_id, ok, error, blocked, kind}.
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
                    "ok": False, "blocked": False, "kind": "error",
                    "error": f"no store resolved at {lat},{lon}"}
        session["store_id"] = sid
        session["secondary_ids"] = secondaries
        session["coord"] = (lat, lon)

    await _ensure_pass(session)

    headers = {**session["headers"],
               **ep.store_headers(session["store_id"], session["secondary_ids"])}
    url = ep.search_url()

    products: list[dict] = []
    seen: set[str] = set()
    ok, error, blocked, kind = False, "", False, "ok"
    page_no: int | None = 0

    while page_no is not None and len(products) < cap:
        body = ep.search_body(keyword, page_no, session.get("body"))
        resp = await _fetch(session, url, headers, body)

        if resp["kind"] == "challenge":
            # TERMINAL for this pass. Re-mint in place and retry once; waiting
            # would never help, which is the bug this rewrite exists to fix.
            if await _mint_pass(session):
                resp = await _fetch(session, url, headers, body)

        if resp["kind"] != "ok":
            kind = resp["kind"]
            error = resp.get("error") or f"HTTP {resp.get('status')}"
            blocked = kind in ("gate", "rate", "challenge")
            logger.debug(f"Zepto search '{keyword}': {error}")
            break

        ok = True
        page_rows, hit_break = _extract_products(resp["body"])
        if not page_rows:
            break  # genuinely nothing more for this term

        # Keep the FIRST sighting — it carries the true (best) rank. Dedupe is
        # mandatory even within one page: a 30-item page carried 3 duplicates,
        # and page 1 repeated 29% of page 0.
        for p in page_rows:
            pid = p.get("variant_id") or p.get("product_id")
            if pid:
                if pid in seen:
                    continue
                seen.add(pid)
            products.append(p)

        # The results ended inside this page — anything further is the "Similar
        # Products" carousel, so there is no next page of search results.
        if hit_break or page_no + 1 >= ep.MAX_PAGES or len(products) >= cap:
            page_no = None
        else:
            page_no += 1
            await asyncio.sleep(ep.SEARCH_GAP_S)

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
        "ok": ok, "error": error, "blocked": blocked, "kind": kind,
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
