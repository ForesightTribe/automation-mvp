"""C6 — Zepto measures at ONE store a tick and rotates only when it can't sell (2026-09-28).

Pure rotation rules, Zepto's brand-search stock summary, the "ad missing → check stock once"
step, and a stubbed multi-tick run through the real `bid.run` — no Zepto, no DB.

    python -m campaign_manager.tests.test_rotation
"""
import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

from app.utils.time import now_ist
from campaign_manager import bid, config, coverage, repo, rotation, stock
from campaign_manager.marketplaces.zepto import catalog as zcat

T0 = now_ist().replace(year=2026, month=9, day=28, hour=9, minute=45, second=0, microsecond=0)
WINDOW = T0.replace(hour=9, minute=0)


def _store(mid, rank):
    return repo.MeasurementStore(lat=12.9 + rank / 100, lon=77.5, label=f"Store{rank}",
                                 merchant_id=mid, city_id=7, source="tenant", rank=rank)


S = [_store("m1", 1), _store("m2", 2), _store("m3", 3)]


def _h(mid, minutes, verdict=coverage.SPONSORED, elig=coverage.UNKNOWN):
    """One stored reading, `minutes` after T0."""
    return SimpleNamespace(merchant_id=mid, verdict=verdict, eligibility=elig,
                           observed_at=T0 + timedelta(minutes=minutes), store_label=mid)


def _out(mid, minutes):
    return _h(mid, minutes, coverage.SKIPPED, coverage.NOT_LISTED)


def _plan(history, at=0, stores=S):
    return rotation.plan(stores, history, window_start=WINDOW,
                         now=T0 + timedelta(minutes=at), rest_minutes=60)


# ── where to measure ─────────────────────────────────────────────────────────

def test_a_new_window_starts_at_store_1():
    p = _plan([])
    assert p.store is S[0] and p.rank == 1 and not p.switched and not p.resting


def test_yesterdays_readings_do_not_count():
    p = _plan([_out("m1", -120)])                    # before today's window opened
    assert p.store is S[0]


def test_our_ad_showing_keeps_the_store():
    p = _plan([_h("m2", 0), _out("m1", -15)], at=15)
    assert p.store is S[1] and not p.switched, "any store that sells is a valid place to measure"


def test_a_store_that_cannot_sell_hands_the_next_tick_to_the_next_store():
    p = _plan([_out("m1", 0), _h("m1", -15)], at=15)
    assert p.store is S[1] and p.rank == 2 and not p.resting


def test_moving_store_resets_the_learning():
    p = _plan([_out("m1", 0), _h("m1", -15)], at=15)
    assert p.switched, "store 1's position and raise step say nothing about store 2's auction"


def test_nothing_learned_yet_means_nothing_to_reset():
    p = _plan([_out("m1", 0)], at=15)
    assert p.store is S[1] and not p.switched


def test_the_rotation_wraps_back_to_store_1():
    p = _plan([_out("m3", 0), _h("m2", -15), _out("m1", -30)], at=15)
    assert p.store is S[0], "store 2 sold in between, so this is not a full cycle — keep rotating"
    assert not p.resting


def test_a_failed_read_does_not_move_the_rotation():
    p = _plan([_h("m2", 0, coverage.ERROR)], at=15)
    assert p.store is S[1], "a read that failed proves nothing about stock"


def test_a_store_that_left_the_set_restarts_at_store_1():
    p = _plan([_h("m9", 0)], at=15)
    assert p.store is S[0]


# ── out-of-stock rest ────────────────────────────────────────────────────────

def _cycle():
    return [_out("m3", 30), _out("m2", 15), _out("m1", 0)]


def test_a_full_cycle_of_stock_outs_rests_and_searches_nothing():
    p = _plan(_cycle(), at=45)
    assert p.store is None and p.resting
    assert p.rest_since == T0, "resting since the first stock-out of the cycle"
    assert p.next_check_at == T0 + timedelta(minutes=90), "an hour after the last check"
    assert p.upcoming is S[0], "the rest keeps rotating"


