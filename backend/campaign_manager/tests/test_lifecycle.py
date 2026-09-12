"""The settle-once lifecycle — what an automation's end means. Pure: no DB, no marketplace.

`needs_settle` decides whether an engine tears an ended automation down again; the sweep
(`marker_changes`) decides what the reconciler writes. Both are exercised against the two
real 2026-09-09 incidents and the migration's backfill.

    python -m campaign_manager.tests.test_lifecycle
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from campaign_manager import config, lifecycle, window

CLOSE = datetime(2026, 9, 7, 23, 0)          # a one-time 16:00–23:00 window on 2026-09-07
AFTER = CLOSE + timedelta(hours=2)
MIGRATED = datetime(2026, 9, 10, 17, 0)      # the backfill stamp every existing row gets


def _bid(**kw) -> SimpleNamespace:
    return SimpleNamespace(**{"state": "active", "type": "once", "date": "2026-09-07",
                              "days": [], "start_date": None, "stop_date": None,
                              "start_time": "16:00", "stop_time": "23:00", **kw})


def _settles(**kw) -> bool:
    return lifecycle.needs_settle(**{"close": CLOSE, "state": "active", "settled_at": None,
                                     "attempts": 0, "now": AFTER, **kw})


# ── needs_settle ─────────────────────────────────────────────────────────────

def test_an_ended_automation_whose_teardown_never_landed_settles():
    assert _settles() is True


def test_nothing_settles_before_it_has_ended():
    assert _settles(now=CLOSE - timedelta(minutes=1)) is False
    assert _settles(close=None) is False                       # no last window at all


def test_only_an_active_automation_settles():
    """Paused means no writes, and a stopped budget schedule has been handed back by Reset —
    the user's choice outranks the calendar."""
    assert _settles(state="paused") is False
    assert _settles(state="stopped") is False


def test_an_automation_that_never_opened_has_nothing_to_tear_down():
    assert _settles(close=datetime.min) is False


def test_a_latch_covers_the_ending_it_was_written_for():
    assert _settles(settled_at=CLOSE) is False
    assert _settles(settled_at=CLOSE + timedelta(minutes=5)) is False


def test_a_latch_from_an_earlier_ending_does_not_cover_a_later_one():
    """Why reopening needs no unlatching: dates moved forward after it settled once, and the
    next ending is later than that latch."""
    assert _settles(settled_at=CLOSE - timedelta(days=3)) is True


def test_settling_gives_up_after_its_attempts():
    assert _settles(attempts=config.SETTLE_MAX_ATTEMPTS - 1) is True
    assert _settles(attempts=config.SETTLE_MAX_ATTEMPTS) is False


def test_settling_stops_once_a_person_has_had_time_to_take_over():
    limit = timedelta(hours=config.SETTLE_MAX_AGE_HOURS)
    assert _settles(now=CLOSE + limit) is True
    assert _settles(now=CLOSE + limit + timedelta(minutes=1)) is False


def test_the_backfill_settles_every_ending_that_had_already_happened():
    """Campaign 637511: its automation's only window closed 2026-09-07 23:00 and the campaign
    was restarted by hand on 2026-09-09. With the migration's stamp it is settled — so nothing
    stops it again. An ending AFTER the migration is still covered."""
    assert lifecycle.needs_settle(CLOSE, "active", MIGRATED, 0, MIGRATED + timedelta(hours=1)) is False
    later = datetime(2026, 9, 12, 21, 0)
    assert lifecycle.needs_settle(later, "active", MIGRATED, 0, later + timedelta(hours=1)) is True


# ── closes, stamps, ended_at ─────────────────────────────────────────────────

def test_the_stamp_is_never_earlier_than_the_close_it_settles():
    assert lifecycle.settle_stamp(CLOSE, CLOSE - timedelta(minutes=1)) == CLOSE
    assert lifecycle.settle_stamp(CLOSE, AFTER) == AFTER
    assert lifecycle.settle_stamp(None, AFTER) == AFTER
    assert lifecycle.settle_stamp(datetime.min, AFTER) == AFTER


