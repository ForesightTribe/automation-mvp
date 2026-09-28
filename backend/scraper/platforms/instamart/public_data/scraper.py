"""Instamart public search — session, transport, and the raw→product step.

A sibling of blinkit/public_data/scraper.py and zepto/public_data/scraper.py on
the session-reuse interface `scraper/public/` drives: one browser context per
worker, `search()` called store after store, results staged locally by the
engine. This module holds no database code.

How Instamart differs from the other two, in the order it matters:

  1. Store binding is in the SEARCH URL (`storeId` / `primaryStoreId`), and the
     location cookie is only how a coordinate becomes a store id. Re-targeting a
     session to the next store is therefore free — three query params, no page
     load, no cookie rewrite. Verified 2026-09-17: same session, switched
     storeId, every item's `podId` followed.
  2. Transport is in-page `fetch()` ONLY. Playwright's request context gets a
     404 (the SPA shell). See endpoints.IN_PAGE_POST.
  3. No header capture. The page's own `matcher` header is not validated.
  4. Pages overlap heavily and `nextOffset` never says stop on keyword searches.
     Dedupe by productId and stop on "no new items" — see `search`.

Every literal lives in endpoints.py.
"""
import asyncio
import json
import re
import time
from typing import Any

from playwright.async_api import async_playwright

from app.utils.logger import logger
from scraper.platforms.instamart.public_data import endpoints as ep

_STORE_RE = re.compile(ep.STORE_ID_RE)


# ── Value helpers ────────────────────────────────────────────────────────────

def _num(v) -> float | None:
    """Price `units` are whole rupees as strings ("110"); rating.value is "4.4"."""
    if v in (None, "", "-"):
        return None
    try:
        return float(v) / ep.PRICE_DIVISOR
    except (TypeError, ValueError):
        return None


def _price(p: dict | None, key: str) -> float | None:
    node = ((p or {}).get(key) or {})
    units = node.get("units")
    nanos = node.get("nanos") or 0
    if units in (None, ""):
        return None
    try:
        return float(units) + float(nanos) / 1e9
    except (TypeError, ValueError):
        return None


def _ad_context(ctx: str) -> dict[str, str]:
    """'cid=…~~adslot=1~~kw=sourdough~~…' → {cid, adslot, kw, …}. Only the keys a
    consumer can act on are kept; the blob is ~400 bytes and mostly opaque."""
    out: dict[str, str] = {}
    for part in (ctx or "").split("~~"):
        k, _, v = part.partition("=")
        if k in ("cid", "adgrpid", "adslot", "kw", "st", "plpr", "class"):
            out[k] = v
    return out


