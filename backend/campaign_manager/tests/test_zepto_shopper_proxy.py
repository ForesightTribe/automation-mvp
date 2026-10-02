"""Zepto's shopper search through a proxy (2026-09-30) — the switch and what it changes.

Zepto's firewall refuses the VM's own address, so there the bid engine's rank and stock reads
go out through a proxy, searching by typed search (`typed_search.py`). These pin the wiring:

  * OFF by default, and then nothing changes — same call, same session;
  * ON without a usable address holds the run rather than quietly going direct;
  * the address's login never appears in an error or a log line;
  * a proxy that did not connect says so, in words a client can read in History;
  * a proxied run stops waiting out refusals once it has spent its wait budget;
  * a one-page stock read does not claim to have seen the whole brand.

No browser, no proxy, no Zepto.

    python -m campaign_manager.tests.test_zepto_shopper_proxy
"""
import asyncio

from campaign_manager import bid, config
from campaign_manager.marketplaces.zepto import adapter, catalog

SECRET = "http://user-name:p%40ss-w0rd@res.example.com:10000"


def _with_proxy(on: bool, address: str = SECRET):
    """Decorator: run the test with the switch set, and put it back."""
    def wrap(fn):
        def run():
            saved = (config.ZEPTO_SHOPPER_PROXY_ON, config.ZEPTO_SHOPPER_PROXY)
            config.ZEPTO_SHOPPER_PROXY_ON, config.ZEPTO_SHOPPER_PROXY = on, address
            try:
                return fn()
            finally:
                config.ZEPTO_SHOPPER_PROXY_ON, config.ZEPTO_SHOPPER_PROXY = saved
        run.__name__, run.__doc__ = fn.__name__, fn.__doc__
        return run
    return wrap


# ── the switch ───────────────────────────────────────────────────────────────

def test_the_proxy_is_off_by_default():
    assert config.ZEPTO_SHOPPER_PROXY_ON is False
    assert adapter.shopper_proxy() is None


@_with_proxy(False)
def test_an_address_alone_does_not_turn_it_on():
    assert adapter.shopper_proxy() is None


@_with_proxy(True)
def test_on_gives_playwright_the_server_and_the_decoded_login():
    assert adapter.shopper_proxy() == {"server": "http://res.example.com:10000",
                                       "username": "user-name", "password": "p@ss-w0rd"}


@_with_proxy(True, "http://res.example.com:10000")
def test_a_proxy_without_a_login_is_fine():
    assert adapter.shopper_proxy() == {"server": "http://res.example.com:10000"}


def _refused(address):
    @_with_proxy(True, address)
    def check():
        try:
            adapter.shopper_proxy()
        except RuntimeError as e:
            return str(e)
        raise AssertionError(f"{address!r} must be refused")
    return check()


def test_on_without_a_usable_address_is_refused_not_quietly_direct():
    for bad in ("", "res.example.com:10000", "http://res.example.com",
                "socks5://user:pw@res.example.com:1080", "http://user:pw@:10000",
                "http://user:pw@res.example.com:notaport"):
        said = _refused(bad)
        assert "CM_ZEPTO_SHOPPER_PROXY" in said


def test_a_refused_address_never_shows_its_login():
    said = _refused("socks5://user-name:p%40ss-w0rd@res.example.com:1080")
    assert "user-name" not in said and "p%40ss" not in said and "p@ss" not in said


def test_the_printable_form_is_host_and_port_only():
    assert adapter.proxy_label({"server": "http://res.example.com:10000", "username": "u",
                                "password": "p"}) == "res.example.com:10000"
    assert adapter.proxy_label(None) == ""


# ── opening the session ──────────────────────────────────────────────────────

class _Driver:
    stopped = False

    async def stop(self):
        self.stopped = True


def _open(open_session):
    """Run `open_position_session` against a fake scraper and a fake Playwright driver.
    Returns (result or the exception, the driver)."""
    import playwright.async_api as pwa
    from scraper.platforms.zepto.public_data import scraper as zs

    driver = _Driver()

    class _Starter:
        async def start(self):
            return driver

    saved = (pwa.async_playwright, zs.open_session)
    pwa.async_playwright, zs.open_session = (lambda: _Starter()), open_session
    try:
        try:
            return asyncio.run(adapter.open_position_session(None, 12.97, 77.57)), driver
        except Exception as e:
            return e, driver
    finally:
        pwa.async_playwright, zs.open_session = saved


def test_off_opens_the_session_exactly_as_before():
    seen = []

    async def _open_session(pw, lat, lon, **kw):
        seen.append(kw)
        return {"page": object()}
    session, _ = _open(_open_session)
    assert seen == [{}], "no proxy, no typed search, no new arguments when the switch is off"
    assert "_wait_budget_s" not in session


@_with_proxy(True)
def test_on_opens_a_proxied_typed_session_with_a_wait_budget():
    seen = []

    async def _open_session(pw, lat, lon, **kw):
        seen.append(kw)
        return {"page": object()}
    session, _ = _open(_open_session)
    (kw,) = seen
    assert kw["proxy"]["server"] == "http://res.example.com:10000"
    assert kw["typed"] is True
    assert session["_wait_budget_s"] == config.ZEPTO_SHOPPER_WAIT_BUDGET_S


