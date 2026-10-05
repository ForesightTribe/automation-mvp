"""Zepto search through the page's OWN search box ("typed search").

`scraper.search` replays the session's captured headers with Playwright's request client —
fast, and what every scrape uses. Through a proxy Zepto refuses exactly that (2026-09-29:
0/4 from the VM, 0/3 from a laptop, and the proxy's address stayed flagged afterwards), while
the page's own requests on the same connection are answered. So a session opened with
`typed=True` searches the way a shopper does: the keyword is typed into Zepto's search box,
the page sends its own search, and we read the page's own answer.

Same result shape as `scraper.search`, which hands a typed session straight here — callers do
not know which one they got. Measured on the VM through the proxy: 10/10, ~6 s and ~210 KB a
search (`zepto-cm-exp/PROXY-TESTS.md`, V2).

ONE SEARCH = ONE CALL TO ZEPTO
------------------------------
A typed keyword makes the page send far more than one request, and only one of them is the
answer. The route handler lets that one through and aborts the rest before they leave:

    while typing     mode TYPED        as-you-type suggestions, 2-4 of them      aborted
    after Enter   A  a results call for the PREVIOUS keyword (a leftover as     aborted
                     the page re-renders) — arrives before OR after B
                  B  a results call for OUR keyword                              SENT
                  C  our keyword again without `intentId`; returns no products   aborted

⚠️ **A is the dangerous one.** Reading "the first results answer after Enter" reports the
previous keyword's list as this keyword's whenever A wins the race — a plausible, well-formed,
wrong rank (found 2026-09-30; four of ten rows in one run). An answer counts ONLY when it is
the answer to the one request we let through, and that request's own body asked for our
keyword. `verdict()` is that rule; do not loosen it.

The store is bound the way it always is on Zepto — by header (`endpoints.store_headers`) —
swapped onto B as it leaves. Every answer is checked: a product from any other store fails
the search rather than being reported.

A REFUSAL NEVER LOOKS LIKE ONE
------------------------------
When Zepto's anonymous search allowance is used up it answers HTTP 299 ("login to search")
straight from CloudFront, WITHOUT the cross-site header. The browser therefore blocks the
answer: the page and Playwright see a request that merely "failed", with no status. Five
versions of the test tool reported these as "the page did not search". The real status is
read at the browser's network layer (CDP) and returned as the same `gate` the replay path
reports, so the caller's existing wait-and-retry applies.

ONE PAGE
--------
A typed search reads the first page (~30 rows) and nothing deeper. When that page is full the
result carries `capped_at`, so a caller that reasons about what was NOT found (the stock
check) knows the list may continue.
"""
import asyncio
import json
import time
from functools import partial
from urllib.parse import urlsplit

from app.utils.logger import logger
from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import scraper as zs

# What one of the page's search calls is, to us. Only OURS leaves the browser.
OURS = "ours"            # a results call for the keyword being searched, first page
TYPING = "typing"        # as-you-type suggestions
STALE = "stale"          # a results call for another keyword (the previous one, re-sent)
BARE = "bare"            # our keyword without `intentId` — returns no products
DEEPER = "deeper"        # our keyword, a later page
UNKNOWN = "unknown"      # a mode we have never seen


def norm(q) -> str:
    return " ".join(str(q or "").lower().split())


def verdict(post_data, keyword: str | None) -> str:
    """Pure. What a search call's request body says it is. `keyword` is the normalised
    keyword being searched right now, or None between searches (nothing is ours then)."""
    try:
        body = json.loads(post_data or "{}")
    except Exception:
        return UNKNOWN
    if not isinstance(body, dict):
        return UNKNOWN
    mode = body.get("mode")
    if mode == ep.TYPED_TYPING_MODE:
        return TYPING
    if mode not in ep.TYPED_RESULTS_MODES:
        return UNKNOWN
    if not keyword or norm(body.get("query")) != keyword:
        return STALE
    if (body.get("pageNumber") or 0) != 0:
        return DEEPER
    if "userSessionId" in body and "intentId" not in body:
        return BARE
    return OURS


