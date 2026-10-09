"""Measurement stores: which dark stores a bid rule reads its position at — no DB, no
marketplace.

A rule names a city; the stores inside it are a setting (`cm_city_stores`): a ranked set — rank
1 the anchor, 2-3 validating it — with a global set a client can replace whole, resolved on every
run so that changing it moves every automation measuring in that city. These pin the precedence,
the fall-throughs when a frozen store is unusable, how a tick reads its stores (stock-outs are
never searched; unknown stock still counts), and that the engine never reads a rule's saved
coordinates except through `measurement_stores`.

    python -m campaign_manager.tests.test_measurement_store
"""
import asyncio
import inspect
import uuid
from types import SimpleNamespace

from campaign_manager import ad_slots, bid, coverage, repo
from campaign_manager.marketplaces.blinkit.live_position import PageResults

DOBRA, OTHER = uuid.uuid4(), uuid.uuid4()
BENGALURU = 499


def _cs(tenant_id=None, merchant_id="30248", rank=1):
    return SimpleNamespace(tenant_id=tenant_id, merchant_id=merchant_id, rank=rank,
                           city_id=BENGALURU)


def _loc(merchant_id="30248", name="Manjunath Garden", active=True, lat=12.90, lon=77.57):
    return SimpleNamespace(merchant_id=merchant_id, location_name=name, city="bengaluru",
                           is_active=active, lat=lat, lon=lon, city_id=BENGALURU)


def _row(tenant_id=None, merchant_id="30248", rank=1, **loc):
    return _cs(tenant_id, merchant_id, rank), _loc(merchant_id, **loc)


def _picked(rows, tenant_id):
    got = repo.pick_city_store(rows, tenant_id)
    return None if got is None else (got[1].merchant_id, got[2])


def _set(rows, tenant_id, limit=3):
    stores, source = repo.pick_city_stores(rows, tenant_id, limit)
    return [cs.merchant_id for cs, _ in stores], source


def _rule(**kw):
    return SimpleNamespace(**{"id": "r1", "city_id": None, "lat": None, "lon": None,
                              "location_name": None, **kw})


def _store(source="global", merchant_id="31001", rank=1, lat=12.93, lon=77.62,
           label="Koramangala"):
    return repo.MeasurementStore(lat=lat, lon=lon, label=label, merchant_id=merchant_id,
                                 city_id=BENGALURU, source=source, rank=rank)


# ── Precedence (the anchor) ──────────────────────────────────────────────────

def test_client_set_beats_the_global_set():
    assert _picked([_row(None, "1"), _row(DOBRA, "2")], DOBRA) == ("2", "tenant")


def test_a_client_without_its_own_set_gets_the_global_set():
    assert _picked([_row(None, "1")], DOBRA) == ("1", "global")


def test_another_clients_set_is_ignored():
    assert _picked([_row(None, "1"), _row(OTHER, "2")], DOBRA) == ("1", "global")


def test_no_client_sees_only_the_global_set():
    assert _picked([_row(DOBRA, "2"), _row(None, "1")], None) == ("1", "global")


def test_nothing_frozen_is_none():
    assert _picked([], DOBRA) is None
    assert _picked([_row(OTHER, "2")], DOBRA) is None


# ── Sets ─────────────────────────────────────────────────────────────────────

def test_a_set_comes_back_in_rank_order():
    rows = [_row(None, "c", rank=3), _row(None, "a", rank=1), _row(None, "b", rank=2)]
    assert _set(rows, DOBRA) == (["a", "b", "c"], "global")


def test_a_client_set_replaces_the_global_set_whole():
    # Never mixed rank by rank: a client's single store is its whole set.
    rows = [_row(None, "g1", rank=1), _row(None, "g2", rank=2), _row(None, "g3", rank=3),
            _row(DOBRA, "c1", rank=1)]
    assert _set(rows, DOBRA) == (["c1"], "tenant")


def test_a_store_listed_twice_keeps_its_lower_rank():
    rows = [_row(None, "a", rank=1), _row(None, "a", rank=3), _row(None, "b", rank=2)]
    assert _set(rows, DOBRA) == (["a", "b"], "global")


def test_ranks_beyond_the_marketplace_limit_are_ignored():
    rows = [_row(None, "a", rank=1), _row(None, "b", rank=2), _row(None, "c", rank=3)]
    assert _set(rows, DOBRA, limit=1) == (["a"], "global")


def test_an_unusable_anchor_hands_the_anchor_to_the_next_rank():
    rows = [_row(None, "a", rank=1, active=False), _row(None, "b", rank=2)]
    assert _set(rows, DOBRA) == (["b"], "global")
    assert _picked(rows, DOBRA) == ("b", "global")


# ── An unusable frozen store falls through, never measures nowhere ────────────

def test_an_inactive_client_set_falls_back_to_global():
    assert _picked([_row(None, "1"), _row(DOBRA, "2", active=False)], DOBRA) == ("1", "global")


