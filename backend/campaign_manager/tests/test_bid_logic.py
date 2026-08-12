"""Unit tests for the bid-optimizer decision logic — pure, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_bid_logic

Covers the distance step, the raise/lower/target/HOLD decision, the active window, and
the Blinkit product-matching (positions.match_position).
"""
from datetime import datetime

from campaign_manager.bid import (
    HOLD_MINUTES, _dynamic_step, _in_window, _window_start, compute_bid,
)
from campaign_manager.marketplaces.blinkit.positions import match_position

NOW = datetime(2026, 8, 1, 14, 0)   # 14:00 on 2026-08-01


# ── step ─────────────────────────────────────────────────────────────────────

def test_dynamic_step_tiers():
    assert _dynamic_step(5) == 100 and _dynamic_step(4) == 100
    assert _dynamic_step(3.5) == 50 and _dynamic_step(3) == 50
    assert _dynamic_step(2) == 25 and _dynamic_step(1) == 25
    assert _dynamic_step(0.5) == 12.5 and _dynamic_step(0) == 12.5


# ── compute_bid ──────────────────────────────────────────────────────────────

def test_at_target_no_change():
    new, reason = compute_bid(3, 3, 50, 10, 200, None, None)
    assert new is None and reason.startswith("target")


def test_below_target_raises():
    # pos 6 > target 3 → distance 3 → step 50 → 50 + 50 = 100
    new, _ = compute_bid(6, 3, 50, 10, 200, None, None)
    assert new == 100


def test_raise_clamped_to_max():
    new, _ = compute_bid(6, 3, 190, 10, 200, None, None)   # 190 + 50 = 240 → clamp 200
    assert new == 200


def test_above_target_lowers():
    # pos 1 < target 3 → distance 2 → step 25 → 100 - 25 = 75
    new, _ = compute_bid(1, 3, 100, 10, 200, None, None)
    assert new == 75


def test_lower_clamped_to_min():
    new, _ = compute_bid(1, 3, 20, 10, 200, None, None)    # 20 - 25 = -5 → clamp 10
    assert new == 10


def test_hold_when_no_improvement_inside_window():
    # pos didn't improve (6 >= last 6) and only 5min < 10min → HOLD, no change
    new, reason = compute_bid(6, 3, 50, 10, 200, last_position=6, minutes_since_change=5)
    assert new is None and reason.startswith("hold")


def test_no_hold_when_improved():
    # pos improved (6 < last 8) → not a hold, raise even though recent
    new, _ = compute_bid(6, 3, 50, 10, 200, last_position=8, minutes_since_change=5)
    assert new == 100


def test_no_hold_after_reflection_window():
    new, _ = compute_bid(6, 3, 50, 10, 200, last_position=6, minutes_since_change=HOLD_MINUTES + 1)
    assert new == 100                                       # waited long enough → raise


def test_no_hold_when_never_changed():
    new, _ = compute_bid(6, 3, 50, 10, 200, last_position=6, minutes_since_change=None)
    assert new == 100                                       # no last change → not held


# ── _in_window ───────────────────────────────────────────────────────────────

def test_in_window_true():
    assert _in_window({"start_time": "09:00", "stop_time": "20:00"}, NOW) is True


def test_in_window_outside_time():
    assert _in_window({"start_time": "09:00", "stop_time": "12:00"}, NOW) is False   # 14:00 > 12:00


def test_in_window_date_bounds():
    assert _in_window({"start_date": "2099-01-01"}, NOW) is False      # not started
    assert _in_window({"stop_date": "2000-01-01"}, NOW) is False       # already ended
    assert _in_window({}, NOW) is True                                 # no constraints


def test_in_window_overnight():
    r = {"start_time": "18:00", "stop_time": "02:00"}                  # crosses midnight
    assert _in_window(r, NOW.replace(hour=20)) is True                 # 20:00 → active
    assert _in_window(r, NOW.replace(hour=1)) is True                  # 01:00 → active
    assert _in_window(r, NOW.replace(hour=12)) is False                # 12:00 → inactive


def test_in_window_once_matches_only_its_date():
    r = {"type": "once", "date": "2026-08-01", "start_time": "09:00", "stop_time": "20:00"}
    assert _in_window(r, NOW) is True                                  # NOW = 2026-08-01 14:00
    other = {"type": "once", "date": "2026-08-02", "start_time": "09:00", "stop_time": "20:00"}
    assert _in_window(other, NOW) is False                             # wrong day


def test_in_window_once_overnight_next_day_tail():
    r = {"type": "once", "date": "2026-07-31", "start_time": "18:00", "stop_time": "02:00"}
    assert _in_window(r, NOW.replace(hour=1)) is True                  # 08-01 01:00 → the next-day tail
    assert _in_window(r, NOW) is False                                 # 08-01 14:00 → tail already over


# Explicit weekday anchors: 2026-07-29 Wed, 07-31 Fri, 08-02 Sun, 08-03 Mon.
def test_in_window_days_filter():
    r = {"type": "recurring", "days": ["friday", "saturday", "sunday"],
         "start_time": "16:00", "stop_time": "02:00"}
    assert _in_window(r, datetime(2026, 7, 31, 18, 0)) is True         # Friday evening
    assert _in_window(r, datetime(2026, 7, 29, 18, 0)) is False        # Wednesday — not a match day


def test_in_window_overnight_tail_start_day():
    r = {"type": "recurring", "days": ["friday", "saturday", "sunday"],
         "start_time": "16:00", "stop_time": "02:00"}
    assert _in_window(r, datetime(2026, 8, 3, 1, 0)) is True           # Mon 01:00 = Sunday's tail
    assert _in_window(r, datetime(2026, 7, 31, 1, 0)) is False         # Fri 01:00 = Thursday's tail (off)


