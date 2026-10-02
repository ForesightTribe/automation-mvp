"""Meeting blocks and pacing (2026-10-01) — pacing.py, orchestrator._recover, zepto
scraper.block_remedy.

The 2026-09-29 Brik Oven keyword run took 8.4 h for what had taken ~1 h: 48 streaks of
block -> recover -> block, a median of 7 searches each. Three things made it so, and these
pin their replacements:

  * every block got one reflex — wait, then a NEW session — although two of Zepto's three
    mechanisms are connection-wide, so a new session only adds warm-up requests;
  * a fixed 2 s pace, clean in the afternoon, overshoots in the morning;
  * a worker gave up after 4 waits and the rest of the run was lost.

And the log said only "BLOCKED", so none of it could be diagnosed afterwards.

No browser, no database. Run:  python -m scraper.public.tests.test_zepto_blocks
"""
import asyncio
import time
from types import SimpleNamespace

from scraper.platforms.zepto.public_data import endpoints as ep
from scraper.platforms.zepto.public_data import scraper as zs
from scraper.public import pacing
from scraper.public.tests.test_run_outcome import (
    _keyword_run, _loc, _ok, _patched, _provider, _rows, _sku_run,
)


def _blocked(kind: str, status: int, body: str = "") -> dict:
    return {"ok": False, "products": [], "merchant_id": "", "total_results": 0,
            "blocked": True, "kind": kind, "error": f"HTTP {status} {body}".strip()}


GATE = _blocked("gate", 299, '{"error_code":"LOGIN_REQUIRED"}')
RATE = _blocked("rate", 429)
CHALLENGE = _blocked("challenge", 202)


def _fast_remedy(kind: str, streak: int):
    """Zepto's decisions (rebuild or not) with the waits shrunk to nothing."""
    _, rebuild = zs.block_remedy(kind, streak)
    return 0.001, rebuild


# ── Zepto's remedy table ─────────────────────────────────────────────────────

def test_rate_and_gate_wait_on_the_same_session():
    assert zs.block_remedy("rate", 1) == (ep.RATE_PAUSE_S, False)
    assert zs.block_remedy("gate", 1) == (ep.GATE_PAUSE_S, False)


def test_a_challenge_rebuilds_at_once():
    assert zs.block_remedy("challenge", 1) == (0.0, True)


def test_repeated_blocks_walk_the_ladder_and_rebuild_at_its_end():
    ladder = ep.RECOVERY_WAITS_S
    assert zs.block_remedy("gate", 2) == (float(ladder[1]), False)
    assert zs.block_remedy("gate", len(ladder)) == (float(ladder[-1]), True)
    assert zs.block_remedy("gate", 50) == (float(ladder[-1]), True)


def test_an_unknown_block_waits_and_starts_clean():
    wait, rebuild = zs.block_remedy("open_failed", 1)
    assert wait == float(ep.RECOVERY_WAITS_S[0]) and rebuild


def test_zepto_provider_carries_the_remedy_and_adaptive_pacing():
    from scraper.public.providers import get_provider
    p = get_provider("zepto")
    assert p.block_remedy is zs.block_remedy
    assert p.block_give_up_s == ep.BLOCK_GIVE_UP_S
    assert p.gap_floor_s == ep.PACE_FLOOR_S and p.gap_max_s == ep.GAP_MAX_S
    # Fixed pacing everywhere else. Blinkit has its OWN remedy since 2026-10-02 (see
    # blinkit public_data/tests/test_blocks.py); Instamart keeps the generic one.
    for slug in ("blinkit", "instamart"):
        assert get_provider(slug).gap_max_s is None
    assert get_provider("blinkit").block_remedy is not zs.block_remedy
    assert get_provider("instamart").block_remedy is None


# ── the orchestrators meet each kind correctly ───────────────────────────────

def test_a_gate_block_retries_on_the_same_session():
    p = _provider(lambda kw, mid, n: GATE if (mid == "m1" and n == 1) else _ok(mid),
                  block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]):
        s = _keyword_run()
    assert s["status"] == "success" and s["blocked"] == 1
    assert s["blocks_by_kind"] == {"gate": 1}
    assert len(p.opened) == 1                   # the one session it started with