@_with_proxy(True, "")
def test_on_without_an_address_fails_before_any_browser_starts():
    async def _must_not_run(*a, **k):
        raise AssertionError("no session may be opened")
    err, driver = _open(_must_not_run)
    assert isinstance(err, RuntimeError) and "CM_ZEPTO_SHOPPER_PROXY" in str(err)
    assert driver.stopped is False, "the driver was never started, so never stopped"


@_with_proxy(True)
def test_a_proxy_that_did_not_connect_says_so_and_a_client_can_read_it():
    async def _open_session(pw, lat, lon, *, why=None, **kw):
        why["nav_error"] = "Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED at https://www.zepto.com/"
        return None
    err, driver = _open(_open_session)
    assert isinstance(err, RuntimeError) and driver.stopped
    said = str(err)
    assert "Zepto shopper proxy did not connect" in said and "res.example.com:10000" in said
    assert "user-name" not in said and "p@ss" not in said
    plain = bid._plain(err, "Zepto's shopper search could not be opened")
    assert "was not available; it is retried next check" in plain
    assert "ERR_TUNNEL" not in plain


@_with_proxy(True)
def test_a_session_zepto_refused_through_the_proxy_is_not_blamed_on_the_proxy():
    async def _open_session(pw, lat, lon, *, why=None, **kw):
        return None                       # the page loaded, its warm-up search never fired
    err, _ = _open(_open_session)
    said = str(err)
    assert "did not connect" not in said
    assert "through the proxy res.example.com:10000" in said
    assert "Zepto did not answer the warm-up search" in said


def test_off_keeps_the_old_failure_message():
    async def _open_session(pw, lat, lon, **kw):
        return None
    err, driver = _open(_open_session)
    assert "could not open a consumer search session at" in str(err) and driver.stopped


# ── waiting out refusals ─────────────────────────────────────────────────────

GATE = {"ok": False, "blocked": True, "kind": "gate", "error": "HTTP 299", "products": []}
FOUND = {"ok": True, "blocked": False, "kind": "ok", "error": "", "products": [{"name": "x"}]}


def _fetch(session, answers):
    """`fetch_positions` with the scraper and the clock faked. Returns (result or the
    exception, seconds slept)."""
    from scraper.platforms.zepto.public_data import scraper as zs

    slept, queue = [], list(answers)

    async def _search(*a, **k):
        return queue.pop(0)

    async def _sleep(s):
        slept.append(s)

    saved = (zs.search, asyncio.sleep)
    zs.search, asyncio.sleep = _search, _sleep
    try:
        try:
            coro = adapter.fetch_positions(session, "milk", 12.9, 77.5, merchant_id="s1")
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro), slept
            finally:
                loop.close()
        except Exception as e:
            return e, slept
    finally:
        zs.search, asyncio.sleep = saved


def test_without_a_budget_a_refused_search_waits_and_retries_as_before():
    session = {}
    out, slept = _fetch(session, [GATE, FOUND])
    assert out == [{"name": "x"}] and slept == [60.0]
    assert "_waited_s" in session


def test_without_a_budget_a_second_refusal_is_not_waited_out():
    out, slept = _fetch({}, [GATE, GATE, FOUND])
    assert isinstance(out, RuntimeError) and slept == [60.0]


def test_a_proxied_run_keeps_retrying_a_refusal_while_its_budget_lasts():
    """The 2026-10-01 case: refused for ~2 minutes after the warm-up. One retry gave up on a
    search that the next minute would have answered."""
    session = {"_wait_budget_s": 180.0}
    out, slept = _fetch(session, [GATE, GATE, FOUND])
    assert out == [{"name": "x"}] and slept == [60.0, 60.0]
    assert session["_waited_s"] == 120.0


def test_a_proxied_run_stops_waiting_once_its_budget_is_spent():
    session = {"_wait_budget_s": 120.0}
    out, slept = _fetch(session, [GATE, GATE, GATE, FOUND])   # 60 + 60, then the budget is gone
    assert isinstance(out, RuntimeError) and "blocked" in str(out)
    assert slept == [60.0, 60.0]
    out, slept = _fetch(session, [GATE, FOUND])               # later searches: no waiting at all
    assert isinstance(out, RuntimeError) and slept == []
    assert session["_waited_s"] == 120.0


# ── the stock read ───────────────────────────────────────────────────────────

def _brand_page(n_ours, n_total):
    return [{"variant_id": f"v{i}", "name": f"P{i}", "brand": "Brik Oven" if i < n_ours else "Other"}
            for i in range(n_total)]


def test_a_full_one_page_read_with_ours_to_the_end_is_not_complete():
    """30 rows of ours on a full page, asked for 48: the brand may well continue on the page
    a typed search never reads. Calling that complete would mark the rest "not sold here"."""
    res = {"ok": True, "error": "", "merchant_id": "s1", "products": _brand_page(30, 30),
           "capped_at": 30}
    assert catalog.summarise(res, 48, {"brik oven"})["complete"] is False


def test_a_full_page_whose_tail_is_other_brands_is_complete():
    res = {"ok": True, "error": "", "merchant_id": "s1", "products": _brand_page(5, 30),
           "capped_at": 30}
    assert catalog.summarise(res, 48, {"brik oven"})["complete"] is True


def test_a_short_page_is_complete_as_before():
    res = {"ok": True, "error": "", "merchant_id": "s1", "products": _brand_page(5, 8)}
    assert catalog.summarise(res, 48, {"brik oven"})["complete"] is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} shopper-proxy tests passed.")
