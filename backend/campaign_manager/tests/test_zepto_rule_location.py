"""ZC-C4/C14 — a Zepto bid rule always knows where it measures.

The rule's author may name a city or a store; when they name neither, the city comes from
the CAMPAIGN's own targeting, and the store from the freeze layers (`cm stores`). Pure /
stubbed — no DB, no Zepto.

    python -m campaign_manager.tests.test_zepto_rule_location
"""
import asyncio
import uuid

from campaign_manager import repo

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
CAMPAIGN = 2427461


async def _no_duplicate(*a, **k):
    """`repo.require_no_live_bid_rule` stubbed away — ZC-C9 has its own test file, and it
    would query the real `CmBidRule` these tests swap for a recorder."""
    return None


def _store(merchant_id="m1", source="catalog", city_id=1, label="A store"):
    return repo.MeasurementStore(lat=12.9, lon=77.6, label=label, merchant_id=merchant_id,
                                 city_id=city_id, source=source)


# ── the choice itself (pure) ────────────────────────────────────────────────

def test_a_frozen_city_wins_even_with_fewer_stores():
    """Freezing a store is a deliberate choice; store COUNT is only the tie-break for
    cities nobody has configured."""
    cities = {1: ("Bengaluru", "KA", _store(source="catalog", city_id=1)),
              2: ("Mysore", "KA", _store(source="global", city_id=2))}
    assert repo.best_measurement_city(cities, {1: 169, 2: 3})[0] == 2


def test_a_tenant_freeze_counts_as_frozen_too():
    cities = {1: ("Bengaluru", "KA", _store(source="catalog", city_id=1)),
              2: ("Mysore", "KA", _store(source="tenant", city_id=2))}
    assert repo.best_measurement_city(cities, {1: 169, 2: 3})[0] == 2


def test_with_nothing_frozen_the_biggest_city_wins():
    cities = {1: ("Bengaluru", "KA", _store(city_id=1)),
              2: ("Mysore", "KA", _store(city_id=2))}
    assert repo.best_measurement_city(cities, {1: 169, 2: 3})[0] == 1


def test_a_tie_is_broken_by_name_so_the_answer_is_stable():
    cities = {1: ("Mysore", "KA", _store(city_id=1)), 2: ("Bengaluru", "KA", _store(city_id=2))}
    assert repo.best_measurement_city(cities, {1: 5, 2: 5})[0] == 2
    assert repo.best_measurement_city(cities, {})[0] == 2


# ── picking for a campaign (DB calls stubbed) ───────────────────────────────

def _pick(*, specific, names, resolved, catalog, counts=None):
    calls = {}

    async def _targets(tenant_id, platform, campaign_id):
        return specific, names

    async def _resolve(platform, wanted):
        calls["resolved"] = list(wanted)
        return {n.strip().lower(): resolved.get(n.strip().lower()) for n in wanted}

    async def _measurable(platform, *, tenant_id=None, city_ids=None):
        calls["city_ids"] = None if city_ids is None else set(city_ids)
        return catalog

    orig = (repo.campaign_target_cities, repo.resolve_city_ids, repo.measurable_cities,
            repo.AsyncSessionLocal)
    repo.campaign_target_cities, repo.resolve_city_ids = _targets, _resolve
    repo.measurable_cities = _measurable
    repo.AsyncSessionLocal = _FakeSession(counts or {})
    try:
        return asyncio.run(repo.pick_rule_location(TENANT, "zepto", CAMPAIGN)), calls
    finally:
        (repo.campaign_target_cities, repo.resolve_city_ids, repo.measurable_cities,
         repo.AsyncSessionLocal) = orig


class _FakeSession:
    """Stands in for `AsyncSessionLocal()` — answers only the store-count query."""

    def __init__(self, counts):
        self.counts = counts

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *a, **k):
        counts = self.counts

        class _R:
            def all(self):
                return list(counts.items())
        return _R()


def test_a_city_targeted_campaign_measures_only_where_it_runs():
    (store, unresolved), calls = _pick(
        specific=True, names=["Bengaluru", "Mysuru"],
        resolved={"bengaluru": 499, "mysuru": 500},
        catalog={499: ("Bengaluru", "KA", _store(city_id=499)),
                 500: ("Mysore", "KA", _store(city_id=500))},
        counts={499: 169, 500: 4})
    assert calls["city_ids"] == {499, 500}, "must narrow to the campaign's own cities"
    assert store.city_id == 499 and unresolved == []


def test_a_campaign_running_everywhere_may_use_any_measurable_city():
    (store, unresolved), calls = _pick(
        specific=False, names=[], resolved={},
        catalog={499: ("Bengaluru", "KA", _store(city_id=499))}, counts={499: 169})
    assert calls["city_ids"] is None
    assert store.city_id == 499


def test_an_unmatched_city_name_is_reported_not_swallowed():
    """Zepto says "Belgavi"; our registry says "Belgaum". The rule still gets a city, and
    the unmatched name comes back so a save can mention it (ZC-C4)."""
    (store, unresolved), _ = _pick(
        specific=True, names=["Bengaluru", "Belgavi"],
        resolved={"bengaluru": 499, "belgavi": None},
        catalog={499: ("Bengaluru", "KA", _store(city_id=499))}, counts={499: 169})
    assert store.city_id == 499
    assert unresolved == ["Belgavi"]