def test_a_challenge_rebuilds_the_session():
    p = _provider(lambda kw, mid, n: CHALLENGE if (mid == "m1" and n == 1) else _ok(mid),
                  block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]):
        s = _keyword_run()
    assert s["status"] == "success" and s["blocks_by_kind"] == {"challenge": 1}
    assert len(p.opened) == 2                   # start + one rebuild


def test_every_block_is_recorded_with_its_kind_and_zeptos_words():
    def answer(kw, mid, n):
        if mid == "m0" and n == 1:
            return GATE
        if mid == "m1" and n == 1:
            return RATE
        return _ok(mid)

    p = _provider(answer, block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]) as tmp:
        s = _keyword_run()
        rows = _rows(tmp, "SELECT kind, detail, merchant_id, query, streak, phase "
                          "FROM blocks ORDER BY id")
    assert [r["kind"] for r in rows] == ["gate", "rate"]
    assert "LOGIN_REQUIRED" in rows[0]["detail"]
    assert rows[0]["merchant_id"] == "m0" and rows[0]["query"] == "soda"
    assert [r["streak"] for r in rows] == [1, 1]   # the answer between them reset it
    assert s["blocks_by_kind"] == {"gate": 1, "rate": 1}


def test_a_long_bad_patch_does_not_stop_the_worker():
    """A connection-wide bad patch — six blocks in a row, across three stores. The
    worker rides it out (a block only ends a worker after block_give_up_s), every store
    is reached, and the backlog pass collects the three pairs the patch cost."""
    n_calls = {"n": 0}

    def answer(kw, mid, n):
        n_calls["n"] += 1
        return GATE if n_calls["n"] <= 6 else _ok(mid)

    p = _provider(answer, block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(i) for i in range(4)], keywords=["soda"]) as tmp:
        s = _keyword_run()
        streaks = [r["streak"] for r in _rows(tmp, "SELECT streak FROM blocks ORDER BY id")]
    assert s["status"] == "success" and s["unattempted"] == 0
    assert s["blocked"] == 6 and s["recovered"] == 3 and s["pairs_done"] == 4
    assert streaks == [1, 2, 3, 4, 5, 6]


def test_a_wall_stops_the_worker_and_the_run_is_partial():
    """Nothing but blocks for block_give_up_s: not a rate limit — stop, leave the rest
    for --resume."""
    # Each wait (0.03 s) is a real fraction of the give-up (0.05 s), so the worker stops
    # after the 2nd-3rd block whatever the machine's speed — with near-zero waits a fast
    # machine could get through every store before the clock ran out.
    p = _provider(lambda kw, mid, n: GATE if mid != "m0" else _ok(mid),
                  block_remedy=lambda kind, n: (0.03, False), block_give_up_s=0.05)
    with _patched(p, locations=[_loc(i) for i in range(8)], keywords=["soda"]):
        s = _keyword_run()
    assert s["status"] == "partial"
    assert s["pairs_done"] == 1 and s["unattempted"] >= 1


def test_the_own_sku_scrape_meets_blocks_the_same_way():
    p = _provider(lambda q, mid, n: GATE if (mid == "m1" and n == 1) else _ok(mid),
                  block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(i) for i in range(3)]) as tmp:
        s = _sku_run()
        rows = _rows(tmp, "SELECT kind FROM blocks")
    assert s["status"] == "success" and s["blocks_by_kind"] == {"gate": 1}
    assert len(p.opened) == 1 and [r["kind"] for r in rows] == ["gate"]
    assert s["errors"] == 0 and s["recovered"] == 0     # retried in the main pass


def test_a_session_that_cannot_reopen_is_recorded_and_retried():
    # Start OK; the challenge's rebuild fails once, then works.
    opens = iter([True, False, True])
    p = _provider(lambda kw, mid, n: CHALLENGE if (mid == "m0" and n == 1) else _ok(mid),
                  opens=opens, block_remedy=_fast_remedy, block_give_up_s=60)
    with _patched(p, locations=[_loc(0), _loc(1)], keywords=["soda"]) as tmp:
        s = _keyword_run()
        kinds = [r["kind"] for r in _rows(tmp, "SELECT kind FROM blocks ORDER BY id")]
    assert s["status"] == "success"
    assert kinds == ["challenge", "open_failed"]


# ── adaptive pacing ──────────────────────────────────────────────────────────

def _pacer(**kw):
    prov = SimpleNamespace(gap_max_s=8.0, gap_floor_s=2.3, search_gap_s=2.0,
                           gap_backoff=1.5, gap_ease_after=3, gap_ease=1.25)
    for k, v in kw.items():
        setattr(prov, k, v)
    return pacing.new(prov)


