"""Coverage: which stores a bid decision counts, and the one position it acts on — pure.

The rule is "target at every store where the campaign is listed and in stock", which is the
same as "the worst such store at target". These pin who counts, who binds, and — above all —
that only CONFIRMED absence of stock can ever stop a raise.

    python -m campaign_manager.tests.test_coverage
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from campaign_manager import coverage as c

CAMPAIGN = {"554783", "554779", "618146", "804747", "618143"}   # 5 tapioca flavours


def _stock(complete=True, **in_stock):
    return c.StoreStock(complete=complete, in_stock={k.lstrip("p"): v for k, v in in_stock.items()})


def _store(rank=1, label=None):
    return SimpleNamespace(rank=rank, label=label or f"store {rank}", merchant_id=str(rank))


def _r(verdict, position=None, rank=1, elig=c.ELIGIBLE):
    return c.Reading(_store(rank), elig, verdict, position)


# ── Eligibility ──────────────────────────────────────────────────────────────

def test_one_flavour_in_stock_is_enough():
    stock = _stock(p554783=True, p554779=False, p618146=False)
    assert c.eligibility(CAMPAIGN, stock) == c.ELIGIBLE


def test_listed_but_all_sold_out_is_out_of_stock_when_the_read_was_complete():
    stock = _stock(p554783=False, p554779=False)
    assert c.eligibility(CAMPAIGN, stock) == c.OUT_OF_STOCK


def test_sold_out_on_a_partial_read_is_only_unknown():
    # Other flavours may sit beyond the cap, in stock — a partial read cannot rule them out.
    stock = _stock(complete=False, p554783=False)
    assert c.eligibility(CAMPAIGN, stock) == c.UNKNOWN


def test_not_listed_needs_a_complete_read():
    assert c.eligibility(CAMPAIGN, _stock(p999=True)) == c.NOT_LISTED
    assert c.eligibility(CAMPAIGN, _stock(complete=False, p999=True)) == c.UNKNOWN


def test_another_campaigns_stock_does_not_make_a_store_eligible():
    # Goli soda in stock says nothing about whether tapioca chips can be sold here.
    assert c.eligibility(CAMPAIGN, _stock(p620124=True, p554784=True)) == c.NOT_LISTED


def test_no_stock_read_is_unknown():
    assert c.eligibility(CAMPAIGN, None) == c.UNKNOWN


def test_no_campaign_product_ids_is_unknown():
    assert c.eligibility(set(), _stock(p554783=False)) == c.UNKNOWN
    assert c.eligibility(None, _stock(p554783=False)) == c.UNKNOWN


def test_only_eligible_and_unknown_stores_count():
    assert c.counts(c.ELIGIBLE) and c.counts(c.UNKNOWN)
    assert not c.counts(c.OUT_OF_STOCK) and not c.counts(c.NOT_LISTED)


# ── Aggregation ──────────────────────────────────────────────────────────────

def test_the_worst_counted_store_binds():
    out = c.aggregate([_r(c.SPONSORED, 5, 1), _r(c.SPONSORED, 13, 2), _r(c.SPONSORED, 1, 3)])
    assert out.kind == "decide" and out.binding.position == 13 and out.counted == 3


def test_a_store_without_our_ad_binds_over_ones_that_have_it():
    absent = c.Reading(_store(2), c.ELIGIBLE, c.ABSENT, c.absent_position(48), 48)
    out = c.aggregate([_r(c.SPONSORED, 5, 1), absent])
    assert out.binding is absent and out.binding.position == 49


def test_absent_with_unknown_stock_still_counts_so_a_climb_is_never_stopped():
    # The worry that shaped this module: a new automation, not on the page yet, no stock
    # information. It must bid up, not be read as sold out.
    absent = c.Reading(_store(1), c.UNKNOWN, c.ABSENT, c.absent_position(48), 48)
    out = c.aggregate([absent])
    assert out.kind == "decide" and out.binding is absent


def test_ties_are_attributed_to_the_lower_rank():
    out = c.aggregate([_r(c.SPONSORED, 5, 3), _r(c.SPONSORED, 5, 1), _r(c.SPONSORED, 5, 2)])
    assert out.binding.store.rank == 1


def test_excluded_stores_leave_the_decision_to_the_rest():
    out = c.aggregate([_r(c.SKIPPED, rank=1, elig=c.OUT_OF_STOCK), _r(c.SPONSORED, 5, 2)])
    assert out.kind == "decide" and out.binding.store.rank == 2
    assert out.counted == 1 and out.excluded == 1


def test_every_store_excluded_is_a_stock_problem_not_a_bid():
    out = c.aggregate([_r(c.SKIPPED, rank=1, elig=c.OUT_OF_STOCK),
                       _r(c.SKIPPED, rank=2, elig=c.NOT_LISTED)])
    assert out.kind == "no_stock" and out.binding is None and out.excluded == 2


def test_nothing_readable_is_an_error_not_a_stock_problem():
    assert c.aggregate([_r(c.ERROR, rank=1)]).kind == "error"
    # Excluded + failed with nothing counted: we could not look where it mattered.
    assert c.aggregate([_r(c.SKIPPED, rank=1, elig=c.OUT_OF_STOCK),
                        _r(c.ERROR, rank=2)]).kind == "error"


def test_a_failed_store_does_not_block_the_ones_that_were_read():
    out = c.aggregate([_r(c.ERROR, rank=1), _r(c.SPONSORED, 9, 2)])
    assert out.kind == "decide" and out.binding.position == 9


def test_absent_position_is_just_below_the_page():
    assert c.absent_position(0) == 1.0 and c.absent_position(48) == 49.0


# ── Doubt: a reading we can't trust gets no vote this tick ────────────────────

def _unknown_absent(rank):
    return c.Reading(_store(rank), c.UNKNOWN, c.ABSENT, 49.0, 48)


def test_unknown_stock_and_not_showing_is_set_aside_when_another_store_is_clear():
    out = c.aggregate([_r(c.SPONSORED, 5, 1), _unknown_absent(2)])
    assert out.kind == "decide" and out.binding.store.rank == 1 and out.counted == 1
    assert out.readings[1].verdict == c.UNTRUSTED


def test_a_confirmed_store_not_showing_also_overrules_a_doubtful_one():
    confirmed = c.Reading(_store(1), c.ELIGIBLE, c.ABSENT, 49.0, 48)
    out = c.aggregate([confirmed, _unknown_absent(2)])
    assert out.binding.store.rank == 1 and out.readings[1].verdict == c.UNTRUSTED


def test_unknown_stock_and_not_showing_still_counts_when_it_is_all_we_know():
    # A new campaign, no stock readable yet, not on the page anywhere: it must still climb.
    out = c.aggregate([_unknown_absent(1), _unknown_absent(2)])
    assert out.kind == "decide" and out.counted == 2


def test_untrusted_and_given_up_readings_do_not_vote():
    out = c.aggregate([_r(c.UNTRUSTED, rank=1), _r(c.GAVE_UP, rank=2), _r(c.SPONSORED, 9, 3)])
    assert out.kind == "decide" and out.binding.store.rank == 3 and out.excluded == 2


def test_only_untrusted_readings_decide_nothing():
    assert c.aggregate([_r(c.UNTRUSTED, rank=1)]).kind == "error"


def test_every_counted_store_given_up_is_unwinnable():
    out = c.aggregate([_r(c.GAVE_UP, rank=1), _r(c.SKIPPED, rank=2, elig=c.OUT_OF_STOCK)])
    assert out.kind == "unwinnable"


def test_no_readings_at_all_is_an_error():
    assert c.aggregate([]).kind == "error"


# ── Giving up at the ceiling ─────────────────────────────────────────────────

OPEN = datetime(2026, 9, 17, 16, 0)


def _h(verdict, bid, minutes_after_open):
    return SimpleNamespace(verdict=verdict, bid=bid,
                           observed_at=OPEN + timedelta(minutes=minutes_after_open))


def _gave_up(history, ceiling=150, ticks=2):
    return c.gave_up(history, window_start=OPEN, ceiling=ceiling, ticks=ticks)


def test_gives_up_after_enough_checks_not_showing_at_the_ceiling():
    assert _gave_up([_h(c.ABSENT, 150, 45), _h(c.ABSENT, 150, 30)])


def test_a_check_below_the_ceiling_does_not_count_toward_giving_up():
    assert not _gave_up([_h(c.ABSENT, 150, 45), _h(c.ABSENT, 110, 30)])


def test_showing_at_the_ceiling_breaks_the_run():
    assert not _gave_up([_h(c.ABSENT, 150, 45), _h(c.SPONSORED, 150, 30)])


def test_checks_from_before_this_window_do_not_count():
    assert not _gave_up([_h(c.ABSENT, 150, 15), _h(c.ABSENT, 150, -600)])


def test_giving_up_sticks_for_the_rest_of_the_window():
    assert _gave_up([_h(c.GAVE_UP, 150, 60)])


def test_raising_the_ceiling_lifts_a_give_up():
    history = [_h(c.GAVE_UP, 150, 60), _h(c.ABSENT, 150, 45), _h(c.ABSENT, 150, 30)]
    assert not _gave_up(history, ceiling=200)


def test_zero_ticks_disables_giving_up():
    assert not _gave_up([_h(c.ABSENT, 150, m) for m in (60, 45, 30)], ticks=0)


# ── Problem streaks ──────────────────────────────────────────────────────────

def test_a_usable_reading_has_no_problem_streak():
    assert c.unusable_streak([_h(c.ERROR, 1, 0)], c.SPONSORED) == 0


def test_the_streak_counts_this_check_and_the_unbroken_run_before_it():
    history = [_h(c.UNTRUSTED, 1, 30), _h(c.ERROR, 1, 15), _h(c.SPONSORED, 1, 0),
               _h(c.ERROR, 1, -15)]
    assert c.unusable_streak(history, c.ERROR) == 3


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
    print(f"\n{len(tests) - failed}/{len(tests)} coverage tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