class State:
    """What a typed session carries between its route handler and its searches."""

    def __init__(self):
        self.keyword: str | None = None   # being searched now (normalised); None = between searches
        self.sent = None                  # THE request let through for it — at most one
        self.blocked: list[int] = []      # raw status of answers the browser blocked (this try)
        self.last_done = 0.0
        self.armed = False                # False during the warm-up: its search goes untouched
        self.warned_unknown = False
        # The run's usage, for the one log line when the session closes.
        self.bytes = 0
        self.searches = 0
        self.calls = 0                    # search calls that actually reached Zepto
        self.refused = 0


async def attach(session: dict) -> State:
    """Make `session` a typed one: count its data and stop the dead weight
    (`endpoints.TYPED_BLOCK_*`). Call BEFORE the warm-up — the warm-up is about half of a
    run's megabytes, and most of that is images. The warm-up's own search goes out untouched:
    the search calls are only taken over by `arm`."""
    st = State()
    session["typed"] = st
    await session["context"].route("**/*", partial(_route, session))

    async def _count(req):
        try:
            s = await req.sizes()
            st.bytes += (s["requestHeadersSize"] + s["requestBodySize"]
                         + s["responseHeadersSize"] + s["responseBodySize"])
        except Exception:
            pass
    session["context"].on("requestfinished", lambda r: asyncio.ensure_future(_count(r)))
    return st


async def arm(session: dict) -> None:
    """Take over the warmed-up page's search calls: from here on only our one call per search
    reaches Zepto's search service."""
    page, st = session["page"], session["typed"]
    st.armed = True
    # The raw status of a blocked answer is visible nowhere else (see the module docstring).
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")
        ids: set[str] = set()

        def _sent(e):
            rq = e.get("request") or {}
            if ep.SEARCH_PATH in rq.get("url", "") and rq.get("method") == "POST":
                ids.add(e.get("requestId"))

        def _answer(e):
            if e.get("requestId") not in ids:
                return
            names = {str(k).lower() for k in (e.get("headers") or {})}
            if "access-control-allow-origin" not in names:
                st.blocked.append(e.get("statusCode"))
        cdp.on("Network.requestWillBeSent", _sent)
        cdp.on("Network.responseReceivedExtraInfo", _answer)
    except Exception as e:
        # Without it a blocked answer is still detected, just not told apart by status.
        logger.debug(f"Zepto typed search: no network-layer view ({e})")
    await _settle(page)


async def _settle(page) -> None:
    """Let a freshly loaded page go quiet before driving it: over a slow line a search typed
    into a half-loaded page turns into a full page reload."""
    try:
        await page.wait_for_load_state("networkidle", timeout=int(ep.TYPED_SETTLE_S * 1000))
    except Exception:
        pass
    await page.wait_for_timeout(1000)


def dead_weight(resource_type: str, url: str) -> bool:
    """Pure. Never downloaded in a typed session (see `endpoints.TYPED_BLOCK_HOSTS`)."""
    if resource_type in ep.TYPED_BLOCK_RESOURCES:
        return True
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ep.TYPED_BLOCK_HOSTS)


async def _route(session: dict, route) -> None:
    st, req = session["typed"], route.request
    try:
        if dead_weight(req.resource_type, req.url):
            return await route.abort()
        # The warm-up's own search goes out as the page sent it (it is one call). Stopping it
        # was tried 2026-10-01 against the refusals that follow a warm-up: no difference
        # either way in a back-to-back A/B, so the validated sequence stands.
        if not st.armed or ep.SEARCH_PATH not in req.url or req.method != "POST":
            return await route.continue_()
        what = verdict(req.post_data, st.keyword)
        if what == OURS and st.sent is None:
            st.sent = req
            st.calls += 1
            return await route.continue_(headers={
                **req.headers, **ep.store_headers(session["store_id"], ())})
        if what == UNKNOWN and not st.warned_unknown:
            st.warned_unknown = True
            logger.warning("Zepto typed search: the page sent a search call of a kind this "
                           "code has never seen — it was not sent on. If typed searches "
                           "start failing, Zepto's page has changed.")
        await route.abort()
    except Exception as e:
        # The page closed under us, or the request was already handled. Nothing to recover.
        logger.debug(f"Zepto typed search: route handler: {e}")


