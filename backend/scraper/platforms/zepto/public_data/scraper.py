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

4. **Replaying is refused through a proxy.** A session opened with `typed=True` searches
   through the page's own search box instead (`typed_search.py`); `search()` hands such a
   session straight over, so callers see one function and one result shape.

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
from scraper.utils.search_result import HEADERS_COMMON
from scraper.platforms.zepto.public_data import ads
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
        # Paid placement or organic. Zepto interleaves the two and says which is
        # which; on one live `bread` search 9 of 24 results were sponsored, so
        # dropping this silently mixed bought placements into SoV and rank. See
        # ads.py — and note it is NOT `is_fly_wheel_ad`, which is false even on
        # confirmed ads.
        "is_ad": ads.is_sponsored(pr),
        # The sponsored slot's tracking id: advertiser, campaign, store, and the
        # CAMPAIGN keyword that won the slot (which is NOT the query searched).
        # Empty on organic rows. `ads.parse_ucl_id` decodes it.
        "ucl_id": str(item.get("uclId") or ""),
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
        # When the last request LEFT — what pacing measures from (`_pace`, and the
        # orchestrators' pacer through the session). A transport retry is a request too.
        session["last_request_at"] = time.monotonic()
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

async def _capture(page, url_part: str, nav, settle_ms: int = 9000,
                   why: dict | None = None) -> tuple[dict, str | None]:
    """Capture headers (and body) from the page's OWN request to `url_part`.

    The listener must outlive the navigation: Zepto fires these AFTER
    domcontentloaded, so removing it when goto() returns captures nothing. The
    poll below is load-bearing — do not 'simplify' it away.

    `why`, when given, receives the browser's own reason for a navigation that failed
    (`nav_error`) — the only thing that tells "the proxy is down" from "Zepto said no".
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
        if why is not None:
            why.setdefault("nav_error", "the page did not load in time")
    except Exception as e:
        logger.debug(f"Zepto: capture failed for {url_part}: {e}")
        if why is not None:
            # First line only: Playwright appends a call log, and the reason is up front.
            why.setdefault("nav_error", " ".join(str(e).split("Call log")[0].split())[:160])
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


async def _make_session(browser, lat: float, lon: float, *, typed: bool = False,
                        why: dict | None = None,
                        resolve_store: bool = True) -> dict | None:
    """Isolated context on `browser`, warmed up, headers captured, coordinate
    resolved to a store. Returns the session dict or None.

    `typed` makes it a typed-search session (`typed_search.py`): same warm-up, then the
    page's requests are taken over and every `search()` goes through the search box.
    `why` receives the reason when None is returned (see `_capture`).

    `resolve_store=False` skips the coordinate -> store lookup. The worker pools name the
    store on every search (`merchant_id`), so for them the lookup was one `get_page` per
    session open spent on an answer nobody read. A search that does arrive with only a
    coordinate still resolves it — `coord` is left unset so the first one does."""
    ctx = await browser.new_context(
        user_agent=HEADERS_COMMON["User-Agent"], locale="en-IN")
    page = await ctx.new_page()
    session: dict[str, Any] = {"context": ctx, "page": page}
    if typed:
        from scraper.platforms.zepto.public_data import typed_search
        await typed_search.attach(session)

    gp_headers, _ = await _capture(
        page, ep.GET_PAGE_PATH,
        lambda: page.goto(ep.HOMEPAGE_URL, wait_until="domcontentloaded",
                          timeout=30000), why=why)
    session["gp_headers"] = gp_headers
    session["minted_at"] = time.monotonic()

    headers, raw_body = await _capture(
        page, ep.SEARCH_PATH,
        lambda: page.goto(ep.WARMUP_SEARCH_URL, wait_until="domcontentloaded",
                          timeout=30000), why=why)
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

    if typed:
        # No coordinate lookup: it is a replayed request, the very thing a typed session
        # exists to avoid. Every search names its store.
        session.update(store_id="", secondary_ids=(), coord=(lat, lon))
        await typed_search.arm(session)
        return session

    if not resolve_store:
        session.update(store_id="", secondary_ids=(), coord=None)
        return session

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


async def launch_browser(pw, proxy: dict | None = None):
    """The browser every Zepto shopper session runs in — the public scrape's worker pool,
    the own-SKU scrape, the Explorer and the bid engine's rank checks all come through
    here (the pool via `providers.Provider.launch_browser`).

    The FULL Chromium in headless mode, not Playwright's default headless shell, which
    Zepto's WAF blocks — see `endpoints.BROWSER_CHANNEL`.

    `proxy` is Playwright's own `{server, username, password}`. Only the bid engine passes
    one (`campaign_manager/marketplaces/zepto/adapter.py`); the scrapes never do.
    """
    kw = dict(headless=True, channel=ep.BROWSER_CHANNEL, args=PLAYWRIGHT_ARGS)
    if proxy:
        kw["proxy"] = proxy
    return await pw.chromium.launch(**kw)


async def open_session(pw, lat: float, lon: float, *, proxy: dict | None = None,
                       typed: bool = False, why: dict | None = None) -> dict | None:
    """Launch a browser + one session (ad-hoc / single-worker use). The session
    OWNS the browser; close_session shuts it down.

    `proxy` and `typed` go together in practice — a proxied session must search through the
    page (`typed_search.py`). `why` receives the reason when None is returned."""
    browser = await launch_browser(pw, proxy)
    session = await _make_session(browser, lat, lon, typed=typed, why=why)
    if not session:
        await browser.close()
        return None
    session["browser"] = browser  # owned
    return session


async def open_context_session(browser, lat: float, lon: float) -> dict | None:
    """One session as an isolated context on a SHARED browser (the worker pool).
    Does NOT own the browser — close_session only closes the context.

    No store lookup at open: see `_make_session(resolve_store=False)`."""
    return await _make_session(browser, lat, lon, resolve_store=False)


def block_remedy(kind: str, streak: int) -> tuple[float, bool]:
    """How to meet a block: (seconds to wait, rebuild the session?).

    `streak` is how many blocks in a row this worker has hit, this one included. The
    provider hands this to the orchestrators (`providers.Provider.block_remedy`); it is
    the single place that knows Zepto's three mechanisms want three different things —
    see endpoints.py:

        rate (429)       connection-wide, ~60 s   wait, SAME session
        gate (299)       connection-wide, ~60 s   wait, SAME session
        challenge (202)  this session only        rebuild now (search() already re-minted once)

    Rebuilding on a 429 or a 299 was the old reflex. It fires a homepage, a warm-up search
    and a `get_page` into a block that is about the connection, not the session — more
    requests at exactly the moment Zepto is saying there have been too many.

    A block that keeps coming back walks RECOVERY_WAITS_S, and from the end of the ladder
    the session is rebuilt as well, in case it is the session after all.
    """
    ladder = ep.RECOVERY_WAITS_S
    step = float(ladder[min(streak - 1, len(ladder) - 1)])
    worn = streak >= len(ladder)
    if kind == "rate":
        return (ep.RATE_PAUSE_S if streak == 1 else step), worn
    if kind == "gate":
        return (ep.GATE_PAUSE_S if streak == 1 else step), worn
    if kind == "challenge":
        return (0.0 if streak == 1 else step), True
    # Anything else that came back marked blocked: wait, and start clean.
    return step, True


async def _pace(session: dict) -> None:
    """Hold the next request until `gap_s` after the last one LEFT (start to start).

    `gap_s` is set on the session by the orchestrators' adaptive pacer; a caller that
    sets nothing gets the floor, PACE_FLOOR_S."""
    last = session.get("last_request_at")
    if last is None:
        return
    wait = last + session.get("gap_s", ep.PACE_FLOOR_S) - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)


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
    distinct_ad_slots: bool = True,
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

    `distinct_ad_slots` decides whether a product's sponsored and organic
    placements are two rows or one — see the dedupe loop below.

    Returns {products, total_results, merchant_id, ok, error, blocked, kind}.
    """
    if session.get("typed") is not None:
        # A typed session cannot replay (that is why it is one). Same result shape.
        from scraper.platforms.zepto.public_data import typed_search
        return await typed_search.search(session, keyword, cap, merchant_id=merchant_id,
                                         distinct_ad_slots=distinct_ad_slots)

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
    seen: set[tuple[str, bool]] = set()   # (product id, is_ad) — see the loop below
    ok, error, blocked, kind = False, "", False, "ok"
    truncated = False
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
            # A page AFTER the first failed: `products` is the head of the list only,
            # and storing it as the result would state rank and SoV over a cut list.
            truncated = ok
            logger.debug(f"Zepto search '{keyword}': {error}")
            break

        ok = True
        page_rows, hit_break = _extract_products(resp["body"])
        if not page_rows:
            break  # genuinely nothing more for this term

        # Dedupe on (product, is_ad) — NOT on product alone.
        #
        # Zepto genuinely repeats rows across pages (page 1 repeated 29% of page 0),
        # so some deduping is mandatory. But a product can also hold TWO REAL SLOTS
        # on one page: its organic placement and a sponsored one. Verified live —
        # `sourdough bread` showed Brik Oven organic at 1/2/4 and sponsored at
        # 7/9/13; `ricotta` showed the same SKU organic at 8 and sponsored at 9.
        # (The "3 duplicates in a 30-item page" this comment used to cite were
        # almost certainly those pairs, not artifacts.)
        #
        # Collapsing them lost the ad row, which understated SoV at BOTH ends: a
        # brand in 2 of 4 slots scored 1/3 = 33% instead of 2/4 = 50%, because the
        # denominator shrank too. It also hid the only position a bid can move.
        #
        # Rank is unaffected: `classify_products` takes min(position) over our rows,
        # so the best placement still wins regardless of how many are kept.
        #
        # ⚠️ `distinct_ad_slots=False` collapses the pair back to one row, and the
        # TARGETED own-SKU scrape needs exactly that. It measures a product's STATE
        # at a store (price, stock, inventory) rather than its placements on a page,
        # and writes `sku_snapshots` — where a second row for the same product at the
        # same store double-counts the inventory it is there to report. A brand-name
        # query is precisely where a brand-defence ad shows up, so this is not
        # hypothetical. Two scrapes, two questions, two keys.
        for p in page_rows:
            pid = p.get("variant_id") or p.get("product_id")
            if pid:
                key = (pid, bool(p.get("is_ad")) and distinct_ad_slots)
                if key in seen:
                    continue
                seen.add(key)
            products.append(p)

        # The results ended inside this page — anything further is the "Similar
        # Products" carousel, so there is no next page of search results.
        if hit_break or page_no + 1 >= ep.MAX_PAGES or len(products) >= cap:
            page_no = None
        else:
            page_no += 1
            # The next page is another request against the same limiter: same pace,
            # measured from when this one left.
            await _pace(session)

    products = products[:cap]
    # Fall back to running order where Zepto gave no position.
    for i, p in enumerate(products, 1):
        if p.get("position") is None:
            p["position"] = i

    return {
        "products": products,
        # The rows we KEPT, not a total: Zepto reports no count of matches. Blinkit's
        # `total_results` is its own count, so the two never compare — see
        # app/models/search.py SearchSnapshot.total_results.
        "total_results": len(products),
        # The session's store IS the merchant here — unlike Blinkit, where it has
        # to be read back off the products because one response spans several.
        "merchant_id": session.get("store_id", ""),
        "ok": ok, "error": error, "blocked": blocked, "kind": kind,
        "truncated": truncated,
    }


# ── Public entrypoint (CLI-compatible) ───────────────────────────────────────

async def scrape(
    keyword: str,
    brand_slug: str,
    city_slug: str = "",            # label only — carried onto the result
    zone: str = "",
    pincode: str = "",
    lat: float | None = None,
    lon: float | None = None,
    aliases: list[str] | None = None,
    cap: int | None = None,
) -> dict[str, Any]:
    """Scrape one keyword at one location (opens + closes its own session).
    The orchestrator reuses one session across keywords instead."""
    # Coordinates are REQUIRED. This used to fall back to a hardcoded city table whose
    # own docstring called its coordinates unverified placeholders, so a caller that
    # forgot them silently scraped a made-up point and got a plausible-looking result.
    # A scraper has no business owning a city registry; the caller resolves the store
    # (see scraper/utils/locations.py) and passes real coordinates.
    if lat is None or lon is None:
        raise ValueError(
            "zepto scrape needs lat/lon. Resolve them from the store catalogue "
            "with scraper.utils.locations.resolve_city(db, 'zepto', city)."
        )
    _lat, _lon = float(lat), float(lon)
    _pincode = pincode
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
            f"Zepto: no products for '{keyword}' in {city_slug}"
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