def test_the_rest_check_comes_due_after_the_rest_delay():
    p = _plan(_cycle(), at=90)
    assert p.store is S[0] and p.resting


def test_the_rest_ends_the_moment_a_store_can_sell():
    p = _plan([_h("m1", 90)] + _cycle(), at=105)
    assert p.store is S[0] and not p.resting


def test_still_out_at_the_rest_check_keeps_resting():
    p = _plan([_out("m1", 90)] + _cycle(), at=105)
    assert p.store is None and p.resting and p.upcoming is S[1]
    assert p.rest_since == T0


def test_a_single_store_rests_after_one_stock_out():
    p = _plan([_out("m1", 0)], at=15, stores=S[:1])
    assert p.store is None and p.resting


# ── Zepto's brand-search stock ───────────────────────────────────────────────

def _p(vid, brand="Brik Oven", in_stock=True):
    return {"variant_id": vid, "brand": brand, "name": f"{brand} {vid}", "in_stock": in_stock}


def _sum(products, cap=60, **res):
    return zcat.summarise({"ok": True, "products": products, "merchant_id": "m1", **res}, cap,
                          zcat.own_names({"brik oven"}))


def test_our_products_come_back_keyed_by_variant_id():
    got = _sum([_p("v1"), _p("x", "Other"), _p("v2")])
    assert got["ok"] and got["complete"] and got["served_by"] == "m1"
    assert [p["pid"] for p in got["products"]] == ["v1", "v2"]


def test_none_of_ours_is_an_answer_not_an_error():
    """Zepto hides sold-out products, so a store with nothing of ours returns other brands."""
    got = _sum([_p("x", "Other"), _p("y", "Other")])
    assert got["ok"] and got["complete"] and got["products"] == []
    known = coverage.StoreStock(complete=True, in_stock={})
    assert coverage.eligibility({"v1"}, known) == coverage.NOT_LISTED


def test_an_empty_search_says_nothing():
    assert _sum([])["ok"] is False


def test_a_capped_read_still_full_of_ours_is_not_complete():
    got = _sum([_p(f"v{i}") for i in range(5)], cap=5)
    assert got["ok"] and not got["complete"]


def test_a_flagged_sold_out_product_is_honoured():
    got = _sum([_p("v1", in_stock=False)])
    assert got["products"][0]["in_stock"] is False


def test_a_brandless_product_is_ours_by_name():
    got = _sum([{"variant_id": "v1", "brand": "", "name": "Brik Oven Sourdough"}])
    assert [p["pid"] for p in got["products"]] == ["v1"]


def test_the_zepto_adapter_binds_the_brand_search_to_the_store():
    import inspect
    from campaign_manager.marketplaces.zepto import adapter
    assert "merchant_id" in inspect.signature(adapter.read_store_catalog).parameters
    assert "merchant_id=merchant_id" in inspect.getsource(zcat.read)


# ── "our ad is missing" → one stock check ────────────────────────────────────

class _StockOnly:
    def __init__(self, stocked: bool | None):
        self.stocked, self.calls = stocked, []

    async def read_store_catalog(self, session, query, lat, lon, *, cap, names,
                                 merchant_id=None):
        self.calls.append(merchant_id)
        if self.stocked is None:
            return {"ok": False, "error": "HTTP 299 LOGIN_REQUIRED"}
        return {"ok": True, "complete": True, "served_by": merchant_id,
                "products": [{"pid": "v1", "in_stock": True}] if self.stocked else []}