def test_a_schedule_closes_with_its_last_window():
    first = window.Window(type="once", date="2026-09-07", start_time="10:00", end_time="12:00")
    last = window.Window(type="once", date="2026-09-08", start_time="10:00", end_time="12:00")
    forever = window.Window(start_time="10:00", end_time="12:00")
    assert lifecycle.schedule_close([first, last]) == datetime(2026, 9, 8, 12, 0)
    assert lifecycle.schedule_close([first, forever]) is None
    assert lifecycle.schedule_close([]) is None                # default-only: never ends


def test_ended_at_is_the_close_or_the_creation_of_one_that_never_opened():
    created = datetime(2026, 9, 1, 12, 0)
    assert lifecycle.ended_at(CLOSE, created, CLOSE - timedelta(minutes=1)) is None
    assert lifecycle.ended_at(CLOSE, created, AFTER) == CLOSE
    assert lifecycle.ended_at(datetime.min, created, AFTER) == created
    assert lifecycle.ended_at(None, created, AFTER) is None


# ── the reconciler's sweep ───────────────────────────────────────────────────

def test_the_sweep_writes_nothing_for_a_live_automation():
    assert lifecycle.bid_rule_markers(_bid(date="2026-09-20"), AFTER) == {}


def test_the_sweep_records_an_ending_once():
    rule = _bid(created_at=datetime(2026, 9, 1))
    assert lifecycle.bid_rule_markers(rule, AFTER) == {"ended_at": CLOSE}
    rule.ended_at = CLOSE
    assert lifecycle.bid_rule_markers(rule, AFTER) == {}      # idempotent


def test_the_sweep_leaves_a_landed_teardown_alone():
    rule = _bid(ended_at=CLOSE, settled_at=CLOSE, settle_attempts=0)
    assert lifecycle.bid_rule_markers(rule, AFTER) == {}


def test_reopening_clears_the_ending_and_its_attempts_but_keeps_the_stamp():
    """Its date moved forward after it ended, had settled once, and had given up once.

    The stamp stays: it records the most recent close that WAS torn down, and every reader
    compares it against the close it is asking about — an old stamp is automatically not a
    latch on the new ending. Clearing it used to be the rule, and it would now re-arm a
    revert the budget engine had already made (`lifecycle.revert_owed`)."""
    rule = _bid(date="2026-09-20", ended_at=CLOSE, settled_at=CLOSE, settle_attempts=3)
    assert lifecycle.bid_rule_markers(rule, AFTER) == {"ended_at": None, "settle_attempts": 0}
    assert lifecycle.needs_settle(close=datetime(2026, 9, 20, 23, 0), state="active",
                                  settled_at=CLOSE, attempts=0,
                                  now=datetime(2026, 9, 20, 23, 1)) is True


def test_the_backfilled_stamp_survives_on_automations_that_have_not_ended():
    rule = _bid(date="2026-09-20", settled_at=MIGRATED)
    assert lifecycle.bid_rule_markers(rule, AFTER) == {}


def test_a_latch_stamped_a_minute_before_its_close_survives_the_sweep():
    """The end-of-window reset fires a minute before the stop and stamps the close it tears
    down. A reconcile landing inside that minute must not throw the latch away."""
    rule = _bid(settled_at=CLOSE)
    assert lifecycle.bid_rule_markers(rule, CLOSE - timedelta(seconds=30)) == {}


def test_a_budget_schedule_is_swept_on_its_last_window():
    schedule = SimpleNamespace(state="active", created_at=datetime(2026, 9, 1))
    rules = [SimpleNamespace(type="once", date="2026-09-07", days=[], time_slots=[],
                             start_date=None, end_date=None, start_time="16:00",
                             end_time="23:00")]
    assert lifecycle.schedule_markers(schedule, rules, AFTER) == {"ended_at": CLOSE}
    assert lifecycle.schedule_needs_settle(schedule, rules, AFTER) is True
    schedule.settled_at = CLOSE
    assert lifecycle.schedule_needs_settle(schedule, rules, AFTER) is False


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
    print(f"\n{len(tests) - failed}/{len(tests)} lifecycle tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
