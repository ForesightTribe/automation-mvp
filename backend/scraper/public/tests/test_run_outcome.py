"""How a public scrape reports what it covered (2026-09-30) — orchestrator.py,
targeted.py, outcome.py, staging.py.

Until now a run was stamped `success` the moment its worker pool returned, and a pool
returns when every worker has died just as readily as when the queue is empty:

    Zepto own-SKU   2026-09-26   169 stores, 0 done          -> success
    Blinkit keyword 2026-09-25   1,439 of 2,456 locations    -> success, loaded

These pin the replacement: status comes from coverage; every unanswered pair is either
retried or named; "nothing here" is recorded as an answer; a partial run resumes.

No browser, no database: the marketplace is a scripted fake, Playwright is a stub, and
staging goes to a temp directory.

Run:  python -m scraper.public.tests.test_run_outcome
"""
import asyncio
import contextlib
import dataclasses
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

from scraper.platforms.blinkit.public_data import parser as bl_parser
from scraper.public import orchestrator, outcome, providers, staging, targeted

TENANT = uuid.UUID("a870fd8d-7373-47ec-ad69-5dd08ce35542")


# ── fakes ────────────────────────────────────────────────────────────────────

def _loc(i: int):
    return SimpleNamespace(lat=12.0 + i, lon=77.0 + i, merchant_id=f"m{i}",
                           city="bengaluru", location_name=f"zone{i}", pincode="")


def _product(merchant_id: str, brand: str = "Dobra", pid: str = "1", position: int = 1):
    return {"product_id": pid, "name": f"{brand} Goli Soda", "brand": brand,
            "price": 20.0, "mrp": 25.0, "unit": "200 ml", "position": position,
            "in_stock": True, "inventory": 5, "merchant_id": merchant_id,
            "merchant_type": "express"}


def _ok(merchant_id: str, products=None):
    products = [_product(merchant_id)] if products is None else products
    return {"ok": True, "products": products, "merchant_id": merchant_id,
            "total_results": len(products), "error": ""}


FAIL = {"ok": False, "products": [], "merchant_id": "", "total_results": 0,
        "error": "HTTP 500"}
BLOCK = {"ok": False, "products": [], "merchant_id": "", "total_results": 0,
         "error": "HTTP 429", "blocked": True, "kind": "rate"}


def _provider(answer, *, opens=None, probe_every_s=0.0, max_block_waits=2, **extra):
    """A scripted marketplace. `answer(keyword, merchant_id, nth_call)` returns the
    search result; `opens` is an iterator of bools deciding whether each session
    open succeeds (default: always). `extra` overrides any Provider field — the
    defaults below are Provider's own (no block remedy, fixed pacing)."""
    calls: dict[tuple, int] = {}
    opened: list = []

    async def open_session(browser, lat, lon):
        if opens is not None and not next(opens, False):
            return None
        opened.append((lat, lon))
        return {"id": object()}

    async def search(session, keyword, cap, lat=None, lon=None, merchant_id=None,
                     follow_similarity=False, distinct_ad_slots=True):
        n = calls[(keyword, merchant_id)] = calls.get((keyword, merchant_id), 0) + 1
        return answer(keyword, merchant_id, n)

    async def close_session(session):
        pass

    async def launch_browser(pw):
        return SimpleNamespace(close=_anoop)

    return SimpleNamespace(
        slug="blinkit", name="Fake", result_cap=36, brand_cap=48,
        open_session=open_session, search=search, close_session=close_session,
        parse=bl_parser.parse, launch_browser=launch_browser,
        search_gap_s=0.0, store_gap_s=0.0, max_workers=None,
        pause_every=None, pause_s=0,
        probe_every_s=probe_every_s, max_block_waits=max_block_waits,
        **{**_PROVIDER_DEFAULTS, **extra},
        calls=calls, opened=opened,
    )


# Provider's own defaults for the fields the fake does not script, read off the real
# dataclass so a field added there can never silently go missing here.
_PROVIDER_DEFAULTS = {
    f.name: f.default for f in dataclasses.fields(providers.Provider)
    if f.name in ("block_remedy", "block_give_up_s", "gap_max_s", "gap_floor_s",
                  "gap_backoff", "gap_ease_after", "gap_ease")
}


async def _anoop(*a, **k):
    return None


