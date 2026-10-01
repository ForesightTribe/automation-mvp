"""Typed search — Zepto searched through the page's own search box (2026-09-30).

The proxied bid session cannot replay its search (Zepto refuses that through a proxy), so it
types the keyword into Zepto's page and reads the page's own answer. These pin the rules that
were learned the hard way on live runs (`zepto-cm-exp/PROXY-TESTS.md`):

  * after Enter the page sends several results calls and only ONE is the answer — the
    previous keyword's re-sent call must never be read as this keyword's list;
  * exactly one call per search leaves the browser;
  * a refusal arrives as a request that merely "failed" — it must come back as the same
    `gate` the replay path reports, not as "nothing found";
  * a list served by any other store is a failure, not a result.

No browser and no Zepto: the page is a script that plays back what the real one does.

    python -m scraper.platforms.zepto.public_data.tests.test_typed_search
"""
import asyncio
import json
import time

from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import scraper as zs
from scraper.platforms.zepto.public_data import typed_search as ts

STORE = "store-A"
OTHER_STORE = "store-B"


# ── what Zepto's page sends, as request bodies ───────────────────────────────

def typing(q):
    return {"query": q, "pageNumber": 0, "mode": "TYPED", "userSessionId": "s"}


def results(q, *, intent=True, page=0, mode="AUTOSUGGEST"):
    body = {"query": q, "pageNumber": page, "mode": mode, "userSessionId": "s"}
    if intent:
        body["intentId"] = "i"
    return body


def answer(names, store=STORE, *, ended=False):
    """A search response carrying `names` as products of `store`."""
    items = [{"position": i, "productResponse": {
        "storeId": store, "product": {"id": f"p{n}", "name": n},
        "productVariant": {"id": f"v{n}"}}} for i, n in enumerate(names)]
    layout = [{"widgetId": ep.PRODUCT_GRID_WIDGET,
               "data": {"resolver": {"data": {"items": items}}}}]
    if ended:
        layout.append({"widgetId": "HEADER_WIDGET"})
    return {"layout": layout}


# ── a page that plays a script ───────────────────────────────────────────────

class _Request:
    def __init__(self, body):
        self.url, self.method, self.resource_type = ep.search_url(), "POST", "xhr"
        self.post_data = json.dumps(body)
        self.headers = {"x-from-page": "1", "store_id": "the-page's-own-store"}
        self.failure = None


class _Route:
    def __init__(self, request):
        self.request, self.action, self.headers = request, None, None

    async def abort(self):
        self.action = "abort"

    async def continue_(self, headers=None):
        self.action, self.headers = "continue", headers


class _Response:
    def __init__(self, request, status, body):
        self.request, self.status, self._body = request, status, body

    async def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class _CDP:
    def __init__(self):
        self.handlers = {}

    async def send(self, *a, **k):
        pass

    def on(self, event, fn):
        self.handlers[event] = fn


class _Context:
    def __init__(self, cdp, page):
        self._cdp, self._page = cdp, page

    def on(self, event, fn):
        pass

    async def route(self, pattern, handler):
        self._page._handler = handler

    async def new_cdp_session(self, page):
        if self._cdp is None:
            raise RuntimeError("no CDP here")
        return self._cdp


class _Box:
    def __init__(self, page):
        self.page = page
        self.first = self

    async def count(self):
        return 1 if self.page.has_box else 0

    async def click(self, **k):
        pass

    async def focus(self):
        pass


class _Keyboard:
    def __init__(self, page):
        self.page = page

    async def press(self, key):
        if key == "Enter":
            await self.page.enter()

    async def type(self, text, delay=0):
        self.page.typed = text