def test_nothing_resolvable_means_no_store_and_the_names_to_fix():
    (store, unresolved), _ = _pick(
        specific=True, names=["Belgavi"], resolved={"belgavi": None}, catalog={})
    assert store is None and unresolved == ["Belgavi"]


def test_a_city_we_know_but_have_no_store_in_yields_nothing():
    (store, unresolved), _ = _pick(
        specific=True, names=["Belgavi"], resolved={"belgavi": 498}, catalog={})
    assert store is None and unresolved == []


def test_catalog_text_entries_are_never_saved_as_a_city_id():
    """`measurable_cities` also returns keys like `text:mysuru` for stores whose city has no
    canonical row. Those cannot be a rule's `city_id`, so they must not be picked."""
    (store, _u), _ = _pick(
        specific=False, names=[], resolved={},
        catalog={"text:mysuru": ("Mysuru", None, _store(city_id=None))})
    assert store is None


# ── what the save does with it ──────────────────────────────────────────────

def test_a_rule_with_no_city_is_given_one_rather_than_refused():
    created = {}

    async def _ok(tenant_id, platform, campaign_id):
        return None

    async def _pick_loc(tenant_id, platform, campaign_id):
        return _store(city_id=499, label="Byatarayanapura"), []

    restore = _fake_model(created)
    orig = (repo.require_automatable, repo.pick_rule_location, repo.AsyncSessionLocal,
            repo.require_no_live_bid_rule)
    repo.require_automatable, repo.pick_rule_location = _ok, _pick_loc
    repo.require_no_live_bid_rule = _no_duplicate       # ZC-C9, covered by its own tests
    repo.AsyncSessionLocal = _FakeDb()
    try:
        asyncio.run(repo.create_bid_rule(TENANT, "zepto", CAMPAIGN, "Tech Test",
                                         "pink toffee", 3, 10))
    finally:
        restore()
        (repo.require_automatable, repo.pick_rule_location, repo.AsyncSessionLocal,
         repo.require_no_live_bid_rule) = orig

    assert created["city_id"] == 499, "saved BY CITY, so it follows that city's frozen store"
    assert created["lat"] == 12.9 and created["lon"] == 77.6
    assert created["location_name"] == "Byatarayanapura"


def test_a_rule_that_cannot_be_placed_says_which_cities_failed():
    async def _ok(tenant_id, platform, campaign_id):
        return None

    async def _pick_loc(tenant_id, platform, campaign_id):
        return None, ["Belgavi"]

    orig = (repo.require_automatable, repo.pick_rule_location)
    repo.require_automatable, repo.pick_rule_location = _ok, _pick_loc
    try:
        asyncio.run(repo.create_bid_rule(TENANT, "zepto", CAMPAIGN, "Tech Test",
                                         "pink toffee", 3, 10))
    except repo.NotAutomatable as e:
        assert "Belgavi" in str(e) and "Nothing was created" in str(e)
    else:
        raise AssertionError("must refuse")
    finally:
        repo.require_automatable, repo.pick_rule_location = orig


def test_blinkit_still_saves_a_rule_with_no_location_at_all():
    """Only a marketplace that declares it needs one is placed; Blinkit's coordinate
    fallback is a real search, so nothing changes there."""
    created = {}

    async def _boom(*a, **k):
        raise AssertionError("Blinkit must not be sent through the placer")

    restore = _fake_model(created)
    orig = (repo.pick_rule_location, repo.AsyncSessionLocal, repo.require_no_live_bid_rule)
    repo.pick_rule_location = _boom
    repo.require_no_live_bid_rule = _no_duplicate
    repo.AsyncSessionLocal = _FakeDb()
    try:
        asyncio.run(repo.create_bid_rule(TENANT, "blinkit", 123, "C", "kw", 3, 10))
    finally:
        restore()
        (repo.pick_rule_location, repo.AsyncSessionLocal,
         repo.require_no_live_bid_rule) = orig
    assert created["city_id"] is None and created["lat"] is None


class _FakeDb:
    """`AsyncSessionLocal()` for a create: records the row, commits and refreshes nothing.

    `create_bid_rule` imports `CmBidRule` inside the function, so the model is swapped by
    `_fake_model()` BEFORE the call — swapping it when the session opens is already too
    late."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.row = row

    async def commit(self):
        return None

    async def refresh(self, row):
        return None


def _fake_model(created: dict):
    """Swap `CmBidRule` for a recorder; returns the restore callable. `create_bid_rule`
    imports it inside the function, so this must happen BEFORE the call."""
    import app.models.campaign_manager_v2 as m

    class _FakeRule:
        def __init__(self, **kw):
            created.update(kw)

        def __getattr__(self, k):
            return created.get(k)

    orig = m.CmBidRule
    m.CmBidRule = _FakeRule

    def _restore():
        m.CmBidRule = orig
    return _restore


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto rule-location tests passed.")