class _PW:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@contextlib.contextmanager
def _patched(provider, *, locations, keywords=None, brands=None):
    """Point both orchestrators at the fake marketplace and a temp staging dir."""
    kw_map = {kw: [("dobra", ["dobra"])] for kw in (keywords or [])}
    saved = {
        (orchestrator, "get_provider"): orchestrator.get_provider,
        (orchestrator, "async_playwright"): orchestrator.async_playwright,
        (orchestrator, "_own_keyword_map"): orchestrator._own_keyword_map,
        (orchestrator, "_keyword_cap"): orchestrator._keyword_cap,
        (orchestrator, "_locations"): orchestrator._locations,
        (orchestrator, "_competitor_list"): orchestrator._competitor_list,
        (orchestrator, "_WORKER_STAGGER_S"): orchestrator._WORKER_STAGGER_S,
        (orchestrator, "_OPEN_SESSION_RETRY_S"): orchestrator._OPEN_SESSION_RETRY_S,
        (targeted, "get_provider"): targeted.get_provider,
        (targeted, "async_playwright"): targeted.async_playwright,
        (targeted, "_own_brands"): targeted._own_brands,
        (targeted, "_locations"): targeted._locations,
        (targeted, "_WORKER_STAGGER_S"): targeted._WORKER_STAGGER_S,
        (targeted, "_OPEN_SESSION_RETRY_S"): targeted._OPEN_SESSION_RETRY_S,
        (staging, "STAGING_DIR"): staging.STAGING_DIR,
    }

    async def _kw_map(db, tid):
        return dict(kw_map)

    async def _none(db, tid, mp):
        return None

    async def _locs(db, tid, mp):
        return list(locations)

    async def _no_competitors(db, tid):
        return []

    async def _brands(db, tid, default_cap, mp):
        return list(brands or [("dobra", ["dobra"], 48)])

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for mod in (orchestrator, targeted):
            mod.get_provider = lambda slug: provider
            mod.async_playwright = _PW
            mod._locations = _locs
            mod._WORKER_STAGGER_S = 0
            mod._OPEN_SESSION_RETRY_S = ()
        orchestrator._own_keyword_map = _kw_map
        orchestrator._keyword_cap = _none
        orchestrator._competitor_list = _no_competitors
        targeted._own_brands = _brands
        staging.STAGING_DIR = Path(tmp)
        try:
            yield Path(tmp)
        finally:
            for (mod, name), value in saved.items():
                setattr(mod, name, value)


def _db():
    return SimpleNamespace(close=_anoop)


def _keyword_run(workers=1, resume=False):
    return asyncio.run(orchestrator.run_tenant(
        _db(), TENANT, workers=workers, resume=resume, mp_slug="blinkit"))


def _sku_run(workers=1, resume=False):
    return asyncio.run(targeted.run_targeted(
        _db(), TENANT, workers=workers, resume=resume, mp_slug="blinkit"))


def _run_row(tmp: Path) -> dict:
    (path,) = list(tmp.glob("*.sqlite3"))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM run").fetchone())
    conn.close()
    return row


def _rows(tmp: Path, sql: str) -> list[dict]:
    (path,) = list(tmp.glob("*.sqlite3"))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute(sql)]
    conn.close()
    return out


# ── the status rule ──────────────────────────────────────────────────────────

def test_decide_clean_run_is_success():
    assert outcome.decide(expected=100, done=100, done_this_run=100,
                          unattempted_stores=0, min_coverage_pct=90) == outcome.SUCCESS


def test_decide_nothing_scraped_is_failed():
    assert outcome.decide(expected=100, done=0, done_this_run=0,
                          unattempted_stores=20, min_coverage_pct=90) == outcome.FAILED


def test_decide_unattempted_stores_is_partial_even_above_the_floor():
    # 95% is over the floor, but stores were left on the queue: the workers died.
    assert outcome.decide(expected=100, done=95, done_this_run=95,
                          unattempted_stores=1, min_coverage_pct=90) == outcome.PARTIAL


def test_decide_under_the_floor_is_partial():
    assert outcome.decide(expected=100, done=89, done_this_run=89,
                          unattempted_stores=0, min_coverage_pct=90) == outcome.PARTIAL