def test_a_store_gone_from_the_catalog_falls_back_to_global():
    assert _picked([_row(None, "1"), (_cs(DOBRA, "gone"), None)], DOBRA) == ("1", "global")


def test_a_store_without_coordinates_is_not_usable():
    assert _picked([_row(DOBRA, "2", lat=None)], DOBRA) is None


# ── Labels ───────────────────────────────────────────────────────────────────

def test_catalog_labels_are_trimmed():
    # Real catalog data: "Financial District\r\n" was showing up verbatim in run logs.
    assert repo._store_of(_loc("42318", name="Financial District\r\n"), "catalog").label == \
        "Financial District"


def test_a_nameless_store_is_labelled_by_city_and_id():
    assert repo._store_of(_loc("42318", name=""), "catalog").label == "bengaluru/42318"


# ── Where the engine measures ────────────────────────────────────────────────

def test_a_rule_following_its_city_measures_at_the_whole_frozen_set():
    rule = _rule(city_id=BENGALURU, lat=12.90, lon=77.57, location_name="Manjunath Garden")
    frozen = [_store("tenant", "a", 1), _store("tenant", "b", 2), _store("tenant", "c", 3)]
    stores = bid.measurement_stores(rule, {BENGALURU: frozen})
    assert [s.merchant_id for s in stores] == ["a", "b", "c"]
    assert bid.measurement_point(rule, {BENGALURU: frozen}) == \
        (12.93, 77.62, "Koramangala", "tenant")


def test_a_city_with_nothing_frozen_keeps_the_saved_store():
    rule = _rule(city_id=BENGALURU, lat=12.90, lon=77.57, location_name="Manjunath Garden")
    assert bid.measurement_point(rule, {}) == (12.90, 77.57, "Manjunath Garden", "rule")


def test_a_saved_store_carries_its_catalog_id_for_the_stock_lookup():
    rule = _rule(lat=12.90, lon=77.57, location_name="Manjunath Garden")
    [store] = bid.measurement_stores(rule, {}, {(12.90, 77.57): "30248"})
    assert store.merchant_id == "30248" and store.source == "rule"


def test_a_pinned_rule_ignores_city_stores():
    rule = _rule(city_id=None, lat=17.41, lon=78.35, location_name="Financial District")
    assert bid.measurement_point(rule, {BENGALURU: [_store()]}) == \
        (17.41, 78.35, "Financial District", "rule")


def test_a_rule_with_no_store_at_all_uses_the_default():
    assert bid.measurement_point(_rule(), {}) == \
        (bid._DEFAULT_LAT, bid._DEFAULT_LON, None, "default")


def test_a_rule_without_the_column_still_works():
    # Pre-migration rows and other tests' doubles carry no `city_id` attribute at all.
    rule = SimpleNamespace(lat=18.97, lon=72.83, location_name="Municipal Colony")
    assert bid.measurement_point(rule, {BENGALURU: [_store()]})[3] == "rule"


def test_the_engine_reads_coordinates_only_through_measurement_stores():
    src = inspect.getsource(bid.run)
    for leak in ("rule.lat", "rule.lon", "_first.lat", "_first.lon", "rule.location_name"):
        assert leak not in src, (
            f"bid.run reads `{leak}` directly — go through measurement_stores, or a city's "
            f"frozen stores are silently ignored")


# ── Reading a tick's stores (fake marketplace) ───────────────────────────────

class _FakeMarketplace:
    """Positions by store latitude. `fail` latitudes raise on fetch, `empty` ones return no
    products, `truncated` ones return a page-1-only result."""

    def __init__(self, positions: dict, fail=(), empty=(), truncated=()):
        self.positions, self.fetched, self.merchant_ids = positions, [], []
        self.fail, self.empty, self.truncated = set(fail), set(empty), set(truncated)

    async def fetch_positions(self, session, keyword, lat, lon, *, merchant_id=None):
        self.fetched.append(lat)
        self.merchant_ids.append(merchant_id)
        if lat in self.fail:
            raise RuntimeError("HTTP 429")
        if lat in self.empty:
            return PageResults()
        results = PageResults({"pid": str(i)} for i in range(48))
        results.truncated = lat in self.truncated
        return results

    def locate_position(self, results, keyword, lat, lon, **_):
        pos = self.positions.get(lat)
        return ad_slots.Placement(pos, pos, (), (),
                                  "live" if pos is not None else "product not in results")


CAMPAIGN = {"554783", "618146"}
PRODUCTS = [{"pid": "554783"}, {"pid": "618146"}]


def _read(market, stores, stock=None, cache=None, products=PRODUCTS, brand_name=None,
          given_up=None):
    return asyncio.run(bid._read_stores(
        market, None, {} if cache is None else cache, stores, "tapioca chips",
        products=products, campaign_pids={p["pid"] for p in products},
        stock_by_store=stock or {}, campaign_id=638413, match_type="EXACT",
        brand_name=brand_name, given_up=given_up))


