"""Blinkit blocks and cut-short searches (2026-10-02) — blinkit public_data/scraper.py.

Until now a Cloudflare block was not recognised as one. `in_page_fetch` re-sent the
request three more times within ~5 s, the search then counted as an ordinary failure,
and two of those skipped the rest of the store — the likely mechanism behind the
2026-09-25 run that stopped at 1,439 of 2,456 locations. And a search whose page 2
failed came back `ok` with page 1 only, so share of voice was stated over 12 of 36
products as if they were all.

These pin: blocks are classified and handed back at once (for the scrape pools only —
the campaign manager keeps its retries); each kind has its remedy; a cut-short search
is flagged and the orchestrators retry it instead of storing it.

No browser: the page is a scripted fake. Run:
    python -m scraper.platforms.blinkit.public_data.tests.test_blocks
"""
import asyncio

from scraper.platforms.blinkit.public_data import endpoints as ep
from scraper.platforms.blinkit.public_data import scraper as bs
from scraper.public.providers import get_provider


# ── scripted page ────────────────────────────────────────────────────────────

def _snippet(pid: int, position: int) -> dict:
    return {
        "data": {"atc_action": {"add_to_cart": {"cart_item": {
            "product_id": pid, "product_name": f"Dobra Soda {pid}", "brand": "Dobra",
            "price": 20, "mrp": 25, "unit": "200 ml", "inventory": 5,
            "merchant_id": 101, "merchant_type": "express"}}}},
        "tracking": {"common_attributes": {"product_position": str(position)}},
    }


def _page(first: int, n: int, more: bool) -> dict:
    nxt = (f"/v1/layout/search?offset={first + n}&search_method=basic&search_count=40"
           if more else None)
    return {"status": 200, "body": {"response": {
        "snippets": [_snippet(first + i, first + i) for i in range(n)],
        "pagination": {"next_url": nxt}}}}


CF_PAGE = {"status": 403, "body": None, "error": "non-JSON body (Cloudflare?)",
           "head": "<!DOCTYPE html><html><head><title>Just a moment...</title>"}
RATE = {"status": 429, "body": {"error": "too many"}}
SERVER = {"status": 500, "body": {"error": "oops"}}
FORBIDDEN = {"status": 403, "body": {"message": "forbidden"}}
DOWN = {"status": 0, "error": "TypeError: Failed to fetch"}


class _Page:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    async def evaluate(self, js, payload):
        self.calls += 1
        return self.answers.pop(0) if self.answers else self.answers_last

    @property
    def answers_last(self):
        return {"status": 0, "error": "script ran out"}


def _session(page, retry_blocks=False):
    return {"page": page, "headers": {"auth_key": "x"}, "retry_blocks": retry_blocks}


def _no_retry_waits():
    orig = bs._RETRY_DELAYS
    bs._RETRY_DELAYS = (0.0, 0.0, 0.0)
    return orig


# ── what an answer was ───────────────────────────────────────────────────────

def test_classify():
    assert bs.classify(_page(1, 1, False)) == "ok"
    assert bs.classify(RATE) == "rate"
    assert bs.classify(CF_PAGE) == "challenge"
    assert bs.classify({**CF_PAGE, "status": 503}) == "challenge"
    assert bs.classify({**CF_PAGE, "status": 200}) == "challenge"   # an interstitial
    assert bs.classify(FORBIDDEN) == "forbidden"
    assert bs.classify(SERVER) == "error"
    assert bs.classify(DOWN) == "error"                            # transport, not a block


def test_a_cloudflare_page_is_named_by_its_title():
    assert bs._detail(CF_PAGE) == "HTTP 403 · Just a moment..."
    assert bs._detail(DOWN) == "HTTP 0 · TypeError: Failed to fetch"


# ── the pools stop re-sending blocks; the campaign manager does not change ──

def test_pool_sessions_hand_a_block_back_at_once():
    page = _Page(RATE, _page(1, 1, False))
    resp = asyncio.run(bs.in_page_fetch(page, "u", {}, None, retry_blocks=False))
    assert resp["status"] == 429 and page.calls == 1


