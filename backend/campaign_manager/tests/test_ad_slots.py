"""Ad slots — the bid target is the Nth SPONSORED listing on the page (2026-10-05).

The pure counting (`campaign_manager/ad_slots.py`), Blinkit's matcher on top of it, and the
engine plumbing that carries a slot from a search to a decision and into History — no DB, no
marketplace. Zepto's attribution has its own module (test_zepto_positions.py).

    python -m campaign_manager.tests.test_ad_slots
"""
import asyncio
import uuid
from types import SimpleNamespace

from campaign_manager import ad_slots, bid, coverage, repo
from campaign_manager.marketplaces import get_adapter
from campaign_manager.marketplaces.blinkit import positions as bpos
from campaign_manager.marketplaces.blinkit.live_position import PageResults


def ad(pos, pid="x", name="Other Brand Soda"):
    return {"position": pos, "is_ad": True, "pid": pid, "name": name}


def org(pos, pid="x", name="Other Brand Soda"):
    return {"position": pos, "is_ad": False, "pid": pid, "name": name}


# ── counting ─────────────────────────────────────────────────────────────────

def test_slots_are_numbered_among_shown_ads_only():
    """Deepansh's example: ads at 2, 5, 6, 9, 11 are Ad #1-#5, so Ad #2 is position 5."""
    results = [org(1), ad(2), org(3), org(4), ad(5), ad(6), org(7), org(8), ad(9), org(10), ad(11)]
    ads = ad_slots.ad_positions(results)
    assert ads == (2, 5, 6, 9, 11)
    assert ad_slots.slot_of(5, ads) == 2
    assert ad_slots.page_position_of_slot(1, ads) == 2
    assert ad_slots.page_position_of_slot(2, ads) == 5


def test_the_same_target_follows_a_different_layout():
    """Ads at 1, 3, 5, 7: Ad #2 is position 3. The client never sees the layout."""
    ads = ad_slots.ad_positions([ad(1), org(2), ad(3), org(4), ad(5), org(6), ad(7)])
    assert ad_slots.page_position_of_slot(2, ads) == 3


def test_an_empty_layout_slot_is_not_a_slot():
    """Blinkit's layout has places for ads at 1/5/9; if 5 goes unfilled, the ad at 9 is the
    SECOND ad a shopper sees — Ad #2, not #3."""
    ads = ad_slots.ad_positions([ad(1), org(5), ad(9)])
    assert ad_slots.slot_of(9, ads) == 2


def test_a_position_with_no_ad_has_no_slot():
    assert ad_slots.slot_of(4, (1, 5)) is None
    assert ad_slots.slot_of(None, (1, 5)) is None


def test_a_page_with_fewer_ads_than_the_target_has_no_such_slot():
    assert ad_slots.page_position_of_slot(3, (1, 5)) is None
    assert ad_slots.page_position_of_slot(0, (1, 5)) is None


def test_place_builds_the_whole_reading():
    p = ad_slots.place([org(1), ad(2), ad(5)], 5, [1, 1], "live")
    assert (p.slot, p.page_position, p.ad_positions, p.organic_positions) == (2, 5, (2, 5), (1,))


def test_no_ad_of_ours_is_no_slot_whatever_organic_shows():
    p = ad_slots.place([org(1), ad(2)], None, [1], "organic only")
    assert p.slot is None and p.page_position is None and p.organic_positions == (1,)


def test_the_label_people_read():
    assert ad_slots.label(2, 5) == "Ad #2 · position 5"
    assert ad_slots.label(2) == "Ad #2"
    assert ad_slots.label(None) == "no ad slot"


# ── the organic-overlap warning's rule ───────────────────────────────────────

def test_organic_above_the_target_slot_is_an_overlap():
    """Target Ad #2 = position 5 here; we're organic at 1 → paying for visibility we have."""
    assert ad_slots.organic_overlap(2, (2, 5, 6, 9, 11), (1, 4)) == 1


def test_organic_below_the_target_slot_is_not():
    assert ad_slots.organic_overlap(1, (2, 5), (4,)) is None


def test_no_overlap_without_organic_or_without_the_slot():
    assert ad_slots.organic_overlap(1, (2, 5), ()) is None
    assert ad_slots.organic_overlap(3, (2, 5), (1,)) is None      # the page has no Ad #3


def _page(mid, minutes, ads, organic, label=None):
    from datetime import datetime, timedelta
    return SimpleNamespace(merchant_id=mid, store_label=label or mid, ad_positions=list(ads),
                           organic_positions=list(organic),
                           observed_at=datetime(2026, 10, 5, 12) - timedelta(minutes=minutes))


