"""Unit tests for the catalogue write-back (docs §4 — "Tables it READS but does not own").

Pure logic — no Blinkit, no DB. Covers the three questions that matter:

  1. does a landed LIVE write produce a patch, and the right one?
  2. does anything that did NOT land produce none? (dry run, refusal, no-op, guardrail)
  3. does a marketplace with no `catalog_patch` produce none? — the Zepto guarantee,
     pinned here so nobody has to remember it when Zepto's write-back is built.

Run:  python -m campaign_manager.tests.test_catalog_writeback
"""
import asyncio

from campaign_manager import repo, writes
from campaign_manager.marketplaces.blinkit import adapter as blinkit


# ── Fakes ────────────────────────────────────────────────────────────────────

class _ZeptoLike:
    """A marketplace that accepts every write but has not taught us where those writes
    land in our catalogue — which is exactly Zepto today.

    It genuinely has no `catalog_patch` attribute (rather than one set to None), because
    that is the real shape of the thing under test: a module that does not define it."""
    MIN_BUDGET = None
    MAX_BUDGET = None
    MIN_BID = None
    MAX_BID = None
    RESUME_RESUBMITS = True

    def __init__(self, ok=True):
        self._resp = {"status": True} if ok else {"status": False, "message": "nope"}

    async def apply_budget(self, client, campaign_id, budget):
        return self._resp

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type):
        return self._resp

    async def apply_status(self, client, campaign_id, target, *, budget=None):
        return self._resp


class _Adapter(_ZeptoLike):
    """The same marketplace, once it HAS declared where its writes land. Borrows Blinkit's
    real `catalog_patch` so the vocabulary under test is the shipped one."""
    catalog_patch = staticmethod(blinkit.catalog_patch)


def _budget(**kw):
    defaults = dict(run_id="t", campaign_id=101, target=700, current=200,
                    dry_run=False, recent_writes=0)
    defaults.update(kw)
    applied = defaults.pop("applied")
    adapter = defaults.pop("adapter", _Adapter())
    asyncio.run(writes.apply_budget(adapter, None, applied=applied, **defaults))
    return applied


def _bid(**kw):
    defaults = dict(run_id="t", campaign_id=101, keyword="soda", new_cpm=450,
                    current_cpm=200, min_bid=100, max_bid=900, match_type="EXACT",
                    dry_run=False, recent_writes=0)
    defaults.update(kw)
    applied = defaults.pop("applied")
    adapter = defaults.pop("adapter", _Adapter())
    asyncio.run(writes.apply_bid(adapter, None, applied=applied, **defaults))
    return applied


def _status(**kw):
    defaults = dict(run_id="t", campaign_id=101, target="paused", current="running",
                    dry_run=False, recent_writes=0)
    defaults.update(kw)
    applied = defaults.pop("applied")
    adapter = defaults.pop("adapter", _Adapter())
    asyncio.run(writes.apply_status(adapter, None, applied=applied, **defaults))
    return applied


# ── 1. A landed write produces the right patch ───────────────────────────────

def test_budget_write_patches_the_campaign_row():
    [p] = _budget(applied=[])
    assert p["table"] == blinkit.CATALOG_CAMPAIGNS
    assert p["key"] == {"campaign_id": 101}
    assert p["set"] == {"daily_budget": 700}


def test_bid_write_patches_the_keyword_row():
    [p] = _bid(applied=[])
    assert p["table"] == blinkit.CATALOG_KEYWORDS
    assert p["key"] == {"campaign_id": 101, "keyword": "soda", "match_type": "EXACT"}
    assert p["set"] == {"current_cpm": 450}


def test_a_bid_is_recorded_at_the_CLAMPED_value():
    # The rule asks for 5000, the ceiling is 900 — 900 is what Blinkit was sent, so 900
    # is what the catalogue must say. Recording the request would make our copy disagree
    # with the marketplace in the one direction that matters (too high).
    [p] = _bid(applied=[], new_cpm=5000)
    assert p["set"] == {"current_cpm": 900}


def test_a_broad_rule_patches_the_SMART_row():
    # `apply_bid` sends BROAD as SMART and the scrape keys the row that way, so a BROAD
    # rule whose patch said "BROAD" would silently match no row at all.
    [p] = _bid(applied=[], match_type="BROAD")
    assert p["key"]["match_type"] == "SMART"


def test_stop_patches_status_only():
    [p] = _status(applied=[])
    assert p["set"] == {"status": "STOPPED"}


def test_restart_patches_status_AND_budget():
    # A Blinkit restart re-submits the campaign and sets its budget — recording only the
    # status would leave `daily_budget` stale after the one write that certainly moved it.
    [p] = _status(applied=[], target="running", current="paused", budget=650)
    assert p["set"] == {"status": "ACTIVE", "daily_budget": 650}


# ── 2. Anything that did not land produces nothing ───────────────────────────