def test_decide_a_few_lost_pairs_above_the_floor_is_success():
    assert outcome.decide(expected=100, done=97, done_this_run=97,
                          unattempted_stores=0, min_coverage_pct=90) == outcome.SUCCESS


def test_decide_resume_with_nothing_left_is_success():
    assert outcome.decide(expected=100, done=100, done_this_run=0,
                          unattempted_stores=0, min_coverage_pct=90) == outcome.SUCCESS


def test_exit_code_worst_status_wins():
    assert outcome.exit_code(["success", "skipped"]) == 0
    assert outcome.exit_code(["success", "partial"]) == outcome.PARTIAL_EXIT_CODE
    assert outcome.exit_code(["partial", "failed"]) == 1


# ── keyword scrape ───────────────────────────────────────────────────────────

def test_keyword_clean_run():
    p = _provider(lambda kw, mid, n: _ok(mid))
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda", "candy"]) as tmp:
        s = _keyword_run(workers=2)
        row = _run_row(tmp)
    assert s["status"] == "success" and s["coverage_pct"] == 100.0
    assert s["snapshots"] == 6 and s["unattempted"] == 0 and s["unrecovered"] == 0
    assert row["status"] == "success" and row["error"] is None
    assert (row["pairs_done"], row["pairs_total"]) == (6, 6)


def test_keyword_no_session_opens_is_failed_not_success():
    """The 2026-09-26 shape: every worker fails to open, the pool returns at once."""
    p = _provider(lambda kw, mid, n: _ok(mid), opens=iter([]))
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]) as tmp:
        s = _keyword_run(workers=2)
        row = _run_row(tmp)
    assert s["status"] == "failed"
    assert s["unattempted"] == 3 and s["snapshots"] == 0
    assert row["status"] == "failed" and "never attempted" in row["error"]


def test_keyword_worker_dying_midway_is_partial_and_resumes():
    """The 2026-09-25 shape: the worker loses its session part-way and exits with
    stores still queued. Then --resume finishes the same file."""
    def answer(kw, mid, n):
        return BLOCK if mid == "m2" else _ok(mid)

    # First open works; every re-open after the block fails -> the worker exits.
    p = _provider(answer, opens=iter([True]), probe_every_s=0.001, max_block_waits=2)
    locs = [_loc(i) for i in range(6)]
    with _patched(p, locations=locs, keywords=["soda", "candy"]) as tmp:
        s = _keyword_run(workers=1)
        row = _run_row(tmp)
        assert s["status"] == "partial"
        assert s["unattempted"] == 3               # m3, m4, m5 never left the queue
        assert s["pairs_done"] == 4 and s["pairs_total"] == 12
        assert row["status"] == "partial" and row["loaded_at"] is None

        # Resume: the marketplace has recovered. Same file, only the missing pairs.
        p2 = _provider(lambda kw, mid, n: _ok(mid))
        orchestrator.get_provider = lambda slug: p2
        s2 = _keyword_run(workers=1, resume=True)
        row2 = _run_row(tmp)
    assert s2["status"] == "success" and s2["pairs_done"] == 12
    assert s2["skipped"] == 4                      # the four pairs already staged
    assert sorted(p2.calls) == sorted(
        (kw, f"m{i}") for i in range(2, 6) for kw in ("soda", "candy"))
    assert row2["status"] == "success" and row2["error"] is None


def test_keyword_plain_failures_reach_the_backlog():
    """A plain (non-block) failure used to be counted and dropped — only a
    blocked-twice keyword was ever retried."""
    p = _provider(lambda kw, mid, n: FAIL if (mid == "m1" and n == 1) else _ok(mid))
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda", "candy"]):
        s = _keyword_run(workers=1)
    assert s["status"] == "success"
    assert s["errors"] == 2 and s["recovered"] == 2 and s["unrecovered"] == 0
    assert s["snapshots"] == 6


def test_keyword_store_skip_does_not_lose_the_rest_of_the_store():
    """Two failures skip the store's remaining keywords. They used to vanish; now the
    backlog pass gets them."""
    seen_in_backlog = []

    def answer(kw, mid, n):
        if mid == "m0" and n == 1 and kw in ("a", "b"):
            return FAIL
        if mid == "m0":
            seen_in_backlog.append(kw)
        return _ok(mid)

    p = _provider(answer)
    with _patched(p, locations=[_loc(0), _loc(1)], keywords=["a", "b", "c"]):
        s = _keyword_run(workers=1)
    assert sorted(seen_in_backlog) == ["a", "b", "c"]      # `c` was never tried before
    assert s["status"] == "success" and s["recovered"] == 3 and s["unrecovered"] == 0