def _with_stock_repo(fn):
    saved = (repo.get_store_stock, repo.get_own_brands, repo.upsert_store_stock)

    async def _none(*a, **k):
        return {}

    async def _brands(*a, **k):
        return [("brik oven", 60, {"brik oven"})]

    async def _noop(*a, **k):
        return None

    repo.get_store_stock, repo.get_own_brands, repo.upsert_store_stock = _none, _brands, _noop
    try:
        return fn()
    finally:
        repo.get_store_stock, repo.get_own_brands, repo.upsert_store_stock = saved


def _check(reading, stocked):
    adapter = _StockOnly(stocked)
    out, n = _with_stock_repo(lambda: asyncio.run(bid._rotation_stock(
        adapter, {}, uuid.uuid4(), "zepto", [reading], campaign_pids={"v1"},
        stock_by_store={}, now=T0, run_id="t", dry_run=True)))
    return out[0], n, adapter.calls


def _absent():
    return coverage.Reading(S[0], coverage.UNKNOWN, coverage.ABSENT, 21.0, 20, "not ours")


def test_missing_ad_and_in_stock_means_outbid_so_it_counts():
    r, n, calls = _check(_absent(), stocked=True)
    assert r.verdict == coverage.ABSENT and r.eligibility == coverage.ELIGIBLE
    assert n == 1 and calls == ["m1"], "one brand search, bound to the store"


def test_missing_ad_and_not_sold_there_holds_and_moves_on():
    r, _, _ = _check(_absent(), stocked=False)
    assert r.verdict == coverage.SKIPPED and r.eligibility == coverage.NOT_LISTED
    assert rotation.cant_sell(r)


def test_missing_ad_and_stock_unreadable_holds_rather_than_raising_blind():
    r, _, _ = _check(_absent(), stocked=None)
    assert r.verdict == coverage.UNTRUSTED
    assert coverage.aggregate([r]).kind == "error", "no raise on an unreadable stock check"


def test_our_ad_showing_needs_no_stock_check():
    shown = coverage.Reading(S[0], coverage.UNKNOWN, coverage.SPONSORED, 3.0, 20, "ours")
    r, n, calls = _check(shown, stocked=True)
    assert r is shown and n == 0 and calls == []


# ── the whole engine, tick by tick ───────────────────────────────────────────

class _World:
    """Three stores. Per store: is our ad showing (its position, or None), and is the product
    in stock. Records every search the engine makes."""

    def __init__(self):
        self.ad = {"m1": None, "m2": None, "m3": None}
        self.stocked = {"m1": False, "m2": False, "m3": False}
        self.searches: list[tuple[str, str]] = []

    def by_lat(self, lat):
        return next(s.merchant_id for s in S if abs(s.lat - lat) < 1e-9)


class _FakeZepto:
    RAISE_WHEN_ABSENT = True
    RECOGNISES_AD_BY_CAMPAIGN = True
    REQUIRES_RULE_LOCATION = True

    def __init__(self, world):
        self.w = world

    async def setup(self, tenant):
        return None, None, "client"

    async def open_position_session(self, pw, lat, lon):
        return {"open": True}

    async def close_position_session(self, session):
        pass

    async def read_campaign(self, client, cid):
        return "running", 1000, {}

    def bids_from_detail(self, detail):
        return {"sourdough": 20}

    async def read_products(self, client, cid):
        return [{"pid": "v1", "name": "Sourdough"}]

    async def read_bid_floors(self, client, cid, detail):
        return {}

    async def fetch_positions(self, session, kw, lat, lon, *, merchant_id=None):
        self.w.searches.append(("keyword", merchant_id))
        return [{"row": i} for i in range(20)]

    def locate_position(self, results, kw, lat, lon, **kw_):
        pos = self.w.ad[self.w.by_lat(lat)]
        return (float(pos), "live") if pos else (None, "our product is not in these results")

    async def read_store_catalog(self, session, query, lat, lon, *, cap, names,
                                 merchant_id=None):
        self.w.searches.append(("stock", merchant_id))
        return {"ok": True, "complete": True, "served_by": merchant_id,
                "products": [{"pid": "v1", "in_stock": True}] if self.w.stocked[merchant_id]
                else []}