def _extract_product(item: dict, rank: int) -> dict | None:
    """One grid item → the shared product dict `classify_products` / staging read.

    `merchant_id` is the store that SERVED the item (`podId`), which can be the
    secondary store rather than the one requested. Storing the request's store
    would attribute a competitor's listing to the wrong dark store.
    """
    name = (item.get("displayName") or "").strip()
    if not name:
        return None
    var = (item.get("variations") or [{}])[0] or {}
    price = var.get("price") or {}
    inv = var.get("inventory") or {}
    cart = var.get("cartAllowedQuantity") or {}
    rating = var.get("rating") or {}
    analytics = item.get("analytics") or {}
    extra_fields = analytics.get("extraFields") or {}
    badges = {b.get("type") for b in (item.get("badges") or []) if isinstance(b, dict)}
    is_ad = ep.AD_BADGE in badges or bool(item.get("adTrackingContext"))

    # Depth vs cap. "That's all we have in stock" with allowedQuantity=3 is real
    # depth; "Only 6 unit(s) … per order" with 6 is a per-order cap and says
    # nothing about stock. The number alone cannot tell them apart, the wording
    # can. Both are kept verbatim in `extra` for the day the wording changes.
    limit_msg = cart.get("quantityLimitBreachedMessage") or ""
    allowed = cart.get("allowedQuantity")
    inventory = allowed if (allowed is not None and "stock" in limit_msg.lower()) else None

    unit = (var.get("quantityDescription") or "").strip()
    ad_meta = _ad_context(item.get("adTrackingContext") or "") if is_ad else {}
    image_ids = var.get("imageIds") or []

    return {
        "position": rank,
        "name": name,
        "brand": (item.get("brand") or var.get("brandName") or "").strip(),
        "product_id": item.get("productId"),
        "group_id": item.get("parentProductId"),
        "variant_id": var.get("skuId"),
        "price": _price(price, "offerPrice"),
        "mrp": _price(price, "mrp"),
        "in_stock": bool(item.get("inStock", inv.get("inStock", True))),
        "inventory": inventory,
        "max_allowed_qty": allowed,
        "is_ad": is_ad,
        "merchant_id": str(var.get(ep.POD_ID_KEY) or ""),
        "merchant_type": (extra_fields.get("storeIDflag") or "").lower(),
        "unit": unit,
        "unit_raw": unit,
        "rating": _num(rating.get("value")),
        "rating_count": rating.get("count"),
        "category": var.get("category"),
        "ptype": var.get("subCategoryType"),
        "image_url": image_ids[0] if image_ids else None,
        "is_combo_hint": False,
        # Blinkit/Zepto put their ad ids here under their own names; Instamart's
        # too, so `listing_extra` carries them on sponsored rows only.
        "ad_meta": {f"im_{k}": v for k, v in ad_meta.items()},
        # Keyword rows (`search_listings.extra`) get only these four — the shared
        # builder keeps listing rows lean and reads this key opt-in.
        "listing_extra": {
            "confidence": extra_fields.get("searchResultType"),
            "cart_limit": allowed,
            "cart_limit_msg": limit_msg or None,
            "bestseller": ep.BESTSELLER_BADGE in badges,
        },
        # Own-SKU rows (`sku_snapshots.extra`) take this whole blob.
        "extra": {
            "confidence": extra_fields.get("searchResultType"),
            "bestseller": ep.BESTSELLER_BADGE in badges,
            "cart_limit": allowed,
            "cart_limit_msg": limit_msg or None,
            "low_stock_text": inv.get("lowStockText") or None,
            "super_category": var.get("superCategory"),
            "rating_count": rating.get("count"),
            "spin_id": var.get("spinId"),
            "weight_g": var.get("weightInGrams"),
            "discount_label": ((price.get("offerApplied") or {}).get("listingDescription")
                               or None),
        },
    }


def _walk_items(data: dict) -> list[dict]:
    """Every grid item across `cards[]`, in page order."""
    out: list[dict] = []
    for card in (data.get("cards") or []):
        node: Any = ((card.get("card") or {}).get("card") or {})
        for key in ep.GRID_ITEMS_PATH:
            node = (node or {}).get(key)
            if node is None:
                break
        if isinstance(node, list):
            out.extend(i for i in node if isinstance(i, dict))
    return out


def _result_count(data: dict) -> int | None:
    for card in (data.get("cards") or []):
        inner = ((card.get("card") or {}).get("card") or {})
        if ep.RESULT_COUNT_KEY in inner:
            try:
                return int(inner[ep.RESULT_COUNT_KEY])
            except (TypeError, ValueError):
                return None
    return None


def _next_offset(data: dict) -> int | None:
    node: Any = data
    for key in ep.NEXT_OFFSET_PATH:
        node = (node or {}).get(key)
    if node in (None, ""):
        return None
    try:
        return int(node)
    except (TypeError, ValueError):
        return None


# ── Transport ────────────────────────────────────────────────────────────────

def _classify(status: int) -> str:
    if status == 200:
        return "ok"
    if status == ep.CHALLENGE_STATUS:
        return "challenge"
    if status == ep.RATE_STATUS:
        return "rate"
    if status in ep.BLOCK_STATUSES:
        return "blocked"
    return f"http{status}"


async def _fetch(session: dict, path: str, body: dict) -> dict:
    """One in-page POST with a hard timeout, retrying TRANSPORT failures only.

    A blocked status returns at once — the remedy (re-mint, wait) belongs to the
    caller. The timeout wraps `page.evaluate`, so a wedged page cannot hang a
    worker: Playwright's own evaluate has no timeout of its own.
    """
    resp: dict = {"status": 0, "kind": "error", "error": "no attempt"}
    for delay in (0.0,) + ep.RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            r = await asyncio.wait_for(
                session["page"].evaluate(ep.IN_PAGE_POST, [path, body]),
                timeout=ep.FETCH_TIMEOUT_S + 5,
            )
        except asyncio.TimeoutError:
            resp = {"status": 0, "kind": "error", "error": "fetch timeout (page wedged)"}
            continue
        except Exception as e:
            resp = {"status": 0, "kind": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}
            continue

        status = int(r.get("status") or 0)
        text = r.get("body") or ""
        kind = _classify(status)
        if kind == "ok":
            try:
                return {"status": 200, "kind": "ok", "body": json.loads(text)}
            except Exception:
                resp = {"status": 200, "kind": "error", "error": "non-JSON body"}
                continue
        return {"status": status, "kind": kind, "body": None,
                "error": f"HTTP {status} {text[:120]}".strip()}
    return resp