class _Page:
    """`script(keyword)` → what the page sends after Enter, in order:
    `(body, outcome)`; outcome is a response body (answered 200), `("status", n)` (a
    readable non-200), `("blocked", n)` (answered n WITHOUT the cross-site header — the
    browser blocks it) or `("dies", text)` (the request fails on the wire)."""

    def __init__(self, script, *, cdp=True):
        self.script, self.has_box, self.typed = script, True, ""
        self.url = ep.WARMUP_SEARCH_URL
        self.listeners: dict[str, list] = {}
        self.routes: list[_Route] = []
        self.gotos: list[str] = []
        self.cdp = _CDP() if cdp else None
        self.context = _Context(self.cdp, self)
        self.keyboard = _Keyboard(self)
        self._handler = None

    def on(self, event, fn):
        self.listeners.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        self.listeners[event].remove(fn)

    def emit(self, event, arg):
        for fn in list(self.listeners.get(event, [])):
            fn(arg)

    def locator(self, selector):
        return _Box(self)

    async def wait_for_timeout(self, ms):
        pass

    async def wait_for_load_state(self, *a, **k):
        pass

    async def goto(self, url, **k):
        self.gotos.append(url)
        self.url, self.has_box = url, True

    async def enter(self):
        for n, (body, outcome) in enumerate(self.script(self.typed)):
            req = _Request(body)
            route = _Route(req)
            await self._handler(route)
            self.routes.append(route)
            if route.action != "continue":
                continue
            if self.cdp:
                self.cdp.handlers["Network.requestWillBeSent"](
                    {"requestId": str(n), "request": {"url": req.url, "method": "POST"}})
            if isinstance(outcome, dict) or outcome is None:
                self.emit("response", _Response(req, 200, outcome))
            elif outcome[0] == "status":
                self.emit("response", _Response(req, outcome[1], None))
            elif outcome[0] == "blocked":
                if self.cdp:
                    self.cdp.handlers["Network.responseReceivedExtraInfo"](
                        {"requestId": str(n), "statusCode": outcome[1],
                         "headers": {"Server": "CloudFront"}})
                req.failure = "net::ERR_FAILED"
                self.emit("requestfailed", req)
            else:
                req.failure = outcome[1]
                self.emit("requestfailed", req)

    def sent(self):
        """The calls that left the browser, as (query, headers)."""
        return [(json.loads(r.request.post_data)["query"], r.headers)
                for r in self.routes if r.action == "continue"]


def _fast(fn):
    """No real waiting: the page is a script."""
    def run():
        saved = (ep.TYPED_AFTER_S, ep.TYPED_GAP_S, ep.TYPED_ANSWER_S)
        ep.TYPED_AFTER_S, ep.TYPED_GAP_S, ep.TYPED_ANSWER_S = 0.0, 0.0, 0.6
        try:
            fn()
        finally:
            ep.TYPED_AFTER_S, ep.TYPED_GAP_S, ep.TYPED_ANSWER_S = saved
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


def _session(script, **kw):
    page = _Page(script, **kw)
    session = {"page": page, "context": page.context, "store_id": "", "secondary_ids": (),
               "minted_at": time.monotonic()}
    async def _open():
        await ts.attach(session)
        await ts.arm(session)
    asyncio.run(_open())
    return session, page


def _search(session, keyword, store=STORE, **kw):
    return asyncio.run(zs.search(session, keyword, merchant_id=store, **kw))


def _names(res):
    return [p["name"] for p in res["products"]]


# ── verdict: what each of the page's calls is ────────────────────────────────

def test_only_our_keywords_first_page_with_a_search_id_is_ours():
    assert ts.verdict(json.dumps(results("milk")), "milk") == ts.OURS
    assert ts.verdict(json.dumps(results("milk", mode="SHOW_ALL_RESULTS")), "milk") == ts.OURS
    assert ts.verdict(json.dumps(typing("mil")), "milk") == ts.TYPING
    assert ts.verdict(json.dumps(results("paneer")), "milk") == ts.STALE
    assert ts.verdict(json.dumps(results("milk", intent=False)), "milk") == ts.BARE
    assert ts.verdict(json.dumps(results("milk", page=1)), "milk") == ts.DEEPER
    assert ts.verdict(json.dumps({"query": "milk", "mode": "SOMETHING_NEW"}), "milk") == ts.UNKNOWN
    assert ts.verdict("not json", "milk") == ts.UNKNOWN
    assert ts.verdict("[1, 2]", "milk") == ts.UNKNOWN


