"""Blinkit public search scraper.

Flow: open one headless-browser session per location (captures Cloudflare
clearance + the session-bound headers once), then run many keyword searches as
in-page fetch() calls, paginating via Blinkit's own next_url. The session is
reused across keywords — the expensive browser warmup is paid once per location,
not once per search.

`scraper.py` returns raw extracted fields; `parser.py` types/classifies them.
"""
import asyncio
import re
from typing import Any
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PWTimeout

from app.utils.logger import logger
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.search_result import HEADERS_COMMON, dig
from scraper.platforms.blinkit.public_data import ads, endpoints as ep


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

    rating_raw = common.get("rating")
    try:
        rating = float(rating_raw) if rating_raw not in (None, "") else None
    except (TypeError, ValueError):
        rating = None

    return {
        "product_id": str(cart_item.get("product_id") or ""),
        "name": cart_item.get("product_name") or "",
        "brand": cart_item.get("brand") or "",
        "price": cart_item.get("price"),
        "mrp": cart_item.get("mrp"),
        "unit": cart_item.get("unit") or "",
        "inventory": inventory,
        "in_stock": in_stock,
        "rating": rating,
        "product_state": common.get("state") or "",
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
        # Paid placement or organic. The marker was always in the block we already
        # read for position/rating/category — we simply never looked at it, so every
        # stored Blinkit listing to date reads as organic and SoV/rank are computed
        # over a mixture of bought and earned slots. `ads.py` owns the predicate; the
        # bid optimizer reads it through the same function. See its docstring for why
        # the campaign id must come from `common_attributes` and nowhere else.
        "is_ad": ads.is_sponsored(common),
        # The sponsoring campaign's tracking ids — OUR campaign id, the same integer
        # the Campaign Manager writes to. Empty dict on organic rows.
        "ad_meta": ads.ad_meta(common),
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
            // real HTTP status so the retry loop + logs see it for what it is, and the
            // head of the page, whose <title> says which Cloudflare page it was.
            return {status: r.status, body: null, error: "non-JSON body (Cloudflare?)",
                    head: text.slice(0, 600)};
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


def classify(resp: dict) -> str:
    """What an in-page fetch's answer was: `ok`, a block (`rate` / `challenge` /
    `forbidden`, see endpoints.py), or `error` (a transport failure or an ordinary
    non-200 — not something to wait out).

    A non-JSON body is Cloudflare's page standing in for Blinkit's: whatever its status
    (403 and 503 in practice, a 200 interstitial too), the session's clearance is no
    longer accepted."""
    status = resp.get("status") or 0
    if status == 200 and resp.get("body") is not None:
        return "ok"
    if status == 429:
        return "rate"
    if status and resp.get("body") is None and "non-JSON" in (resp.get("error") or ""):
        return "challenge"
    if status == 403:
        return "forbidden"
    return "error"


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _detail(resp: dict) -> str:
    """`HTTP 403 · Just a moment...` — the status plus, for a Cloudflare page, its title."""
    out = f"HTTP {resp.get('status')}"
    m = _TITLE.search(resp.get("head") or "")
    if m:
        out += f" · {' '.join(m.group(1).split())[:80]}"
    elif resp.get("error"):
        out += f" · {resp['error']}"
    return out


async def in_page_fetch(page, url: str, headers: dict, body: dict | None,
                        retry_blocks: bool = True) -> dict:
    """In-page fetch with a hard per-attempt timeout + retry/backoff on transient
    failures. Returns on the first 200; otherwise the last response after retries.

    `retry_blocks=False` returns a BLOCK (see `classify`) at once instead of re-sending
    it three times within ~5 s — the public scrapes' worker pools pass that (through their
    session) and wait the block out properly (`block_remedy`). The default keeps the old
    behaviour for the campaign manager's position checks, which have no such machinery.

    PUBLIC on purpose: the campaign manager's live-position scrape calls this too. It is
    the one place that knows how to get a request past Cloudflare (in-page fetch on a
    cleared session, challenge detection, backoff) — duplicating it would mean fixing
    Blinkit changes twice and discovering the second copy months later."""
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
        if not retry_blocks and classify(resp) in ep.BLOCK_KINDS:
            return resp
    return resp


# ── Session lifecycle ────────────────────────────────────────────────────────

async def new_search_context(browser, lat: float, lon: float):
    """The browser context every Blinkit consumer-side session runs in.

    PUBLIC because the campaign manager's position check opens one too. It used to build
    its own — a different user agent, no locale, no geolocation, no launch args — and
    that thinner fingerprint was the one Cloudflare refused on the VM. One setup, so a
    change that gets us past Cloudflare applies to every caller."""
    return await browser.new_context(
        user_agent=HEADERS_COMMON["User-Agent"],
        locale="en-IN",
        geolocation={"latitude": lat, "longitude": lon},
        permissions=["geolocation"],
    )


# Page titles Cloudflare serves instead of the site when it challenges or blocks.
_CF_TITLES = ("just a moment", "attention required", "access denied")


async def warm_up(page, lat: float, lon: float) -> tuple[dict, str]:
    """Load the homepage (fixes the location) and a throwaway search, and copy the
    headers Blinkit's own page attaches to its `/v1/layout/search` request.

    Returns (headers, why). `headers` is empty when capture failed, and `why` then says
    what the browser actually saw — a Cloudflare page, an HTTP status, a timeout — so
    the failure is diagnosable from the log instead of a bare "no headers"."""
    captured: dict[str, str] = {}
    seen_search = False

    def _on_req(req):
        nonlocal seen_search
        if ep.SEARCH_PATH in req.url and not captured:
            seen_search = True
            captured.update(req.headers)

    notes: list[str] = []
    page.on("request", _on_req)
    try:
        for name, url, wait in (("homepage", ep.HOMEPAGE_URL.format(lat=lat, lon=lon), 1000),
                                ("search page", ep.WARMUP_SEARCH_URL, 1500)):
            status = None
            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=20000)
                status = resp.status if resp else None
                await page.wait_for_timeout(wait)
            except PWTimeout:
                notes.append(f"{name}: timed out after 20s")
                continue
            except Exception as e:
                notes.append(f"{name}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
                continue
            try:
                title = (await page.title()).strip()
            except Exception:
                title = ""
            if any(t in title.lower() for t in _CF_TITLES):
                notes.append(f"{name}: Cloudflare page (HTTP {status}, '{title[:60]}')")
            elif status and status >= 400:
                notes.append(f"{name}: HTTP {status} ('{title[:60]}')")
    finally:
        page.remove_listener("request", _on_req)

    headers = {k: captured[k] for k in ep.SEARCH_HEADER_KEYS if k in captured}
    if headers:
        return headers, ""
    if seen_search:
        notes.append("the page's search request carried none of the expected headers "
                     "(did Blinkit rename them?)")
    else:
        notes.append("Blinkit's page never sent its own search request")
    return {}, "; ".join(notes)


async def _make_session(browser, lat: float, lon: float) -> dict | None:
    """Create an isolated context on `browser`, warm it up, and capture the
    session-bound search headers. Returns {context, page, headers} or None."""
    ctx = await new_search_context(browser, lat, lon)
    page = await ctx.new_page()
    headers, why = await warm_up(page, lat, lon)
    if not headers:
        logger.warning(f"Blinkit: no session headers captured — {why}")
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
    pool). Does not own the browser — close_session() only closes the context.

    Pool sessions hand blocks straight back (`retry_blocks=False`): the orchestrators
    wait them out by kind (`block_remedy`), which beats re-sending them at once."""
    session = await _make_session(browser, lat, lon)
    if session:
        session["retry_blocks"] = False
    return session


def block_remedy(kind: str, streak: int) -> tuple[float, bool]:
    """How to meet a Blinkit block: (seconds to wait, open a new session?).

    `streak` is how many blocks in a row this worker has hit, this one included. Handed
    to the orchestrators through `providers.Provider.block_remedy`:

        rate (429)       too fast, right now          wait, SAME session
        challenge        Cloudflare's page, not JSON  NEW session at once (stale clearance)
        forbidden (403)  refused, JSON body           wait, then a new session

    A new session costs a homepage load and a warm-up search, so it is the last resort
    rather than the reflex. Blocks that keep coming walk RECOVERY_WAITS_S, and from the
    end of the ladder a new session as well. ⚠️ Unmeasured — see endpoints.py.
    """
    ladder = ep.RECOVERY_WAITS_S
    step = float(ladder[min(streak - 1, len(ladder) - 1)])
    worn = streak >= len(ladder)
    if kind == "rate":
        return (ep.RATE_PAUSE_S if streak == 1 else step), worn
    if kind == "challenge":
        return (0.0 if streak == 1 else step), True
    if kind == "forbidden":
        return (ep.FORBIDDEN_PAUSE_S if streak == 1 else step), True
    return step, True


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
    merchant_id: str | None = None,
    follow_similarity: bool = False,
    distinct_ad_slots: bool = True,
) -> dict:
    """Run one keyword search in an open session, paginating up to `cap`. Pass
    `lat`/`lon` to target a specific store without reopening the session — Blinkit
    selects the dark store from the lat/lon headers.

    `merchant_id` is accepted for interface compatibility and IGNORED. Blinkit
    binds by coordinate and reports the serving store back off the products; the
    argument exists for marketplaces that bind the other way round (see D8 and
    scraper/public/providers.py).

    By default paging stops when results switch from `basic` to `similarity`
    (loosely-related padding) — right for a category-keyword scrape. Set
    `follow_similarity=True` for the BRAND scrape: Blinkit returns only ~18 of a
    brand's products as `basic` and pushes the rest into `similarity`, so following
    the tail (bounded by `cap`) recovers the full catalog. Safe there because the
    caller classifies own-brand-only, discarding any non-own similarity padding.

    `distinct_ad_slots` decides whether a product's sponsored and organic placements
    are two rows or one — see the dedupe loop below.

    Returns {products, total_results, merchant_id, ok, error, blocked, kind, truncated}.
    `ok` is False when the FIRST page did not come back; `blocked`/`kind` say whether a
    failed page was a block (see `classify`); `truncated` says a LATER page failed, so
    `products` is the head of the list, not all of it.

    ⚠️ `truncated` rows must not be stored as a search result: share of voice and rank
    are computed over the whole list, and a list cut at 12 of 36 states both wrongly
    with nothing to show it. The public orchestrators treat it as a failure (and retry);
    the campaign manager's stock read keeps using what it got, as it always has.
    """
    page = session["page"]
    headers = session["headers"]
    if lat is not None and lon is not None:
        headers = {**headers, "lat": str(lat), "lon": str(lon)}

    products: list[dict] = []
    seen: set[tuple[str, bool]] = set()   # (product id, is_ad) — see the loop below
    total_results: int | None = None
    ok = False
    error = ""
    blocked, kind, truncated = False, "ok", False
    url: str | None = ep.first_search_url(keyword)
    body: dict | None = ep.SEARCH_BODY
    requested: set[str] = set()
    pages = 0

    while url and len(products) < cap:
        # Three stops on top of the cap, because the cap alone cannot end a loop in
        # which duplicates don't count: a next_url we already fetched, a page that
        # added nothing, and a hard page ceiling. See ep.MAX_PAGES for the store
        # that looped forever without them.
        if url in requested or pages >= ep.MAX_PAGES:
            logger.warning(
                f"Blinkit search '{keyword}' @ ({lat},{lon}): stopped paging after "
                f"{pages} pages ({'next page repeats one already fetched' if url in requested else 'page limit'})"
            )
            break
        requested.add(url)
        pages += 1
        before = len(products)

        resp = await in_page_fetch(page, url, headers, body,
                                   retry_blocks=session.get("retry_blocks", True))
        kind = classify(resp)
        if kind != "ok":
            error = _detail(resp)
            blocked = kind in ep.BLOCK_KINDS
            # A page AFTER the first failed: what we hold is the head of the list.
            truncated = ok
            if truncated:
                error = f"page {pages} failed after {len(products)} products — {error}"
            logger.debug(f"Blinkit search '{keyword}': {error}")
            break
        ok = True
        page_body = resp.get("body") or {}
        # Blinkit repeats products across pages — the `similarity` tail re-lists items
        # already returned as `basic`, so a brand scrape (follow_similarity=True) saw
        # the same SKU two or three times and wrote a duplicate row per store. Keep the
        # FIRST sighting: it carries the true (best) rank.
        #
        # Dedupe on (product, is_ad) — NOT on product alone, which is what this did
        # until `is_ad` was populated above.
        #
        # Whether Blinkit serves a product BOTH slots on one response is NOT
        # established: api.txt concatenates several captures, so its repeated pids
        # prove nothing either way. (On Zepto it is established — `sourdough bread`
        # showed one SKU organic at 1/2/4 and sponsored at 7/9/13.)
        #
        # The key is widened anyway because the failure is ONE-SIDED. If Blinkit never
        # dual-slots, the two keys are identical and this changes nothing. If it does,
        # the narrow key drops a real placement — and drops the wrong one: sponsored
        # slots rank high, so the ad arrives FIRST and first-sighting-wins keeps it,
        # silently converting the product's stored placement from earned to bought.
        # A wider key cannot invent a row; a narrower one can rewrite the truth.
        #
        # Rank is unaffected either way: `classify_products` takes min(position) over
        # our rows, so the best placement still wins regardless of how many are kept.
        #
        # ⚠️ `distinct_ad_slots=False` collapses the pair back to one row, and the
        # TARGETED own-SKU scrape needs exactly that. It measures a product's STATE at
        # a store (price, stock, inventory) rather than its placements on a page, and
        # writes `sku_snapshots` — where a second row for the same product at the same
        # store double-counts the inventory it is there to report. A brand-name query
        # is precisely where a brand-defence ad shows up, so this is not hypothetical.
        # Two scrapes, two questions, two keys.
        for p in _extract_products(page_body):
            pid = p.get("product_id")
            if pid:
                key = (pid, bool(p.get("is_ad")) and distinct_ad_slots)
                if key in seen:
                    continue
                seen.add(key)
            products.append(p)

        next_url, method, count = _pagination(page_body)
        if total_results is None:
            total_results = count
        if not next_url:
            break
        if len(products) == before:
            logger.warning(
                f"Blinkit search '{keyword}' @ ({lat},{lon}): page {pages} added no new "
                f"products — stopped paging"
            )
            break
        if method != ep.BASIC_SEARCH_METHOD and not follow_similarity:
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
    return {"products": products, "total_results": total_results,
            "merchant_id": _express_merchant(products), "ok": ok, "error": error,
            "blocked": blocked, "kind": "ok" if not error else kind,
            "truncated": truncated}


def _express_merchant(products: list[dict]) -> str:
    """The express store serving this coordinate — the location's identity.

    One response spans several stores and tiers (express + longtail hubs + the odd
    super_longtail), interleaved by rank, so the FIRST product is not reliably the
    express one: a longtail row often outranks it, and some keywords return no
    express product at all. Only the per-product `merchant_type` identifies it.

    Returns "" when no express product was returned — the honest answer. Every
    product keeps its own merchant_id regardless; this is only the snapshot-level
    label. See docs/darkstores.md.
    """
    return next(
        (p["merchant_id"] for p in products
         if p.get("merchant_type") == "express" and p.get("merchant_id")),
        "",
    )


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
    The orchestrator (Phase 5) will instead reuse one session across keywords."""
    # Coordinates are REQUIRED. This used to fall back to a hardcoded city table whose
    # own docstring called its coordinates unverified placeholders, so a caller that
    # forgot them silently scraped a made-up point and got a plausible-looking result.
    # A scraper has no business owning a city registry; the caller resolves the store
    # (see scraper/utils/locations.py) and passes real coordinates.
    if lat is None or lon is None:
        raise ValueError(
            "blinkit scrape needs lat/lon. Resolve them from the store catalogue "
            "with scraper.utils.locations.resolve_city(db, 'blinkit', city)."
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
        logger.warning(f"Blinkit scrape failed for '{keyword}': {e}")

    if not products:
        logger.warning(
            f"Blinkit: no products for '{keyword}' in {city_slug}"
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