# ── Session lifecycle ────────────────────────────────────────────────────────

async def _warm_up(page) -> int:
    """Load the homepage once so the context can resolve stores and holds a WAF
    pass. Returns the page size: a gate page is a few thousand characters, a real
    page ~150k."""
    await page.goto(ep.HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3_000)
    return len(await page.content())


async def _store_at(ctx, page, lat: float, lon: float, label: str = "") -> str | None:
    """Coordinate → the dark store serving it, via the location cookie and the
    bootstrap state of a fresh homepage load. None = not serviceable."""
    await ctx.clear_cookies(name=ep.LOCATION_COOKIE)
    await ctx.add_cookies([{
        "name": ep.LOCATION_COOKIE,
        "value": json.dumps({"lat": lat, "lng": lon, "address": label,
                             "area": "", "id": "", "annotation": ""}),
        "domain": ep.COOKIE_DOMAIN, "path": "/",
    }])
    await page.goto(ep.HOME_URL, wait_until="domcontentloaded", timeout=45_000)
    state = await page.evaluate(f"() => JSON.stringify({ep.BOOTSTRAP_VAR} || null)")
    m = _STORE_RE.search(state or "")
    return m.group(1) if m else None


async def _mint_pass(session: dict) -> bool:
    """Refresh the AWS WAF pass in place by re-navigating the session's own page.
    The page renews the cookie itself while it lives, but a timer costs nothing
    and covers a page that has gone quiet."""
    try:
        await session["page"].goto(ep.HOME_URL, wait_until="domcontentloaded",
                                   timeout=30_000)
        await session["page"].wait_for_timeout(2_000)
        session["minted_at"] = time.monotonic()
        return True
    except Exception as e:
        logger.debug(f"Instamart: pass re-mint failed: {e}")
        return False


async def _ensure_pass(session: dict) -> None:
    if time.monotonic() - session.get("minted_at", 0) >= ep.PASS_REFRESH_S:
        await _mint_pass(session)


async def _make_session(browser, lat: float, lon: float) -> dict | None:
    ctx = await browser.new_context(
        user_agent=ep.MOBILE_UA, locale="en-IN", viewport=ep.VIEWPORT,
        is_mobile=True, has_touch=True, extra_http_headers=ep.EXTRA_HEADERS,
    )
    page = await ctx.new_page()
    session: dict[str, Any] = {"context": ctx, "page": page}
    try:
        size = await _warm_up(page)
    except Exception as e:
        logger.warning(f"Instamart: warm-up failed: {e}")
        await ctx.close()
        return None
    if size < ep.WARM_PAGE_MIN_CHARS:
        logger.warning(f"Instamart: warm-up page is {size} chars — bot gate, no session")
        await ctx.close()
        return None
    session["minted_at"] = time.monotonic()

    # Best effort, like Zepto: a caller that passes merchant_id per search never
    # needs this, and failing the session here would kill a worker for the run.
    sid = None
    try:
        sid = await _store_at(ctx, page, lat, lon)
    except Exception as e:
        logger.debug(f"Instamart: store resolve failed at {lat},{lon}: {e}")
    if not sid:
        logger.debug(f"Instamart: no store resolved at {lat},{lon} — session opens "
                     f"anyway; search() must supply merchant_id")
    session["store_id"] = sid or ""
    session["secondary_id"] = ""
    session["coord"] = (lat, lon)
    return session


async def open_session(pw, lat: float, lon: float) -> dict | None:
    """Launch a browser + one session (ad-hoc / single-worker use). The session
    OWNS the browser; close_session shuts it down."""
    browser = await pw.chromium.launch(headless=True, args=ep.LAUNCH_ARGS)
    session = await _make_session(browser, lat, lon)
    if not session:
        await browser.close()
        return None
    session["browser"] = browser
    return session


