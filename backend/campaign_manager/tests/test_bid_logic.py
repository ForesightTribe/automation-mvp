"""Unit tests for the bid-optimizer decision logic — pure, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_bid_logic

Covers the distance step, the raise/lower/target/HOLD decision, the active window, and
the Blinkit product-matching (positions.match_position).
"""
from datetime import datetime

from campaign_manager.bid import (
    HOLD_MINUTES, _dynamic_step, _in_window, _window_start, compute_bid, is_recovery,
    should_relax_target, stored_effective_target,
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


# ── drift-down (cost minimisation at target) ─────────────────────────────────
#
# DRIFT is the keyword-only knob; at 0 (the default) every test above still describes the
# behaviour, which is the point of the kill switch.
DRIFT = {"drift_pct": 7, "drift_min_step": 5}


def test_drift_off_by_default_keeps_the_old_freeze():
    """The kill switch must be a TRUE revert, not a half-disabled state."""
    assert compute_bid(3, 3, 400, 100, 900, 3, 30)[0] is None
    assert compute_bid(1, 3, 400, 100, 900, 1, 30)[0] == 375     # legacy 'lower' still steps


def test_drift_shaves_a_percentage_when_holding():
    new, reason = compute_bid(3, 3, 400, 100, 900, 3, 30, **DRIFT)
    assert new == 372 and reason.startswith("drift")             # 400 - 7% = 372


def test_drift_treats_better_than_target_as_holding():
    """Sponsored slots sit on a sparse lattice, so pos 1 with target 3 is a SUCCESS —
    the cheapest way to satisfy 'at least as good as 3', not an error to correct."""
    new, reason = compute_bid(1, 3, 400, 100, 900, 1, 30, **DRIFT)
    assert new == 372 and reason.startswith("drift")


def test_drift_needs_two_consecutive_holds():
    """One reading was unreliable ~28% of the time in the v1 log — never spend a write on
    a single observation, and give a fresh raise one tick to prove itself."""
    new, reason = compute_bid(3, 3, 400, 100, 900, 9, 30, **DRIFT)   # last tick was OFF target
    assert new is None and "second confirmation" in reason


def test_drift_respects_the_pause():
    new, reason = compute_bid(3, 3, 400, 100, 900, 3, 30, drift_paused=True, **DRIFT)
    assert new is None and "paused" in reason


def test_min_step_floors_a_tiny_percentage():
    new, _ = compute_bid(3, 3, 50, 10, 900, 3, 30, **DRIFT)      # 7% of 50 = 3.5 → floor 5
    assert new == 45


def test_drift_never_goes_below_min_bid():
    new, _ = compute_bid(3, 3, 105, 100, 900, 3, 30, **DRIFT)
    assert new == 100


def test_drift_stops_once_sitting_on_min_bid():
    new, reason = compute_bid(3, 3, 100, 100, 900, 3, 30, **DRIFT)
    assert new is None and "already at min_bid" in reason


# ── recovery (our own drift overshot) vs a competitor outbidding us ──────────

def test_recovery_snaps_back_to_the_last_holding_bid():
    """A _dynamic_step raise from 299 would jump to 399 and overshoot the known-good 322
    by ₹77, which we would then spend an hour drifting back off."""
    new, reason = compute_bid(9, 3, 299, 100, 900, 1, 30, last_holding_cpm=322, **DRIFT)
    assert new == 322 and reason.startswith("recover")


def test_market_moving_against_us_is_a_normal_raise_not_a_recovery():
    """Off target AT the last holding bid = a competitor moved, not our overshoot. The
    snap-back would be a no-op, so it must fall through to the raise ladder."""
    new, reason = compute_bid(9, 3, 322, 100, 900, 1, 30, last_holding_cpm=322, **DRIFT)
    assert new == 422 and reason.startswith("raise")             # distance 6 → step 100


def test_is_recovery_predicate():
    assert is_recovery(9, 3, 299, 322) is True
    assert is_recovery(9, 3, 322, 322) is False                  # not below the holding bid
    assert is_recovery(9, 3, 400, 322) is False                  # above it — market moved
    assert is_recovery(1, 3, 299, 322) is False                  # still holding
    assert is_recovery(9, 3, 299, None) is False                 # never held yet


def test_pause_never_blocks_a_raise():
    """The pause is a ONE-WAY valve. Peak hours: a competitor outbids us mid-pause and we
    must answer on the very next tick, or we sit off-target for 90 minutes."""
    new, reason = compute_bid(9, 3, 322, 100, 900, 1, 30,
                              last_holding_cpm=322, drift_paused=True, **DRIFT)
    assert new == 422 and reason.startswith("raise")


def test_reflection_hold_still_applies_with_drift_on():
    new, reason = compute_bid(9, 3, 400, 100, 900, 9, 2, **DRIFT)
    assert new is None and reason.startswith("hold")


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


# ── unreachable target (relax to what the ceiling can buy) ───────────────────

def test_relax_when_pinned_at_max_and_missing_twice():
    """Target 1, ceiling ₹900, and ₹900 only ever reaches position 5."""
    assert should_relax_target(5, 1, 900, 900, last_position=5) is True


def test_no_relax_on_a_single_bad_reading():
    """One scrape was unreliable ~28% of the time in the v1 log — relaxing the target for
    the rest of the window on one of those would be expensive to undo."""
    assert should_relax_target(5, 1, 900, 900, last_position=1) is False
    assert should_relax_target(5, 1, 900, 900, last_position=None) is False


def test_no_relax_while_there_is_still_room_to_climb():
    """Below the ceiling the raise still has somewhere to go — giving up early would settle
    for a worse position that a higher bid could have bought."""
    assert should_relax_target(5, 1, 400, 900, last_position=5) is False


def test_no_relax_when_the_target_is_being_met():
    assert should_relax_target(1, 1, 900, 900, last_position=1) is False
    assert should_relax_target(1, 3, 900, 900, last_position=1) is False


def test_relax_when_bid_somehow_exceeds_max():
    """`>=`, not `==` — a bid can sit above the ceiling after max_bid is lowered."""
    assert should_relax_target(5, 1, 950, 900, last_position=5) is True


def test_stored_relaxed_target_is_used_while_the_ceiling_matches():
    assert stored_effective_target(1, 900, 5, 900) == 5


def test_raising_max_bid_voids_the_relaxed_target():
    """The dangerous direction: with the old target still in force, being handed MORE room
    to climb would make the optimizer keep drifting DOWN instead."""
    assert stored_effective_target(1, 1500, 5, 900) is None


def test_lowering_max_bid_voids_the_relaxed_target():
    assert stored_effective_target(1, 400, 5, 900) is None


def test_relaxed_target_ignored_when_not_worse_than_the_real_one():
    """A relaxed target equal to or better than the rule's is meaningless — chase the real
    one. Covers a target_position edit that moved the goal past the stored value."""
    assert stored_effective_target(5, 900, 5, 900) is None
    assert stored_effective_target(9, 900, 5, 900) is None


def test_no_relaxed_target_when_unset():
    assert stored_effective_target(1, 900, None, None) is None
    assert stored_effective_target(1, 900, 5, None) is None
    assert stored_effective_target(1, 900, None, 900) is None


def test_relaxed_target_makes_the_achieved_position_count_as_held():
    """The point of relaxing: at position 5 against a relaxed target of 5, drift takes over
    and starts cutting cost, instead of recomputing max_bid forever."""
    new, reason = compute_bid(5, 5, 900, 100, 900, 5, 30, drift_pct=7, drift_min_step=5)
    assert new == 837 and reason.startswith("drift")


def test_without_relaxing_a_pinned_bid_just_recomputes_the_ceiling():
    """Today's behaviour, kept as the contrast: the raise clamps to max_bid, the no-op
    guardrail rejects it, and nothing changes — every 15 minutes, all day."""
    new, _ = compute_bid(5, 1, 900, 100, 900, 5, 30)
    assert new == 900


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
