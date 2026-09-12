"""Measurement stores: which dark store a bid rule reads its position at — pure, no DB, no
marketplace.

A rule names a city; the store inside it is a setting (`cm_city_stores`): a global default
that a client can override, resolved on every run so that changing it moves every automation
measuring in that city. These pin the precedence, the fall-throughs when a frozen store is
unusable, and that the engine never reads a rule's saved coordinates except through
`measurement_point`.

    python -m campaign_manager.tests.test_measurement_store
"""
import inspect
import uuid
from types import SimpleNamespace

from campaign_manager import bid, repo

DOBRA, OTHER = uuid.uuid4(), uuid.uuid4()
BENGALURU = 499


def _cs(tenant_id=None, merchant_id="30248", rank=1):
    return SimpleNamespace(tenant_id=tenant_id, merchant_id=merchant_id, rank=rank,
                           city_id=BENGALURU)


def _loc(merchant_id="30248", name="Manjunath Garden", active=True, lat=12.90, lon=77.57):
    return SimpleNamespace(merchant_id=merchant_id, location_name=name, city="bengaluru",
                           is_active=active, lat=lat, lon=lon, city_id=BENGALURU)


def _row(tenant_id=None, merchant_id="30248", **loc):
    return _cs(tenant_id, merchant_id), _loc(merchant_id, **loc)


def _picked(rows, tenant_id):
    got = repo.pick_city_store(rows, tenant_id)
    return None if got is None else (got[1].merchant_id, got[2])


def _rule(**kw):
    return SimpleNamespace(**{"city_id": None, "lat": None, "lon": None,
                              "location_name": None, **kw})


def _store(source="global"):
    return repo.MeasurementStore(lat=12.93, lon=77.62, label="Koramangala",
                                 merchant_id="31001", city_id=BENGALURU, source=source)


# ── Precedence ───────────────────────────────────────────────────────────────

def test_client_override_beats_the_global_store():
    assert _picked([_row(None, "1"), _row(DOBRA, "2")], DOBRA) == ("2", "tenant")


def test_a_client_without_an_override_gets_the_global_store():
    assert _picked([_row(None, "1")], DOBRA) == ("1", "global")


def test_another_clients_override_is_ignored():
    assert _picked([_row(None, "1"), _row(OTHER, "2")], DOBRA) == ("1", "global")


def test_no_client_sees_only_the_global_store():
    assert _picked([_row(DOBRA, "2"), _row(None, "1")], None) == ("1", "global")


def test_nothing_frozen_is_none():
    assert _picked([], DOBRA) is None
    assert _picked([_row(OTHER, "2")], DOBRA) is None


# ── An unusable frozen store falls through, never measures nowhere ────────────

def test_an_inactive_client_store_falls_back_to_global():
    assert _picked([_row(None, "1"), _row(DOBRA, "2", active=False)], DOBRA) == ("1", "global")


def test_a_store_gone_from_the_catalog_falls_back_to_global():
    assert _picked([_row(None, "1"), (_cs(DOBRA, "gone"), None)], DOBRA) == ("1", "global")


def test_a_store_without_coordinates_is_not_usable():
    assert _picked([_row(DOBRA, "2", lat=None)], DOBRA) is None


def test_only_the_primary_rank_is_the_frozen_store():
    assert _picked([(_cs(DOBRA, "9", rank=2), _loc("9"))], DOBRA) is None


# ── Labels ───────────────────────────────────────────────────────────────────

def test_catalog_labels_are_trimmed():
    # Real catalog data: "Financial District\r\n" was showing up verbatim in run logs.
    assert repo._store_of(_loc("42318", name="Financial District\r\n"), "catalog").label == \
        "Financial District"


def test_a_nameless_store_is_labelled_by_city_and_id():
    assert repo._store_of(_loc("42318", name=""), "catalog").label == "bengaluru/42318"


# ── Where the engine measures ────────────────────────────────────────────────

def test_a_rule_following_its_city_measures_at_the_frozen_store():
    rule = _rule(city_id=BENGALURU, lat=12.90, lon=77.57, location_name="Manjunath Garden")
    assert bid.measurement_point(rule, {BENGALURU: _store("tenant")}) == \
        (12.93, 77.62, "Koramangala", "tenant")


def test_a_city_with_nothing_frozen_keeps_the_saved_store():
    rule = _rule(city_id=BENGALURU, lat=12.90, lon=77.57, location_name="Manjunath Garden")
    assert bid.measurement_point(rule, {}) == (12.90, 77.57, "Manjunath Garden", "rule")


def test_a_pinned_rule_ignores_city_stores():
    rule = _rule(city_id=None, lat=17.41, lon=78.35, location_name="Financial District")
    assert bid.measurement_point(rule, {BENGALURU: _store()}) == \
        (17.41, 78.35, "Financial District", "rule")


def test_a_rule_with_no_store_at_all_uses_the_default():
    assert bid.measurement_point(_rule(), {}) == \
        (bid._DEFAULT_LAT, bid._DEFAULT_LON, None, "default")


def test_a_rule_without_the_column_still_works():
    # Pre-migration rows and other tests' doubles carry no `city_id` attribute at all.
    rule = SimpleNamespace(lat=18.97, lon=72.83, location_name="Municipal Colony")
    assert bid.measurement_point(rule, {BENGALURU: _store()})[3] == "rule"


def test_the_engine_reads_coordinates_only_through_measurement_point():
    src = inspect.getsource(bid.run)
    for leak in ("rule.lat", "rule.lon", "_first.lat", "_first.lon", "rule.location_name"):
        assert leak not in src, (
            f"bid.run reads `{leak}` directly — go through measurement_point, or a city's "
            f"frozen store is silently ignored")


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