def test_between_searches_nothing_is_ours():
    assert ts.verdict(json.dumps(results("milk")), None) == ts.STALE


def test_the_keyword_match_ignores_case_and_spacing():
    assert ts.verdict(json.dumps(results("Sourdough  Bread ")), ts.norm("sourdough bread")) == ts.OURS


def test_trackers_analytics_and_images_are_dead_weight_but_zepto_and_its_firewall_are_not():
    for kind, url in (("script", "https://www.googletagmanager.com/gtm.js?id=x"),
                      ("script", "https://connect.facebook.net/en_US/fbevents.js"),
                      ("xhr", "https://events.zepto.co.in/api/v1/publish-events"),
                      ("image", "https://cdn.zeptonow.com/a.png"),
                      ("font", "https://cdn.zeptonow.com/a.woff2")):
        assert ts.dead_weight(kind, url), url
    for kind, url in (("script", "https://cdn.zeptonow.com/_next/static/chunks/main.js"),
                      ("document", "https://www.zepto.com/search?query=milk"),
                      ("xhr", ep.search_url()),
                      ("script", "https://x.ap-south-1.token.awswaf.com/challenge.js"),
                      ("fetch", "https://x.ap-south-1.token.awswaf.com/verify"),
                      ("script", "https://notfacebook.com.example/x.js")):
        assert not ts.dead_weight(kind, url), url


@_fast
def test_the_warm_ups_own_search_goes_out_untouched():
    """Before `arm`, a search call is the warm-up's: it reaches Zepto as the page sent it —
    the sequence validated on the VM (stopping it made no difference, 2026-10-01)."""
    page = _Page(lambda kw: [])
    session = {"page": page, "context": page.context, "store_id": "", "minted_at": 0}
    asyncio.run(ts.attach(session))
    route = _Route(_Request(results("bread", mode="SHOW_ALL_RESULTS")))
    asyncio.run(page._handler(route))
    assert route.action == "continue" and route.headers is None


# ── the search, end to end against the scripted page ─────────────────────────

@_fast
def test_the_previous_keywords_answer_is_never_read_as_this_keywords():
    """THE rule. The page re-sends the previous keyword's search after Enter, and it can come
    first — reading "the first results answer" reported paneer's list as milk's."""
    def script(kw):
        return [(typing(kw[:2]), None),
                (results("paneer"), answer(["Paneer 1", "Paneer 2"])),     # A — arrives FIRST
                (results(kw), answer(["Milk 1", "Milk 2", "Milk 3"])),      # B
                (results(kw, intent=False), answer([]))]                    # C
    session, page = _session(script)
    res = _search(session, "milk")
    assert res["ok"] and res["kind"] == "ok"
    assert _names(res) == ["Milk 1", "Milk 2", "Milk 3"]
    assert [p["position"] for p in res["products"]] == [1, 2, 3]
    assert [q for q, _ in page.sent()] == ["milk"], "exactly one call may leave the browser"


@_fast
def test_the_one_call_that_leaves_is_bound_to_our_store():
    session, page = _session(lambda kw: [(results(kw), answer(["Milk 1"]))])
    res = _search(session, "milk")
    (_, headers), = page.sent()
    assert headers["store_id"] == headers["storeid"] == STORE
    assert headers["store_ids"] == STORE
    assert headers["x-from-page"] == "1", "the page's own headers must survive the swap"
    assert res["merchant_id"] == STORE


@_fast
def test_a_list_from_another_store_is_a_failure_not_a_result():
    session, _ = _session(lambda kw: [(results(kw), answer(["Milk 1"], store=OTHER_STORE))])
    res = _search(session, "milk")
    assert not res["ok"] and not res["blocked"] and res["products"] == []
    assert OTHER_STORE in res["error"]