async def _remint(session: dict) -> bool:
    """A fresh WAF pass AND a clean search page, in one page load. The replay path re-mints
    on the homepage; a typed session must land where the search box is. The page's own
    search call on load is aborted like any other that is not ours (no keyword is set)."""
    page, st = session["page"], session["typed"]
    st.keyword, st.sent = None, None
    try:
        await page.goto(ep.TYPED_SEARCH_PAGE, wait_until="domcontentloaded", timeout=30000)
        await _settle(page)
        session["minted_at"] = time.monotonic()
        return True
    except Exception as e:
        logger.debug(f"Zepto typed search: re-mint failed: {e}")
        return False


async def _attempt(session: dict, keyword: str) -> dict:
    """Type `keyword`, press Enter, wait for the answer to the one call let through.
    Returns {kind, rows, hit_break, error}; kind is ok | gate | rate | challenge | http<n> |
    error | silent (the page never sent the search) | lost (no search box on the page)."""
    page, st = session["page"], session["typed"]
    box = page.locator(ep.TYPED_SEARCH_BOX).first
    try:
        if await box.count() == 0:
            return {"kind": "lost", "error": "no search box on the page"}
    except Exception as e:
        return {"kind": "lost", "error": f"the page is gone ({str(e)[:80]})"}

    want = norm(keyword)
    got: dict = {}

    async def _on_response(r):
        # The answer to the one request we let through — and, belt and braces, only if that
        # request's own body still says it asked for our keyword.
        if r.request is not st.sent or verdict(r.request.post_data, want) != OURS:
            return
        if r.status != 200:
            got.setdefault("status", r.status)
            return
        try:
            rows, hit_break = zs._extract_products(await r.json())
        except Exception as e:
            got.setdefault("error", f"the answer could not be read ({str(e)[:80]})")
            return
        got.update(status=200, rows=rows, hit_break=hit_break)

    def _on_failed(req):
        if req is st.sent:
            got.setdefault("failed", req.failure or "failed")

    on_response = lambda r: asyncio.ensure_future(_on_response(r))
    st.keyword, st.sent = want, None
    st.blocked.clear()
    page.on("response", on_response)
    page.on("requestfailed", _on_failed)
    try:
        # Real keystrokes: the page only notices its box changing when it is typed into.
        await box.click(timeout=10000)
        await box.focus()
        await page.wait_for_timeout(ep.TYPED_FOCUS_MS)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(keyword, delay=ep.TYPED_KEY_DELAY_MS)
        # Like a person: stop typing, then Enter.
        await page.wait_for_timeout(ep.TYPED_ENTER_WAIT_MS)
        await page.keyboard.press("Enter")
        deadline = time.monotonic() + ep.TYPED_ANSWER_S
        while time.monotonic() < deadline and not got:
            await asyncio.sleep(0.25)
        # The page re-sends its call a moment later (C, above); let that pass — and let a
        # blocked answer's status arrive — before anything else is typed.
        await asyncio.sleep(ep.TYPED_AFTER_S)
    except Exception as e:
        got.setdefault("error", f"the page could not be driven ({str(e)[:100]})")
    finally:
        page.remove_listener("response", on_response)
        page.remove_listener("requestfailed", _on_failed)
        st.keyword = None

    if got.get("status") == 200:
        return {"kind": "ok", "rows": got["rows"], "hit_break": got["hit_break"]}
    if "status" in got:                       # a refusal the page was allowed to read
        return {"kind": zs._classify(got["status"]), "error": f"HTTP {got['status']}"}
    if "failed" in got:
        status = st.blocked[-1] if st.blocked else None
        if status is not None:
            return {"kind": zs._classify(status),
                    "error": f"HTTP {status} — Zepto refused the search (the browser blocked "
                             f"its answer)"}
        if "ERR_FAILED" in got["failed"]:
            # How a blocked answer shows when the network layer could not be watched. Every
            # one traced so far was the login gate.
            return {"kind": "gate", "error": "Zepto refused the search (the browser blocked "
                                             "its answer; most likely HTTP 299)"}
        return {"kind": "error", "error": f"the search request failed ({got['failed']})"}
    if "error" in got:
        return {"kind": "error", "error": got["error"]}
    if st.sent is None:
        return {"kind": "silent", "error": f"the page did not send the search for {keyword!r}"}
    return {"kind": "error", "error": f"no answer within {ep.TYPED_ANSWER_S:g}s"}