def _engine(world):
    """Stub every repo call `bid.run` makes; state carries between ticks like the DB would."""
    rule = SimpleNamespace(
        id="r1", campaign_id=11, keyword="sourdough", campaign_name="Brik", type="once",
        date="2026-09-28", days=None, start_date=None, stop_date=None, start_time="09:00",
        stop_time="21:00", min_bid=10, max_bid=60, target_position=3, match_type="EXACT",
        lat=None, lon=None, location_name="", city_id=7, brand_name="Brik Oven", state="active")
    rt = SimpleNamespace(last_cpm=20, updated_at=T0 - timedelta(minutes=14), last_position=None,
                         last_bid_updated_at=None, last_holding_cpm=None, drift_paused_until=None,
                         raise_step=None, effective_target=None, effective_at_max_bid=None)
    st = {"reads": [], "log": [], "cache": {}, "runtime": rt}

    async def get_bid_rules(*a, **k):
        return [(rule, rt)]

    async def city_stores_for(*a, **k):
        return {7: list(S)}

    async def empty(*a, **k):
        return {}

    async def recent_store_reads(*a, **k):
        out: dict = {}
        for r in sorted(st["reads"], key=lambda r: r["observed_at"], reverse=True):
            out.setdefault((r["rule_id"], r["merchant_id"]), []).append(SimpleNamespace(**r))
        return out

    async def get_store_stock(tenant, platform, ids):
        return {m: v for m, v in st["cache"].items() if m in ids}

    async def upsert_store_stock(tenant, platform, rows):
        for r in rows:
            st["cache"][r["merchant_id"]] = coverage.StoreStock(
                complete=r["complete"], checked_at=r["checked_at"],
                in_stock={p["pid"]: p["in_stock"] for p in r["products"]})

    async def get_own_brands(*a, **k):
        return [("brik oven", 60, {"brik oven"})]

    async def write_bid_runtime(rows):
        for r in rows:
            for k, v in r.items():
                if k != "rule_id":
                    setattr(rt, k, v)
            rt.updated_at = bid.now_ist()

    async def write_run_log(rows):
        st["log"].extend(rows)

    async def write_store_reads(rows):
        st["reads"].extend(rows)

    async def nothing(*a, **k):
        return None

    async def zero(*a, **k):
        return 0

    async def the_rule(rule_id):
        return rule

    async def name(*a, **k):
        return "Brik Oven"

    return st, {
        "get_bid_rules": get_bid_rules, "city_stores_for": city_stores_for,
        "store_ids_at": empty, "recent_store_reads": recent_store_reads,
        "get_store_stock": get_store_stock, "upsert_store_stock": upsert_store_stock,
        "get_own_brands": get_own_brands, "write_bid_runtime": write_bid_runtime,
        "write_run_log": write_run_log, "write_store_reads": write_store_reads,
        "record_applied": nothing, "recent_write_count": zero, "get_bid_rule": the_rule,
        "get_tenant_name": name,
    }


def _tick(world, stubs, at_minutes):
    saved_repo = {k: getattr(repo, k) for k in stubs}
    saved = (bid.get_adapter, bid.now_ist)
    for k, v in stubs.items():
        setattr(repo, k, v)
    bid.get_adapter = lambda platform: _FakeZepto(world)
    bid.now_ist = lambda: T0 + timedelta(minutes=at_minutes)
    world.searches.clear()
    try:
        asyncio.run(bid.run(uuid.uuid4(), dry_run=True, platform="zepto"))
    finally:
        for k, v in saved_repo.items():
            setattr(repo, k, v)
        bid.get_adapter, bid.now_ist = saved
    return list(world.searches)