def test_the_warning_needs_most_recent_checks_at_a_store():
    """Target Ad #2. Store A: organic at 1 above Ad #2 (position 5) in 3 of its last 4 checks
    → warn. Store B: once in 3 → not."""
    reads = [_page("A", 0, (2, 5), (1,)), _page("B", 0, (1, 5), ()),
             _page("A", 15, (2, 5), (1,)), _page("B", 15, (1, 5), (2,)),
             _page("A", 30, (2, 5), ()), _page("B", 30, (1, 5), ()),
             _page("A", 45, (2, 5), (1,))]
    o = ad_slots.overlap_summary(reads, 2)
    assert (o.stores, o.of, o.store_labels) == (1, 2, ("A",))
    assert (o.organic_positions, o.target_page_position) == ((1,), 5)


def test_one_reading_never_raises_the_warning():
    assert ad_slots.overlap_summary([_page("A", 0, (2, 5), (1,))], 2) is None


def test_half_the_checks_is_not_most():
    reads = [_page("A", 0, (2, 5), (1,)), _page("A", 15, (2, 5), ())]
    assert ad_slots.overlap_summary(reads, 2) is None


def test_no_readings_no_warning():
    assert ad_slots.overlap_summary([], 1) is None


# ── the API speaks ad slots ──────────────────────────────────────────────────

_RULE = {"campaign_id": 1, "keyword": "soda", "min_bid": 100}


def test_the_api_accepts_the_target_by_either_name():
    """The dashboard sends `target_ad_slot`; an older one sends `target_position`. Frontend and
    backend deploy separately, so both must work."""
    from app.schemas.campaign_manager import BidRuleIn, BidRuleUpdate
    assert BidRuleIn(**_RULE, target_ad_slot=2).target_position == 2
    assert BidRuleIn(**_RULE, target_position=3).target_position == 3
    assert BidRuleUpdate(target_ad_slot=1).model_dump(exclude_unset=True) == {"target_position": 1}


def test_the_target_is_ad_1_to_5():
    import pydantic
    from app.schemas.campaign_manager import BidRuleIn, BidRuleUpdate
    for bad in (0, 6):
        for make in (lambda v: BidRuleIn(**_RULE, target_ad_slot=v),
                     lambda v: BidRuleUpdate(target_ad_slot=v)):
            try:
                make(bad)
            except pydantic.ValidationError:
                continue
            raise AssertionError(f"target {bad} was accepted")


def test_a_listed_rule_says_its_target_slot_and_the_warning():
    from app.services.campaign_manager_service import _bid_out
    r = SimpleNamespace(
        id="r1", campaign_id=1, campaign_name="C", keyword="soda", target_position=2,
        min_bid=10, max_bid=None, match_type="EXACT", type="recurring", date=None, days=[],
        start_time="09:00", stop_time="21:00", start_date=None, stop_date=None, lat=None,
        lon=None, location_name=None, state="active", platform="blinkit", ended_at=None,
        settled_at=None)
    o = _bid_out(r, overlap=ad_slots.overlap_summary(
        [_page("A", 0, (2, 5), (1,)), _page("A", 15, (2, 5), (1,))], 2))
    assert o.target_ad_slot == 2 and o.target_position == 2
    assert o.organic_overlap.organic_positions == [1]
    assert o.organic_overlap.target_page_position == 5
    assert _bid_out(r).organic_overlap is None


# ── Blinkit's matcher ────────────────────────────────────────────────────────

def test_blinkit_reports_our_slot_among_all_ads():
    results = [ad(1), org(2), org(3), org(4), ad(5, pid="p1", name="Dobra Goli Soda"), ad(9)]
    p = bpos.locate(results, "goli soda", 0, 0, product_names=["Dobra Goli Soda"],
                    product_pids=["p1"], brand_name="dobra")
    assert (p.slot, p.page_position, p.ad_positions) == (2, 5, (1, 5, 9))


def test_blinkit_organic_only_is_no_slot():
    """It always read as "not showing" on Blinkit; it still does, now with the organic
    listing recorded."""
    results = [org(1, pid="p1", name="Dobra Goli Soda"), ad(2)]
    p = bpos.locate(results, "goli soda", 0, 0, product_names=["Dobra Goli Soda"],
                    product_pids=["p1"], brand_name="dobra")
    assert p.slot is None and p.organic_positions == (1,) and "organic only" in p.reason


def test_blinkit_organic_is_matched_by_product_id_only():
    """Name tokens are good enough to recognise our AD, but they catch other products too —
    and an organic listing only feeds a warning, which must not cry wolf."""
    results = [org(1, pid="q9", name="Dobra Masala Soda"), org(2, pid="p1")]
    p = bpos.locate(results, "soda", 0, 0, product_names=["Dobra Goli Soda"],
                    product_pids=["p1"], brand_name="dobra")
    assert p.organic_positions == (2,)