def test_a_block_widens_the_gap_up_to_the_ceiling():
    p = _pacer()
    pacing.on_block(p)
    assert p["gap"] == 2.3 * 1.5
    for _ in range(10):
        pacing.on_block(p)
    assert p["gap"] == 8.0


def test_a_clean_stretch_eases_it_back_never_below_the_floor():
    p = _pacer()
    pacing.on_block(p)
    pacing.on_block(p)                           # 5.175
    for _ in range(3):
        pacing.on_clean(p)
    assert abs(p["gap"] - 5.175 / 1.25) < 1e-9
    for _ in range(300):
        pacing.on_clean(p)
    assert p["gap"] == 2.3


def test_a_block_resets_the_clean_count():
    p = _pacer()
    pacing.on_block(p)
    pacing.on_clean(p)
    pacing.on_clean(p)
    pacing.on_block(p)
    pacing.on_clean(p)
    pacing.on_clean(p)
    assert p["gap"] == 2.3 * 1.5 * 1.5          # no easing yet: the count started over


def test_adaptive_pacing_is_start_to_start_and_counts_the_last_page():
    p = _pacer(gap_floor_s=0.2, gap_max_s=1.0)
    session: dict = {}

    async def go():
        await pacing.before(p, session)
        t0 = time.monotonic()
        session["last_request_at"] = t0 + 0.1   # the search paged; its last request left later
        await pacing.before(p, session)
        return time.monotonic() - t0

    waited = asyncio.run(go())
    assert waited >= 0.3 - 0.02                 # 0.1 (page) + 0.2 (gap), not 0.2
    assert session["gap_s"] == 0.2              # handed to the engine for its next page


def test_fixed_pacing_is_unchanged_for_other_marketplaces():
    prov = SimpleNamespace(gap_max_s=None, gap_floor_s=0.0, search_gap_s=0.05,
                           gap_backoff=1.5, gap_ease_after=20, gap_ease=1.25)
    p = pacing.new(prov)

    async def go():
        t0 = time.monotonic()
        await pacing.before(p, {})              # no wait before…
        mid = time.monotonic() - t0
        await pacing.after(p)                   # …the old gap after
        return mid, time.monotonic() - t0

    mid, total = asyncio.run(go())
    assert mid < 0.02 and total >= 0.05 - 0.01
    pacing.on_block(p)
    assert p["gap"] == 0.05                     # fixed mode never moves


# ── Zepto engine: no wasted store lookup, pages paced from the last request ──

def test_pool_sessions_skip_the_store_lookup():
    """The worker pools name the store on every search, so `get_page` at open was spent
    on an answer nobody read. The ad-hoc / bid-engine session still resolves."""
    lookups = []
    orig_capture, orig_resolve = zs._capture, zs._resolve_store

    async def _capture(page, url_part, nav, settle_ms=9000, why=None):
        return {"x": "1"}, None

    async def _resolve(session, lat, lon):
        lookups.append((lat, lon))
        return "store-1", ()

    class _Ctx:
        async def new_page(self):
            return SimpleNamespace()

        async def close(self):
            pass

    class _Browser:
        async def new_context(self, **kw):
            return _Ctx()

    zs._capture, zs._resolve_store = _capture, _resolve
    try:
        pooled = asyncio.run(zs.open_context_session(_Browser(), 12.9, 77.6))
        adhoc = asyncio.run(zs._make_session(_Browser(), 12.9, 77.6))
    finally:
        zs._capture, zs._resolve_store = orig_capture, orig_resolve
    assert pooled["store_id"] == "" and pooled["coord"] is None
    assert adhoc["store_id"] == "store-1"
    assert lookups == [(12.9, 77.6)]            # only the ad-hoc session looked it up


def test_engine_pace_waits_from_the_last_request():
    session = {"gap_s": 0.15}

    async def go():
        # Stamped inside the loop: asyncio.run's own start-up must not eat the gap.
        t0 = session["last_request_at"] = time.monotonic()
        await zs._pace(session)
        return time.monotonic() - t0

    assert asyncio.run(go()) >= 0.15 - 0.02
    assert asyncio.run(zs._pace({})) is None    # nothing sent yet: no wait


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} block + pacing tests passed.")