def test_keyword_persistent_failure_is_counted_and_named():
    p = _provider(lambda kw, mid, n: FAIL if mid == "m0" else _ok(mid))
    # 1 bad store of 20 -> 95% coverage: over the floor, so success WITH a count.
    with _patched(p, locations=[_loc(i) for i in range(20)], keywords=["a", "b"]) as tmp:
        s = _keyword_run(workers=2)
        row = _run_row(tmp)
    assert s["status"] == "success" and s["coverage_pct"] == 95.0
    assert s["unrecovered"] == 2 and row["unrecovered"] == 2
    assert "got no answer" in s["note"]


def test_keyword_low_coverage_is_partial():
    p = _provider(lambda kw, mid, n: FAIL if mid in ("m0", "m1") else _ok(mid))
    with _patched(p, locations=[_loc(i) for i in range(5)], keywords=["a"]) as tmp:
        s = _keyword_run(workers=1)
        row = _run_row(tmp)
    assert s["coverage_pct"] == 60.0 and s["status"] == "partial"
    assert s["unattempted"] == 0                   # every store WAS reached
    assert row["status"] == "partial"


def test_keyword_empty_result_is_recorded_as_an_answer():
    p = _provider(lambda kw, mid, n: _ok(mid, products=[]) if kw == "rare" else _ok(mid))
    with _patched(p, locations=[_loc(0), _loc(1)], keywords=["soda", "rare"]) as tmp:
        s = _keyword_run(workers=1)
        snaps = _rows(tmp, "SELECT keyword, total_results, brand_rank, brand_sov "
                           "FROM search_snapshots WHERE keyword='rare'")
        listings = _rows(tmp, "SELECT 1 FROM search_listings WHERE keyword='rare'")
    assert s["status"] == "success" and s["pairs_done"] == 4 and s["snapshots"] == 4
    assert len(snaps) == 2 and listings == []
    # NULL, not 0 — an empty page has no share to take, and the read side's avg()
    # must not be dragged down by it.
    assert all(r["total_results"] == 0 and r["brand_sov"] is None
               and r["brand_rank"] is None for r in snaps)


def test_keyword_block_waited_out_is_not_an_error():
    p = _provider(lambda kw, mid, n: BLOCK if (mid == "m1" and n == 1) else _ok(mid),
                  probe_every_s=0.001)
    with _patched(p, locations=[_loc(i) for i in range(3)], keywords=["soda"]):
        s = _keyword_run(workers=1)
    assert s["status"] == "success"
    assert s["blocked"] == 1 and s["errors"] == 0 and s["unrecovered"] == 0


def test_keyword_nothing_to_scrape_is_skipped_not_failed():
    p = _provider(lambda kw, mid, n: _ok(mid))
    with _patched(p, locations=[], keywords=["soda"]):
        s = _keyword_run()
    assert s["status"] == "skipped"
    assert outcome.exit_code([s["status"]]) == 0


# ── own-SKU scrape ───────────────────────────────────────────────────────────

def test_sku_store_without_the_brand_is_an_answer():
    """A store that does not list the brand writes no sku rows — it must still count
    as scraped, and --resume must not redo it."""
    def answer(q, mid, n):
        return _ok(mid, products=[_product(mid, brand="Other")]) if mid == "m1" else _ok(mid)

    p = _provider(answer)
    with _patched(p, locations=[_loc(i) for i in range(3)]) as tmp:
        s = _sku_run(workers=1)
        markers = _rows(tmp, "SELECT lat, n_rows FROM pairs_done ORDER BY lat")
        (path,) = list(tmp.glob("*.sqlite3"))
        stg = staging.open_run(path)
        done = staging.done_sku_pairs(stg)
        staging.close(stg)
    assert s["status"] == "success" and s["rows"] == 2 and s["pairs_done"] == 3
    assert [m["n_rows"] for m in markers] == [1, 0, 1]
    assert ("dobra", 13.0, 78.0) in done


