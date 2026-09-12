"""`window.previous_close` — when did this window LAST close? Pure: no DB, no marketplace.

`last_window_close` answers "when does it close for the last time", which is a question about
an automation's life. This is the other one: "when did it last close", which is what an
end-of-window action has to ask when it may have been missed. The budget engine's failsafe
(`lifecycle.revert_owed`) is built on it — between windows the engine does nothing, so the
only thing standing between a missed 02:00 revert and a campaign spending the night at its
raised budget is this answer.

    python -m campaign_manager.tests.test_previous_close
"""
from datetime import datetime

from campaign_manager import lifecycle, window

DAILY = window.Window(type="recurring", days=[], start_time="19:30", end_time="02:00")
WEEKDAYS = window.Window(type="recurring", days=["friday", "saturday", "sunday"],
                         start_time="19:30", end_time="02:00")
DAYTIME = window.Window(type="recurring", days=[], start_time="09:00", end_time="12:00")
ONCE = window.Window(type="once", date="2026-09-07", start_time="16:00", end_time="23:00")
DATED = window.Window(type="recurring", days=[], start_time="09:00", end_time="12:00",
                      start_date="2026-09-07", end_date="2026-09-09")

# Saturday 2026-09-12. The 19:30–02:00 window that opened on Friday closed at 02:00 today.
SAT_MORNING = datetime(2026, 9, 12, 10, 0)


def test_an_overnight_window_is_found_at_its_close_not_its_start():
    assert window.previous_close(DAILY, SAT_MORNING) == datetime(2026, 9, 12, 2, 0)


def test_a_window_open_right_now_has_not_closed_yet():
    """21:00 on Saturday: tonight's window is open, so the last CLOSE is this morning's."""
    assert window.previous_close(DAILY, datetime(2026, 9, 12, 21, 0)) == \
        datetime(2026, 9, 12, 2, 0)


def test_the_close_is_returned_the_instant_it_happens():
    assert window.previous_close(DAILY, datetime(2026, 9, 12, 2, 0)) == \
        datetime(2026, 9, 12, 2, 0)


def test_a_weekday_filter_skips_to_the_last_eligible_day():
    """Tuesday: Fri/Sat/Sun, so the last close was Monday 02:00 (Sunday's window)."""
    assert window.previous_close(WEEKDAYS, datetime(2026, 9, 15, 10, 0)) == \
        datetime(2026, 9, 14, 2, 0)


def test_a_daytime_window_closes_on_its_own_day():
    assert window.previous_close(DAYTIME, SAT_MORNING) == datetime(2026, 9, 11, 12, 0)
    assert window.previous_close(DAYTIME, datetime(2026, 9, 12, 13, 0)) == \
        datetime(2026, 9, 12, 12, 0)


def test_a_window_that_has_never_opened_has_no_previous_close():
    future = window.Window(type="once", date="2099-01-01", start_time="10:00", end_time="12:00")
    assert window.previous_close(future, SAT_MORNING) is None
    assert window.previous_close(DAILY, datetime(2026, 9, 12, 1, 0)) is not None  # sanity


def test_a_once_rule_from_long_ago_still_reports_its_one_close():
    """Older than the scan window, so it comes from `last_window_close` instead — the failsafe
    must not read "never closed" and leave an ended automation raised."""
    assert window.previous_close(ONCE, datetime(2026, 10, 1)) == datetime(2026, 9, 7, 23, 0)


def test_a_dated_range_stops_closing_after_its_end_date():
    assert window.previous_close(DATED, datetime(2026, 9, 20)) == datetime(2026, 9, 9, 12, 0)


def test_a_schedule_takes_the_latest_close_of_all_its_rules():
    assert window.schedule_previous_close([DAILY, DAYTIME], SAT_MORNING) == \
        datetime(2026, 9, 12, 2, 0)
    assert window.schedule_previous_close([], SAT_MORNING) is None


# ── what the failsafe does with it ──────────────────────────────────────────

CREATED = datetime(2026, 1, 1)


def _owed(close, *, settled_at=None, created_at=CREATED, now=SAT_MORNING):
    return lifecycle.revert_owed(close, created_at, settled_at, now)


def test_a_close_with_no_stamp_is_owed_a_revert():
    assert _owed(datetime(2026, 9, 12, 2, 0)) is True


def test_a_stamp_at_or_after_the_close_latches_it():
    close = datetime(2026, 9, 12, 2, 0)
    assert _owed(close, settled_at=close) is False
    assert _owed(close, settled_at=datetime(2026, 9, 12, 2, 30)) is False
    assert _owed(close, settled_at=datetime(2026, 9, 11, 2, 0)) is True   # the night before


def test_a_close_older_than_a_day_is_not_repaired():
    assert _owed(datetime(2026, 9, 10, 2, 0)) is False


def test_a_close_from_before_the_schedule_existed_is_not_owed():
    close = datetime(2026, 9, 12, 2, 0)
    assert _owed(close, created_at=datetime(2026, 9, 12, 9, 0)) is False
    assert _owed(close, created_at=datetime(2026, 9, 12, 1, 0)) is True


def test_nothing_is_owed_when_there_is_no_close():
    assert _owed(None) is False
    assert _owed(datetime.min) is False


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
    print(f"\n{len(tests) - failed}/{len(tests)} previous-close tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