async def open_context_session(browser, lat: float, lon: float) -> dict | None:
    """One session as an isolated context on a SHARED browser (the worker pool)."""
    return await _make_session(browser, lat, lon)


async def close_session(session: dict) -> None:
    try:
        await session["context"].close()
        if session.get("browser"):
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

    RE-TARGETING. The caller walks many stores through one session. Prefer
    `merchant_id`: the catalog row IS the store, so it goes straight into the
    query string — no lookup. A bare `lat`/`lon` costs a homepage load to
    resolve, once, and only when it differs from the session's coordinate.

    `follow_similarity` is accepted and unused: Instamart tags items
    HIGH/LOW_CONFIDENCE individually instead of switching modes, and the tag is
    stored per row (`extra.confidence`) for the consumer to filter.

    `distinct_ad_slots` decides whether a product's sponsored and organic
    placements are two rows or one. In the capture Brik Oven held #1 organic
    and #2 + #6 as ads for the SAME product — three placements, one product.

    Returns {products, total_results, merchant_id, ok, error, blocked, kind}.
    """
    if merchant_id and merchant_id != session.get("store_id"):
        session["store_id"] = str(merchant_id)
        session["secondary_id"] = ""
    elif not merchant_id and lat is not None and lon is not None \
            and (lat, lon) != session.get("coord"):
        try:
            sid = await _store_at(session["context"], session["page"], lat, lon)
        except Exception as e:
            sid = None
            logger.debug(f"Instamart: re-resolve failed at {lat},{lon}: {e}")
        session["coord"] = (lat, lon)
        session["store_id"] = sid or ""
        session["secondary_id"] = ""
        session["minted_at"] = time.monotonic()
    store = session.get("store_id") or ""
    if not store:
        return {"products": [], "total_results": 0, "merchant_id": "", "ok": False,
                "blocked": False, "kind": "error",
                "error": "no store id — not serviceable, or pass merchant_id"}

    await _ensure_pass(session)

    products: list[dict] = []
    seen: set = set()
    total: int | None = None
    offset, pages = 0, 0
    last: dict = {"kind": "ok"}
    while pages < ep.MAX_PAGES and len(products) < cap:
        last = await _fetch(session, ep.search_url(offset, store, session.get("secondary_id", "")),
                            ep.search_body(keyword, offset))
        pages += 1
        if last["kind"] != "ok":
            break
        data = (last["body"] or {}).get("data") or {}
        if total is None:
            total = _result_count(data)
        added = 0
        for item in _walk_items(data):
            p = _extract_product(item, len(products) + 1)
            if not p:
                continue
            key = (p["product_id"], p["is_ad"]) if distinct_ad_slots else p["product_id"]
            if key in seen:
                continue
            seen.add(key)
            products.append(p)
            added += 1
            if len(products) >= cap:
                break
        nxt = _next_offset(data)
        # Stop on the end signal, or when a page adds nothing new — pages overlap
        # so heavily that "nothing new" is the practical end long before Instamart
        # says so (page 2 of "sourdough": 42 items, 0 new).
        if nxt is None or added == 0:
            break
        offset = nxt

    if last["kind"] != "ok" and not products:
        return {"products": [], "total_results": 0, "merchant_id": store, "ok": False,
                "blocked": last["kind"] in ("challenge", "rate", "blocked"),
                "kind": last["kind"], "error": last.get("error", "")}

    # The store that answered: the commonest podId, which is the request's store
    # unless the secondary filled in. Reported so the engine's "catalog says X,
    # response says Y" check works here as it does on Blinkit.
    pods = [p["merchant_id"] for p in products if p["merchant_id"]]
    observed = max(set(pods), key=pods.count) if pods else store
    return {
        "products": products[:cap],
        "total_results": total if total is not None else len(products),
        "merchant_id": observed,
        "ok": True, "blocked": False, "kind": "ok", "error": "",
    }


async def scrape(keyword: str, lat: float, lon: float, cap: int = ep.RESULT_CAP) -> dict:
    """Ad-hoc: one keyword at one coordinate in a throwaway session."""
    async with async_playwright() as pw:
        session = await open_session(pw, lat, lon)
        if not session:
            return {"products": [], "total_results": 0, "merchant_id": "", "ok": False,
                    "blocked": False, "kind": "error", "error": "could not open session"}
        try:
            return await search(session, keyword, cap)
        finally:
            await close_session(session)