# ── match_position (Blinkit) ─────────────────────────────────────────────────

def test_match_sponsored_by_pid():
    results = [{"position": 2, "name": "Something", "is_ad": True, "pid": "999"}]
    assert match_position(results, product_names=[], product_pids=["999"]) == (2.0, True, True)


def test_match_sponsored_by_name():
    results = [{"position": 4, "name": "Dobra Goli Soda 200ml", "is_ad": True, "pid": "1"}]
    pos, is_ad, found = match_position(results, product_names=["Dobra Masala"], product_pids=[])
    assert pos == 4.0 and is_ad and found                  # "dobra" token matches


def test_match_organic_only_skips():
    results = [{"position": 3, "name": "Dobra Goli Soda", "is_ad": False, "pid": "1"}]
    assert match_position(results, product_names=["Dobra"], product_pids=["1"]) == (None, False, True)


def test_match_not_found():
    results = [{"position": 1, "name": "Some Other Brand", "is_ad": True, "pid": "5"}]
    assert match_position(results, product_names=["Dobra"], product_pids=["9"]) == (None, False, False)


def test_match_empty_results():
    assert match_position([], product_names=["Dobra"], product_pids=["1"]) == (None, False, False)


# ── End-of-window reset timing (A4) ─────────────────────────────────────
#
# The reconciler fires the reset one minute EARLY so it beats the budget engine (a
# parallel lane) to the campaign. That only works because `_reset_run` evaluates windows
# with a LOOK-AHEAD: at 22:59 the window is still open, so without it the run would find
# nothing to reset and the early fire would be a silent no-op.

def test_window_is_still_open_at_the_early_fire_time():
    rule = {"type": "recurring", "start_time": "19:00", "stop_time": "23:00", "days": []}
    assert _in_window(rule, datetime(2026, 8, 7, 22, 59)) is True


def test_lookahead_makes_the_early_fire_see_the_window_as_closed():
    from datetime import timedelta

    from campaign_manager.bid import RESET_LOOKAHEAD_MINUTES

    rule = {"type": "recurring", "start_time": "19:00", "stop_time": "23:00", "days": []}
    fired_at = datetime(2026, 8, 7, 22, 59)
    assert _in_window(rule, fired_at + timedelta(minutes=RESET_LOOKAHEAD_MINUTES)) is False
    # ...and the lookahead must exceed the reconciler's lead, or setup drift lands the run
    # back inside the window.
    from campaign_manager.reconciler import _RESET_LEAD_MINUTES
    assert RESET_LOOKAHEAD_MINUTES > _RESET_LEAD_MINUTES


def test_overnight_window_is_closed_AT_its_stop_time():
    """Same inclusive/exclusive fix as budget: an 18:00–02:00 rule must NOT still be
    'in window' at 02:00, or the reset would skip the keyword it fired for."""
    rule = {"type": "recurring", "start_time": "18:00", "stop_time": "02:00", "days": []}
    assert _in_window(rule, datetime(2026, 8, 8, 1, 59)) is True
    assert _in_window(rule, datetime(2026, 8, 8, 2, 0)) is False


# ── _window_start (the "first fire of this window" anchor) ───────────────────

def test_window_start_is_todays_start_time():
    rule = {"type": "recurring", "start_time": "09:00", "stop_time": "21:00", "days": []}
    assert _window_start(rule, datetime(2026, 8, 12, 14, 30)) == datetime(2026, 8, 12, 9, 0)


def test_window_start_at_the_very_first_fire():
    """The opening tick itself must anchor to its own window, not the previous one —
    otherwise `updated_at >= window_start` is true from the start and the floor is skipped."""
    rule = {"type": "recurring", "start_time": "09:00", "stop_time": "21:00", "days": []}
    assert _window_start(rule, datetime(2026, 8, 12, 9, 0)) == datetime(2026, 8, 12, 9, 0)


def test_window_start_overnight_tail_belongs_to_the_day_it_started():
    """An 18:00–02:00 window is ONE window. At 01:00 it must report yesterday 18:00, or
    midnight would look like a new window and re-floor a bid mid-flight."""
    rule = {"type": "recurring", "start_time": "18:00", "stop_time": "02:00", "days": []}
    assert _window_start(rule, datetime(2026, 8, 12, 1, 0)) == datetime(2026, 8, 11, 18, 0)
    assert _window_start(rule, datetime(2026, 8, 12, 19, 0)) == datetime(2026, 8, 12, 18, 0)


def test_window_start_no_start_time_is_midnight():
    rule = {"type": "recurring", "start_time": None, "stop_time": "21:00", "days": []}
    assert _window_start(rule, datetime(2026, 8, 12, 14, 0)) == datetime(2026, 8, 12, 0, 0)


def test_window_start_seconds_are_stripped():
    """It is compared against a DB timestamp, so a stray second would make the boundary
    tick's comparison flip depending on when in the minute the runner fired."""
    rule = {"type": "recurring", "start_time": "09:00", "stop_time": "21:00", "days": []}
    ws = _window_start(rule, datetime(2026, 8, 12, 14, 30, 47, 123456))
    assert ws.second == 0 and ws.microsecond == 0


def test_yesterdays_runtime_does_not_count_as_this_window_opened():
    """The whole point: a run that last touched the rule during YESTERDAY's window must
    read as 'not opened', so today re-establishes the floor."""
    rule = {"type": "recurring", "start_time": "09:00", "stop_time": "21:00", "days": []}
    now = datetime(2026, 8, 12, 9, 0)
    yesterday_evening = datetime(2026, 8, 11, 20, 45)
    assert yesterday_evening < _window_start(rule, now)


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
    print(f"\n{len(tests) - failed}/{len(tests)} bid-logic tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