def test_dry_run_records_nothing():
    assert _budget(applied=[], dry_run=True) == []
    assert _bid(applied=[], dry_run=True) == []
    assert _status(applied=[], dry_run=True) == []


def test_a_refused_write_records_nothing():
    assert _budget(applied=[], adapter=_Adapter(ok=False)) == []
    assert _bid(applied=[], adapter=_Adapter(ok=False)) == []
    assert _status(applied=[], adapter=_Adapter(ok=False)) == []


def test_a_noop_records_nothing():
    # The budget is already 700 → no write goes out, so nothing to mirror.
    assert _budget(applied=[], target=700, current=700) == []
    assert _bid(applied=[], new_cpm=200, current_cpm=200) == []


def test_a_guardrail_trip_records_nothing():
    # Terminal state: the transition table refuses, so no write and no patch.
    assert _status(applied=[], target="running", current="ended", budget=650) == []


# ── 3. The Zepto guarantee ───────────────────────────────────────────────────

def test_a_marketplace_without_catalog_patch_records_nothing():
    assert not hasattr(_ZeptoLike, "catalog_patch")
    assert _budget(applied=[], adapter=_ZeptoLike()) == []
    assert _bid(applied=[], adapter=_ZeptoLike()) == []
    assert _status(applied=[], adapter=_ZeptoLike()) == []


def test_a_broken_catalog_patch_never_breaks_the_write():
    class _Broken(_Adapter):
        @staticmethod
        def catalog_patch(*a, **k):
            raise RuntimeError("boom")

    applied = []
    ok = asyncio.run(writes.apply_budget(
        _Broken(), None, run_id="t", campaign_id=1, target=700, current=200,
        dry_run=False, recent_writes=0, applied=applied))
    assert ok is True and applied == []


def test_no_accumulator_is_harmless():
    # Every `apply_*` must still work when nobody passes one — the CLI and the tests do.
    assert asyncio.run(writes.apply_budget(
        _Adapter(), None, run_id="t", campaign_id=1, target=700, current=200,
        dry_run=False, recent_writes=0)) is True


# ── merge_patches (pure) ─────────────────────────────────────────────────────

def test_merge_collapses_one_row_to_one_statement():
    merged = repo.merge_patches([
        {"table": "blinkit.campaigns", "key": {"campaign_id": 1}, "set": {"daily_budget": 200}},
        {"table": "blinkit.campaigns", "key": {"campaign_id": 1}, "set": {"status": "STOPPED"}},
    ])
    assert merged == [{"table": "blinkit.campaigns", "key": {"campaign_id": 1},
                       "set": {"daily_budget": 200, "status": "STOPPED"}}]


def test_merge_lets_the_last_write_win():
    # The revert-then-stop sequence writes the budget twice in one run; the catalogue must
    # end on the value the marketplace ended on.
    merged = repo.merge_patches([
        {"table": "blinkit.campaigns", "key": {"campaign_id": 1}, "set": {"daily_budget": 1500}},
        {"table": "blinkit.campaigns", "key": {"campaign_id": 1}, "set": {"daily_budget": 200}},
    ])
    assert merged[0]["set"]["daily_budget"] == 200


def test_merge_keeps_distinct_rows_apart():
    merged = repo.merge_patches([
        {"table": "blinkit.keywords", "key": {"campaign_id": 1, "keyword": "soda"}, "set": {"current_cpm": 300}},
        {"table": "blinkit.keywords", "key": {"campaign_id": 1, "keyword": "cola"}, "set": {"current_cpm": 400}},
    ])
    assert len(merged) == 2


def test_merge_drops_empty_and_none():
    assert repo.merge_patches([None, {}, {"table": "x", "key": {}, "set": {}}]) == []


def test_merge_refuses_a_patch_that_names_no_row():
    # The dangerous one. `record_applied` scopes by tenant + platform and ANDs the key on
    # top, so a patch with no key would widen to "UPDATE every campaign this client owns".
    # It must be DROPPED, never treated as "match anything".
    assert repo.merge_patches([
        {"table": "blinkit.campaigns", "key": {}, "set": {"daily_budget": 700}},
    ]) == []
    assert repo.merge_patches([
        {"table": "blinkit.campaigns", "set": {"daily_budget": 700}},
    ]) == []


def test_merge_survives_a_malformed_patch():
    # A patch missing its table must not raise out of the merge — `record_applied`'s
    # promise is that bookkeeping never breaks the write it is describing.
    good = {"table": "blinkit.campaigns", "key": {"campaign_id": 1}, "set": {"status": "ACTIVE"}}
    assert repo.merge_patches([{"key": {"campaign_id": 9}, "set": {"x": 1}}, good]) == [good]


def test_unknown_write_kind_is_not_an_error():
    # The marketplace has already been mutated by then — an unmapped kind must cost a
    # stale column, never a raised exception.
    assert blinkit.catalog_patch("colour", campaign_id=1, value="red") == []


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
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} write-back tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