def _failed(session: dict, kind: str, error: str) -> dict:
    return {"products": [], "total_results": 0, "merchant_id": session.get("store_id", ""),
            "ok": False, "error": error, "kind": kind,
            "blocked": kind in ("gate", "rate", "challenge")}


def build(rows: list[dict], hit_break: bool, cap: int, store_id: str,
          distinct_ad_slots: bool) -> dict:
    """Pure. One answered page → the result `scraper.search` would have returned."""
    # Bound by header, verified by content: the swap failing would hand back another
    # store's ranks under this store's name, with nothing else to say so.
    served = {p.get("merchant_id") for p in rows if p.get("merchant_id")}
    if served - {store_id}:
        return {"products": [], "total_results": 0, "merchant_id": store_id, "ok": False,
                "blocked": False, "kind": "error",
                "error": f"the answer came from another store ({', '.join(sorted(served))}), "
                         f"not {store_id}"}
    # (product, is_ad) — the same key, for the same reasons, as `scraper.search`.
    products: list[dict] = []
    seen: set[tuple[str, bool]] = set()
    for p in rows:
        pid = p.get("variant_id") or p.get("product_id")
        if pid:
            key = (pid, bool(p.get("is_ad")) and distinct_ad_slots)
            if key in seen:
                continue
            seen.add(key)
        products.append(p)
    products = products[:cap]
    for i, p in enumerate(products, 1):
        if p.get("position") is None:
            p["position"] = i
    out = {"products": products, "total_results": len(products), "merchant_id": store_id,
           "ok": True, "error": "", "blocked": False, "kind": "ok"}
    if len(rows) >= ep.TYPED_PAGE_ROWS and not hit_break:
        out["capped_at"] = len(products)      # a full page: the list may go on
    return out


async def search(session: dict, keyword: str, cap: int = ep.RESULT_CAP, *,
                 merchant_id: str | None = None, distinct_ad_slots: bool = True) -> dict:
    """One keyword at one store, through the page. See the module docstring.

    Returns what `scraper.search` returns — {products, total_results, merchant_id, ok, error,
    blocked, kind} — plus `capped_at` when the page was full."""
    st = session["typed"]
    if merchant_id:
        session["store_id"] = merchant_id
        session["secondary_ids"] = ()
    if not session.get("store_id"):
        # Resolving a coordinate is a replayed request, which is what this path exists to
        # avoid. Every catalogue store has an id, so a caller always has one to pass.
        return _failed(session, "error", "a typed search needs the store's id")

    if time.monotonic() - session.get("minted_at", 0) >= ep.PASS_REFRESH_S:
        await _remint(session)
    wait = ep.TYPED_GAP_S - (time.monotonic() - st.last_done)
    if wait > 0:
        await asyncio.sleep(wait)

    st.searches += 1
    got = await _attempt(session, keyword)
    if got["kind"] in ("silent", "lost", "challenge"):
        # One cure for all three — a clean search page with a fresh pass. A dead pass (202)
        # never recovers by waiting, and the other two never reached Zepto at all.
        logger.debug(f"Zepto typed search {keyword!r}: {got['error']} — reloading the search "
                     f"page and asking once more")
        if await _remint(session):
            got = await _attempt(session, keyword)
    st.last_done = time.monotonic()

    if got["kind"] != "ok":
        if got["kind"] == "gate":
            st.refused += 1
        kind = "error" if got["kind"] in ("silent", "lost") else got["kind"]
        logger.debug(f"Zepto typed search {keyword!r}: {got['error']}")
        return _failed(session, kind, got["error"])
    return build(got["rows"], got["hit_break"], cap, session["store_id"], distinct_ad_slots)


def usage(session: dict) -> str | None:
    """One line on what a typed session cost, for the log when it closes."""
    st = session.get("typed")
    if st is None:
        return None
    return (f"{st.searches} searches, {st.calls} calls reached Zepto, {st.refused} refused, "
            f"{st.bytes / 1_048_576:.1f} MB")