def _three():
    return [_store(merchant_id="a", rank=1, lat=1.0), _store(merchant_id="b", rank=2, lat=2.0),
            _store(merchant_id="c", rank=3, lat=3.0)]


def test_the_store_id_reaches_the_marketplace():
    """ZC-A3. Zepto binds a search to a store by id; with only the coordinate its scraper
    resolves the store through `get_page`, a scarce separate allowance, on every search.
    The id was on every MeasurementStore and never passed."""
    market = _FakeMarketplace({1.0: 5})
    _read(market, _three())
    assert market.merchant_ids == ["a", "b", "c"]


def test_a_store_without_an_id_passes_none_not_an_empty_string():
    # A rule's own saved coordinate may have no catalogue id; "" would be sent as a header.
    market = _FakeMarketplace({1.0: 5})
    _read(market, [_store(merchant_id="", lat=1.0)])
    assert market.merchant_ids == [None]


def test_two_stores_sharing_a_coordinate_are_searched_separately():
    """The cache is keyed by store id as well as coordinate: on Zepto the id IS the store,
    and one catalogue coordinate can front two stores (express + longtail hubs)."""
    market = _FakeMarketplace({1.0: 5})
    _read(market, [_store(merchant_id="a", lat=1.0), _store(merchant_id="b", lat=1.0, rank=2)])
    assert market.merchant_ids == ["a", "b"]


def test_a_confirmed_stock_out_is_never_searched():
    market = _FakeMarketplace({2.0: 5, 3.0: 9})
    sold_out = coverage.StoreStock(complete=True, in_stock={"554783": False, "618146": False})
    readings = _read(market, _three(), {"a": sold_out})
    assert market.fetched == [2.0, 3.0]
    assert readings[0].verdict == coverage.SKIPPED
    out = coverage.aggregate(readings)
    assert out.kind == "decide" and out.binding.store.merchant_id == "c" and out.excluded == 1


def test_no_stock_known_and_not_on_the_page_still_bids_up():
    # A new automation climbing from its floor: nothing sponsored anywhere, no stock read yet.
    readings = _read(_FakeMarketplace({}), _three()[:1])
    out = coverage.aggregate(readings)
    assert out.kind == "decide" and out.binding.verdict == coverage.ABSENT
    assert out.binding.position == 49.0


def test_a_store_that_fails_to_read_leaves_the_decision_to_the_others():
    readings = _read(_FakeMarketplace({1.0: 5, 3.0: 1}, fail={2.0}), _three())
    assert [r.verdict for r in readings] == [coverage.SPONSORED, coverage.ERROR, coverage.SPONSORED]
    assert coverage.aggregate(readings).binding.position == 5


def test_every_store_sold_out_decides_nothing():
    market = _FakeMarketplace({1.0: 1})
    sold_out = coverage.StoreStock(complete=True, in_stock={"554783": False})
    readings = _read(market, _three(), {"a": sold_out, "b": sold_out, "c": sold_out})
    assert market.fetched == [] and coverage.aggregate(readings).kind == "no_stock"


def test_an_empty_search_is_not_read_as_position_one():
    # It used to be: an empty page became placeholder position 1, "target held", and a trim.
    readings = _read(_FakeMarketplace({}, empty={1.0}), _three()[:1])
    assert readings[0].verdict == coverage.UNTRUSTED
    assert coverage.aggregate(readings).kind == "error"


def test_a_cut_short_search_only_distrusts_an_ad_it_did_not_see():
    readings = _read(_FakeMarketplace({2.0: 5}, truncated={1.0, 2.0}), _three()[:2])
    assert [r.verdict for r in readings] == [coverage.UNTRUSTED, coverage.SPONSORED]


def test_unreadable_campaign_products_make_not_showing_untrusted():
    readings = _read(_FakeMarketplace({}), _three()[:1], products=[])
    assert readings[0].verdict == coverage.UNTRUSTED


def test_a_brand_name_is_enough_to_trust_not_showing():
    readings = _read(_FakeMarketplace({}), _three()[:1], products=[], brand_name="dobra")
    assert readings[0].verdict == coverage.ABSENT


def test_a_given_up_store_is_not_searched():
    market = _FakeMarketplace({1.0: 5, 2.0: 9})
    readings = _read(market, _three()[:2], given_up={"b": "out of reach at the ceiling"})
    assert market.fetched == [1.0] and readings[1].verdict == coverage.GAVE_UP


def test_a_keyword_is_searched_once_per_store_across_rules():
    market, cache = _FakeMarketplace({1.0: 5, 2.0: 9}), {}
    _read(market, _three()[:2], cache=cache)
    _read(market, _three()[:2], cache=cache)          # a second rule, same keyword + stores
    assert market.fetched == [1.0, 2.0]


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
    print(f"\n{len(tests) - failed}/{len(tests)} measurement-store tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