@_fast
def test_the_same_keyword_at_the_next_store_is_searched_again():
    """Two automations on one keyword in two cities: the page's re-sent call IS our keyword,
    so it is the one let through — bound to the new store."""
    served = {"n": 0}

    def script(kw):
        served["n"] += 1
        store = STORE if served["n"] == 1 else OTHER_STORE
        return [(results(kw), answer([f"Milk at {store}"], store=store)),
                (results(kw), answer(["a second copy"], store=store))]
    session, page = _session(script)
    first = _search(session, "milk", STORE)
    second = _search(session, "milk", OTHER_STORE)
    assert _names(first) == [f"Milk at {STORE}"] and _names(second) == [f"Milk at {OTHER_STORE}"]
    assert [h["store_id"] for _, h in page.sent()] == [STORE, OTHER_STORE]


@_fast
def test_a_blocked_answer_is_the_login_gate_not_an_empty_list():
    """HTTP 299 without the cross-site header: the browser blocks it and the request just
    "fails". It must come back blocked, as `gate` — the caller waits a minute for that."""
    session, _ = _session(lambda kw: [(results(kw), ("blocked", 299))])
    res = _search(session, "milk")
    assert not res["ok"] and res["blocked"] and res["kind"] == "gate"
    assert "299" in res["error"] and res["products"] == []
    assert session["typed"].refused == 1


@_fast
def test_a_blocked_answer_is_still_a_gate_when_the_network_layer_cannot_be_watched():
    session, _ = _session(lambda kw: [(results(kw), ("blocked", 299))], cdp=False)
    res = _search(session, "milk")
    assert res["blocked"] and res["kind"] == "gate"


@_fast
def test_a_blocked_429_is_a_rate_limit():
    session, _ = _session(lambda kw: [(results(kw), ("blocked", 429))])
    res = _search(session, "milk")
    assert res["blocked"] and res["kind"] == "rate"


@_fast
def test_a_readable_refusal_is_classified_by_its_status():
    session, _ = _session(lambda kw: [(results(kw), ("status", 299))])
    assert _search(session, "milk")["kind"] == "gate"


@_fast
def test_a_request_that_dies_on_the_wire_is_an_error_not_a_block():
    session, _ = _session(lambda kw: [(results(kw), ("dies", "net::ERR_TUNNEL_CONNECTION_FAILED"))])
    res = _search(session, "milk")
    assert not res["ok"] and not res["blocked"] and res["kind"] == "error"
    assert "ERR_TUNNEL" in res["error"]


@_fast
def test_a_page_that_never_searches_is_reloaded_and_asked_once_more():
    tries = {"n": 0}

    def script(kw):
        tries["n"] += 1
        return [] if tries["n"] == 1 else [(results(kw), answer(["Milk 1"]))]
    session, page = _session(script)
    res = _search(session, "milk")
    assert res["ok"] and _names(res) == ["Milk 1"]
    assert page.gotos == [ep.TYPED_SEARCH_PAGE]


@_fast
def test_a_page_that_never_searches_twice_is_an_error():
    session, page = _session(lambda kw: [])
    res = _search(session, "milk")
    assert not res["ok"] and not res["blocked"] and res["kind"] == "error"
    assert "did not send the search" in res["error"]
    assert page.sent() == []


@_fast
def test_a_dead_pass_is_reminted_and_the_search_asked_again():
    tries = {"n": 0}

    def script(kw):
        tries["n"] += 1
        return [(results(kw), ("blocked", 202) if tries["n"] == 1 else answer(["Milk 1"]))]
    session, page = _session(script)
    res = _search(session, "milk")
    assert res["ok"] and page.gotos == [ep.TYPED_SEARCH_PAGE]