def test_a_day_of_stock_outs_through_the_real_engine():
    w = _World()
    st, stubs = _engine(w)
    last = lambda: st["log"][-1]                          # noqa: E731

    # 09:45 — our ad at store 1, position 8 against target 3 → a normal raise, no stock check.
    w.ad["m1"] = 8
    assert _tick(w, stubs, 0) == [("keyword", "m1")]
    assert last()["action"] == "apply" and "raising" in last()["reason"]
    assert st["runtime"].raise_step is not None
    st["runtime"].raise_step = 40                         # an escalated step, learned at store 1

    # 10:00 — gone from store 1, which has none in stock → hold, next tick at store 2.
    w.ad["m1"] = None
    assert _tick(w, stubs, 15) == [("keyword", "m1"), ("stock", "m1")]
    assert last()["action"] == "skip" and last()["new_value"] == last()["old_value"]
    assert "Store2 (store 2 of 3)" in last()["reason"], last()["reason"]

    # 10:15 — store 2 shows us at 6: a raise from a FRESH step (a different auction).
    w.ad["m2"] = 6
    assert _tick(w, stubs, 30) == [("keyword", "m2")]
    base = max(config.bid_tuning("zepto", "BID_RAISE_MIN_STEP"),
               int(20 * config.bid_tuning("zepto", "BID_RAISE_PCT") / 100))
    assert st["runtime"].raise_step == base, "store 1's escalated step must not carry over"

    # 10:30 / 10:45 — store 2 then store 3 run out: one hop a tick.
    w.ad["m2"] = None
    assert _tick(w, stubs, 45) == [("keyword", "m2"), ("stock", "m2")]
    assert _tick(w, stubs, 60) == [("keyword", "m3"), ("stock", "m3")]
    assert "Store1 (store 1 of 3)" in last()["reason"]

    # 11:00 — store 1 again. Its 10:00 stock read is exactly an hour old, so it is re-read;
    # still out → the cycle is complete → out-of-stock rest.
    assert _tick(w, stubs, 75) == [("keyword", "m1"), ("stock", "m1")]
    assert "nor can the other 2 stores we check" in last()["reason"], last()["reason"]

    # 11:15 — resting: no search at all, and History says why.
    assert _tick(w, stubs, 90) == []
    assert last()["action"] == "hold" and "next check around 12:00" in last()["reason"]

    # 12:00 — the hourly check, at the next store in rotation; store 2 has restocked but
    # our ad is still missing → genuinely outbid → the raise resumes.
    w.stocked["m2"] = True
    assert _tick(w, stubs, 135) == [("keyword", "m2"), ("stock", "m2")]
    assert last()["action"] == "apply", last()
    assert last()["reason"].startswith("back in stock at Store2"), last()["reason"]


def test_a_shopper_search_that_cannot_open_holds_every_bid_and_says_so():
    w = _World()
    st, stubs = _engine(w)

    class _Blocked(_FakeZepto):
        async def open_position_session(self, pw, lat, lon):
            raise RuntimeError("Zepto: could not open a consumer search session")

    saved_repo = {k: getattr(repo, k) for k in stubs}
    saved = (bid.get_adapter, bid.now_ist)
    for k, v in stubs.items():
        setattr(repo, k, v)
    bid.get_adapter = lambda platform: _Blocked(w)
    bid.now_ist = lambda: T0
    try:
        res = asyncio.run(bid.run(uuid.uuid4(), dry_run=True, platform="zepto"))
    finally:
        for k, v in saved_repo.items():
            setattr(repo, k, v)
        bid.get_adapter, bid.now_ist = saved
    assert res["errors"] == 1 and res["applied"] == 0
    assert [r["action"] for r in st["log"]] == ["error"]
    assert "shopper search could not be opened" in st["log"][0]["reason"]


def test_blinkit_keeps_reading_every_store():
    assert config.store_strategy("blinkit") == config.EVERY_STORE
    assert config.store_strategy("zepto") == config.ROTATE
    assert config.max_stores("zepto") == 3, "the set is the fallback order, three deep"


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} rotation tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