def test_sku_no_session_opens_is_failed_not_success():
    p = _provider(lambda q, mid, n: _ok(mid), opens=iter([]))
    with _patched(p, locations=[_loc(i) for i in range(4)]) as tmp:
        s = _sku_run(workers=3)
        row = _run_row(tmp)
    assert s["status"] == "failed" and s["unattempted"] == 4 and s["rows"] == 0
    assert row["status"] == "failed" and row["stores_done"] == 0


def test_sku_second_brand_failure_is_retried_then_resumed_by_pair():
    """Two brands at a store: one stages, one fails. Resume used to key on "stores
    that have rows", so the store was skipped and the second brand never came back."""
    brands = [("dobra", ["dobra"], 48), ("pop", ["pop"], 48)]

    def answer(q, mid, n):
        if q == "pop" and mid == "m0":
            return FAIL
        return _ok(mid, products=[_product(mid, brand=q.title())])

    p = _provider(answer)
    with _patched(p, locations=[_loc(0), _loc(1)], brands=brands) as tmp:
        s = _sku_run(workers=1)
        assert s["unrecovered"] == 1 and s["pairs_done"] == 3
        assert s["status"] == "partial"            # 75% < the 90% floor

        p2 = _provider(lambda q, mid, n: _ok(mid, products=[_product(mid, brand=q.title())]))
        targeted.get_provider = lambda slug: p2
        s2 = _sku_run(workers=1, resume=True)
        row2 = _run_row(tmp)
    assert list(p2.calls) == [("pop", "m0")]       # only the missing pair
    assert s2["status"] == "success" and s2["pairs_done"] == 4
    assert row2["status"] == "success"


def test_sku_wrong_store_answer_is_dropped_not_filed():
    def answer(q, mid, n):
        return _ok("someone-else") if mid == "m1" else _ok(mid)

    p = _provider(answer)
    with _patched(p, locations=[_loc(i) for i in range(3)]) as tmp:
        s = _sku_run(workers=1)
        stores = _rows(tmp, "SELECT DISTINCT merchant_id FROM sku_snapshots")
    assert s["mismatched"] == 1 and s["rows"] == 2
    assert sorted(r["merchant_id"] for r in stores) == ["m0", "m2"]


# ── the command's exit code (all the runner ever sees) ──────────────────────

def _cli(args: list[str]):
    from typer.testing import CliRunner
    from cli.commands import scrape
    return CliRunner().invoke(scrape.app, args)


def test_cli_exits_zero_on_a_clean_run():
    p = _provider(lambda kw, mid, n: _ok(mid))
    with _patched(p, locations=[_loc(0), _loc(1)], keywords=["soda"]):
        r = _cli(["public-run", "-t", str(TENANT), "-m", "blinkit", "--no-load"])
    assert r.exit_code == 0, r.output


def test_cli_exits_nonzero_when_nothing_was_scraped():
    """Was exit 0 — so the jobs table showed a 0-store run as green."""
    p = _provider(lambda kw, mid, n: _ok(mid), opens=iter([]))
    with _patched(p, locations=[_loc(0), _loc(1)], keywords=["soda"]):
        r = _cli(["public-run", "-t", str(TENANT), "-m", "blinkit"])
        sku = _cli(["public-skus", "-t", str(TENANT), "-m", "blinkit"])
    assert r.exit_code == 1, r.output
    assert sku.exit_code == 1, sku.output
    assert "Not auto-loading" in r.output and "--resume" in r.output


def test_cli_exits_with_the_partial_code_on_a_partial_run():
    p = _provider(lambda kw, mid, n: BLOCK if mid == "m2" else _ok(mid),
                  opens=iter([True]), probe_every_s=0.001)
    with _patched(p, locations=[_loc(i) for i in range(6)], keywords=["soda"]):
        r = _cli(["public-run", "-t", str(TENANT), "-m", "blinkit"])
    assert r.exit_code == outcome.PARTIAL_EXIT_CODE, r.output
    assert "partial" in r.output


def test_runner_names_a_partial_run():
    from jobs import runner
    assert runner._classify_failure(outcome.PARTIAL_EXIT_CODE, False, False) == "partial"
    assert "gaps" in runner._plain_reason("partial", outcome.PARTIAL_EXIT_CODE)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} run-outcome tests passed.")