@_fast
def test_an_old_pass_is_reminted_before_the_search():
    session, page = _session(lambda kw: [(results(kw), answer(["Milk 1"]))])
    session["minted_at"] = time.monotonic() - ep.PASS_REFRESH_S - 1
    assert _search(session, "milk")["ok"]
    assert page.gotos == [ep.TYPED_SEARCH_PAGE]
    assert time.monotonic() - session["minted_at"] < 5


@_fast
def test_no_store_id_is_refused_without_touching_the_page():
    session, page = _session(lambda kw: [(results(kw), answer(["Milk 1"]))])
    res = asyncio.run(zs.search(session, "milk"))
    assert not res["ok"] and "store's id" in res["error"] and page.routes == []


@_fast
def test_an_empty_answer_for_our_keyword_is_an_answer():
    """Nothing matched the keyword at this store — the replay path says ok with no products,
    and so does this one. (The `intentId`-less copy that is always empty never gets here.)"""
    session, _ = _session(lambda kw: [(results(kw), answer([]))])
    res = _search(session, "zzzz")
    assert res["ok"] and res["products"] == []


@_fast
def test_the_usage_line_counts_searches_calls_and_refusals():
    script = lambda kw: [(results(kw), ("blocked", 299) if kw == "eggs" else answer(["x"]))]
    session, _ = _session(script)
    _search(session, "milk")
    _search(session, "eggs")
    said = ts.usage(session)
    assert "2 searches" in said and "2 calls reached Zepto" in said and "1 refused" in said


# ── build: one answered page → the shared result shape ───────────────────────

def _rows(n, store=STORE, ad_at=()):
    return [{"variant_id": f"v{i}", "name": f"P{i}", "merchant_id": store,
             "position": i + 1, "is_ad": i in ad_at} for i in range(n)]


def test_a_full_page_says_how_far_it_got():
    out = ts.build(_rows(ep.TYPED_PAGE_ROWS), False, 48, STORE, True)
    assert out["ok"] and out["capped_at"] == ep.TYPED_PAGE_ROWS


def test_a_short_page_or_one_the_results_ended_in_is_the_whole_list():
    assert "capped_at" not in ts.build(_rows(12), False, 48, STORE, True)
    assert "capped_at" not in ts.build(_rows(ep.TYPED_PAGE_ROWS), True, 48, STORE, True)


def test_the_cap_still_applies():
    out = ts.build(_rows(30), False, 10, STORE, True)
    assert out["total_results"] == 10 and out["capped_at"] == 10


def test_a_products_ad_and_organic_slots_are_both_kept_unless_asked_otherwise():
    rows = _rows(2) + [{"variant_id": "v0", "name": "P0", "merchant_id": STORE,
                        "position": 3, "is_ad": True}]
    assert ts.build(list(rows), False, 30, STORE, True)["total_results"] == 3
    assert ts.build(list(rows), False, 30, STORE, False)["total_results"] == 2


# ── the seams into the shared scraper ────────────────────────────────────────

def test_search_hands_a_typed_session_to_the_typed_path():
    """One entry point for callers: `scraper.search` passes a typed session straight on."""
    called = []
    saved = ts.search

    async def _typed(*a, **k):
        called.append(1)
        return {}
    ts.search = _typed
    try:
        asyncio.run(zs.search({"typed": ts.State()}, "milk", merchant_id=STORE))
        assert called == [1]
    finally:
        ts.search = saved


class _Chromium:
    def __init__(self):
        self.calls = []

    async def launch(self, **kw):
        self.calls.append(kw)
        return object()


class _PW:
    def __init__(self):
        self.chromium = _Chromium()


def test_the_proxy_reaches_the_browser_only_when_one_is_given():
    pw = _PW()
    asyncio.run(zs.launch_browser(pw))
    asyncio.run(zs.launch_browser(pw, {"server": "http://h:1"}))
    plain, proxied = pw.chromium.calls
    assert "proxy" not in plain
    assert proxied["proxy"] == {"server": "http://h:1"}
    assert proxied["channel"] == plain["channel"] == ep.BROWSER_CHANNEL


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} typed-search tests passed.")