def test_the_default_still_retries_for_the_campaign_manager():
    orig = _no_retry_waits()
    try:
        page = _Page(RATE, _page(1, 1, False))
        resp = asyncio.run(bs.in_page_fetch(page, "u", {}, None))
    finally:
        bs._RETRY_DELAYS = orig
    assert resp["status"] == 200 and page.calls == 2


def test_transport_failures_are_still_retried_by_the_pools():
    orig = _no_retry_waits()
    try:
        page = _Page(DOWN, _page(1, 1, False))
        resp = asyncio.run(bs.in_page_fetch(page, "u", {}, None, retry_blocks=False))
    finally:
        bs._RETRY_DELAYS = orig
    assert resp["status"] == 200 and page.calls == 2


def test_pool_sessions_are_marked_and_others_are_not():
    orig = bs._make_session

    async def _make(browser, lat, lon):
        return {"page": None, "headers": {}}

    bs._make_session = _make
    try:
        pooled = asyncio.run(bs.open_context_session(None, 12.9, 77.6))
    finally:
        bs._make_session = orig
    assert pooled["retry_blocks"] is False
    assert _session(None, retry_blocks=True)["retry_blocks"] is True


# ── search(): blocks, cut-short lists ────────────────────────────────────────

def test_a_first_page_block_is_reported_as_one():
    res = asyncio.run(bs.search(_session(_Page(CF_PAGE)), "soda", 36))
    assert not res["ok"] and res["blocked"] and res["kind"] == "challenge"
    assert "Just a moment" in res["error"] and not res["truncated"]


def test_a_later_page_failing_flags_the_list_as_cut_short():
    page = _Page(_page(1, 12, True), SERVER)
    res = asyncio.run(bs.search(_session(page), "soda", 36))
    assert res["ok"] and res["truncated"] and not res["blocked"]
    assert len(res["products"]) == 12 and "page 2 failed after 12 products" in res["error"]


def test_a_later_page_blocked_is_a_block_and_cut_short():
    page = _Page(_page(1, 12, True), RATE)
    res = asyncio.run(bs.search(_session(page), "soda", 36))
    assert res["blocked"] and res["kind"] == "rate" and res["truncated"]


def test_a_whole_search_is_not_flagged():
    page = _Page(_page(1, 12, True), _page(13, 12, True), _page(25, 12, False))
    res = asyncio.run(bs.search(_session(page), "soda", 36))
    assert res["ok"] and not res["truncated"] and not res["blocked"]
    assert res["kind"] == "ok" and len(res["products"]) == 36


# ── how each kind is met ─────────────────────────────────────────────────────

def test_block_remedy():
    assert bs.block_remedy("rate", 1) == (ep.RATE_PAUSE_S, False)        # same session
    assert bs.block_remedy("challenge", 1) == (0.0, True)               # new session now
    assert bs.block_remedy("forbidden", 1) == (ep.FORBIDDEN_PAUSE_S, True)
    ladder = ep.RECOVERY_WAITS_S
    assert bs.block_remedy("rate", 2) == (float(ladder[1]), False)
    assert bs.block_remedy("rate", len(ladder)) == (float(ladder[-1]), True)


def test_the_blinkit_provider_carries_it():
    p = get_provider("blinkit")
    assert p.block_remedy is bs.block_remedy
    assert p.block_give_up_s == ep.BLOCK_GIVE_UP_S
    assert p.gap_max_s is None and p.search_gap_s == 0.0     # pacing untouched


# ── the orchestrators retry a cut-short search instead of storing it ─────────

def test_a_cut_short_search_is_retried_not_stored():
    from scraper.public.tests.test_run_outcome import (
        _keyword_run, _loc, _ok, _patched, _provider, _rows,
    )

    def answer(kw, mid, n):
        res = _ok(mid)
        if mid == "m1" and n == 1:
            res = {**res, "truncated": True, "error": "page 2 failed after 12 products"}
        return res

    p = _provider(answer)
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]) as tmp:
        s = _keyword_run()
        stored = _rows(tmp, "SELECT merchant_id FROM search_snapshots ORDER BY id")
    assert s["status"] == "success" and s["errors"] == 1 and s["recovered"] == 1
    assert len(stored) == 3                     # m1 stored ONCE — from the retry


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} Blinkit block tests passed.")