# ── the engine ───────────────────────────────────────────────────────────────

class _Blinkit:
    """Real Blinkit matching over a canned page."""

    def __init__(self, page):
        self.page = page

    async def fetch_positions(self, session, keyword, lat, lon, *, merchant_id=None):
        return PageResults(self.page)

    def locate_position(self, results, keyword, lat, lon, **kw):
        return get_adapter("blinkit").locate_position(results, keyword, lat, lon, **kw)


STORE = repo.MeasurementStore(lat=12.9, lon=77.5, label="Store1", merchant_id="m1",
                              city_id=7, source="tenant", rank=1)
PRODUCTS = [{"pid": "p1", "name": "Dobra Goli Soda"}]


def _read(page):
    return asyncio.run(bid._read_stores(
        _Blinkit(page), None, {}, [STORE], "goli soda", products=PRODUCTS,
        campaign_pids={"p1"}, stock_by_store={}, campaign_id=1, match_type="EXACT",
        brand_name="dobra"))[0]


def test_the_engine_decides_on_the_slot_and_keeps_the_page():
    r = _read([org(1, pid="p1"), ad(2), ad(5, pid="p1", name="Dobra Goli Soda"), ad(6)])
    assert r.verdict == coverage.SPONSORED
    assert r.position == 2 and r.page_position == 5             # Ad #2 · position 5
    assert r.ad_positions == (2, 5, 6) and r.organic_positions == (1,)


def test_not_showing_stays_worse_than_any_slot_even_with_no_ads_on_the_page():
    """The placeholder is counted in RESULTS, not ads. "ads + 1" on a page with no ads would
    be 1 — read as holding a target of Ad #1, and the bid would be trimmed."""
    r = _read([org(1), org(2, pid="p1"), org(3)])
    assert r.verdict == coverage.ABSENT
    assert r.position == coverage.absent_position(3) == 4.0
    assert r.position > 1 and r.organic_positions == (2,)


def test_the_store_row_keeps_page_position_and_slot_apart():
    r = _read([ad(2), ad(5, pid="p1", name="Dobra Goli Soda")])
    rule = SimpleNamespace(id="r1", campaign_id=1, keyword="goli soda", city_id=7)
    outcome = coverage.aggregate([r])
    row = bid._store_rows(uuid.uuid4(), "blinkit", "run", rule, outcome.readings, outcome,
                          20, True)[0]
    assert (row["position"], row["ad_slot"]) == (5, 2)
    assert row["ad_positions"] == [2, 5] and row["organic_positions"] == []


def test_an_absent_store_row_records_the_page_but_no_slot():
    r = _read([org(1, pid="p1"), ad(2)])
    rule = SimpleNamespace(id="r1", campaign_id=1, keyword="goli soda", city_id=7)
    outcome = coverage.aggregate([r])
    row = bid._store_rows(uuid.uuid4(), "blinkit", "run", rule, outcome.readings, outcome,
                          20, True)[0]
    assert row["position"] is None and row["ad_slot"] is None
    assert row["ad_positions"] == [2] and row["organic_positions"] == [1]


def test_the_history_row_carries_the_slot_beside_the_page_position():
    row = bid._row(uuid.uuid4(), "blinkit", "run", 1, "C", "kw", "hold", 10, 10, "why", True,
                   True, rule_id="r1", position=5, ad_slot=2, target=1)
    assert (row["position"], row["ad_slot"], row["target"]) == (5, 2, 1)


def test_every_history_row_says_its_target_is_an_ad_slot():
    """On a "not showing" row slot and position are both empty, so without the stamp History
    could not tell a new target (Ad #1) from an old one (position 1)."""
    row = bid._row(uuid.uuid4(), "blinkit", "run", 1, "C", "kw", "apply", 10, 12, "why", True,
                   True, rule_id="r1", target=1)
    assert row["ad_slot"] is None and row["measured_in"] == "ad_slot"


# ── learned state from before the switch ─────────────────────────────────────

def test_state_learned_in_page_positions_is_stale():
    """A relaxed target of 5 written before the switch would read as Ad #5."""
    assert bid.slot_state_is_stale(SimpleNamespace(measured_in=None)) is True
    assert bid.slot_state_is_stale(SimpleNamespace()) is True         # pre-migration row
    assert bid.slot_state_is_stale(SimpleNamespace(measured_in="ad_slot")) is False


def test_a_rule_with_no_state_has_nothing_stale():
    assert bid.slot_state_is_stale(None) is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} ad-slot tests passed.")
