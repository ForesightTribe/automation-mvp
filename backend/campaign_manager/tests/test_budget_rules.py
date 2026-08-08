"""Unit tests for budget rule-matching (V1) — pure logic, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_budget_rules

Uses a fixed reference time and derives the weekday from it, so the tests are
independent of the real calendar.
"""
from datetime import datetime, timedelta

from campaign_manager.budget import _window_just_ended, plan_for_now, target_for_now

# Reference: 2pm on some day. Derive names so tests don't hardcode a weekday.
NOW = datetime(2026, 8, 1, 14, 0)
TODAY = NOW.strftime("%Y-%m-%d")
DAY = NOW.strftime("%A").lower()
OTHER_DAY = (NOW + timedelta(days=1)).strftime("%A").lower()


def test_recurring_day_and_time_matches():
    rule = {"type": "recurring", "days": [DAY], "start_time": "12:00", "end_time": "18:00", "budget": 2000}
    target, _ = target_for_now(500, [rule], NOW)
    assert target == 2000


def test_no_rule_matches_returns_default():
    rule = {"type": "recurring", "days": [OTHER_DAY], "start_time": "12:00", "end_time": "18:00", "budget": 2000}
    target, reason = target_for_now(500, [rule], NOW)
    assert target == 500 and "default" in reason


def test_outside_time_range_falls_to_default():
    rule = {"type": "recurring", "days": [DAY], "start_time": "06:00", "end_time": "12:00", "budget": 2000}
    target, _ = target_for_now(500, [rule], NOW)  # 14:00 is not in 06:00–12:00
    assert target == 500


def test_time_slots():
    hit = {"type": "recurring", "days": [], "time_slots": ["afternoon"], "budget": 2000}
    miss = {"type": "recurring", "days": [], "time_slots": ["morning"], "budget": 2000}
    assert target_for_now(500, [hit], NOW)[0] == 2000   # 14:00 = afternoon
    assert target_for_now(500, [miss], NOW)[0] == 500


def test_date_range():
    future = {"type": "recurring", "days": [], "start_date": "2099-01-01", "budget": 2000}
    within = {"type": "recurring", "days": [], "start_date": "2000-01-01", "end_date": "2099-01-01", "budget": 2000}
    assert target_for_now(500, [future], NOW)[0] == 500   # today < start_date
    assert target_for_now(500, [within], NOW)[0] == 2000


def test_midnight_crossing():
    rule = {"type": "recurring", "days": [DAY], "start_time": "22:00", "end_time": "02:00", "budget": 2000}
    assert target_for_now(500, [rule], NOW)[0] == 500                       # 14:00 → inactive
    late = NOW.replace(hour=23)
    assert target_for_now(500, [rule], late)[0] == 2000                     # 23:00 → active


def test_once_on_and_off_date():
    on = {"type": "once", "date": TODAY, "start_time": "12:00", "end_time": "18:00", "budget": 3000}
    off = {"type": "once", "date": "2099-12-31", "budget": 3000}
    assert target_for_now(500, [on], NOW)[0] == 3000
    assert target_for_now(500, [off], NOW)[0] == 500


def test_first_matching_rule_wins():
    rules = [
        {"type": "recurring", "days": [DAY], "start_time": "12:00", "end_time": "18:00", "budget": 2000},
        {"type": "recurring", "days": [DAY], "start_time": "12:00", "end_time": "18:00", "budget": 9999},
    ]
    assert target_for_now(500, rules, NOW)[0] == 2000


def test_empty_days_is_every_day():
    rule = {"type": "recurring", "days": [], "start_time": "12:00", "end_time": "18:00", "budget": 2000}
    assert target_for_now(500, [rule], NOW)[0] == 2000


# Explicit weekday anchors: 2026-07-30 Thu, 07-31 Fri, 08-01 Sat, 08-02 Sun, 08-03 Mon.
def test_overnight_tail_belongs_to_start_day():
    rule = {"type": "recurring", "days": ["friday", "saturday", "sunday"],
            "start_time": "16:00", "end_time": "02:00", "budget": 1500}
    assert target_for_now(300, [rule], datetime(2026, 7, 31, 18, 0))[0] == 1500   # Fri evening
    assert target_for_now(300, [rule], datetime(2026, 8, 3, 1, 0))[0] == 1500     # Mon 01:00 = Sun's tail
    assert target_for_now(300, [rule], datetime(2026, 7, 31, 1, 0))[0] == 300     # Fri 01:00 = Thu's tail (off)
    assert target_for_now(300, [rule], datetime(2026, 8, 3, 3, 0))[0] == 300      # Mon 03:00 = past the tail


def test_once_overnight_tail():
    rule = {"type": "once", "date": "2026-08-02", "start_time": "16:00", "end_time": "02:00", "budget": 2000}
    assert target_for_now(300, [rule], datetime(2026, 8, 2, 20, 0))[0] == 2000    # Sun evening
    assert target_for_now(300, [rule], datetime(2026, 8, 3, 1, 0))[0] == 2000     # Mon 01:00 = Sun's tail
    assert target_for_now(300, [rule], datetime(2026, 8, 3, 3, 0))[0] == 300      # past the tail
    assert target_for_now(300, [rule], datetime(2026, 8, 1, 20, 0))[0] == 300     # wrong day


# ── Campaign activation: the state half of the plan (docs/campaign-activation.md) ──
#
# The rule under test is AD2: a campaign is stopped ONLY by a window ENDING, never merely
# because no window happens to be active. Getting this wrong stops campaigns at times
# nobody asked for.

WINDOW = {"type": "recurring", "days": [], "start_time": "19:00", "end_time": "02:00",
          "budget": 1000}


def _plan(at, *, toggle=True, rules=(WINDOW,)):
    return plan_for_now(200, list(rules), at, stop_after_window=toggle)


def test_inside_window_is_running_with_the_rule_budget():
    budget, state, _ = _plan(datetime(2026, 8, 1, 20, 0))
    assert (budget, state) == (1000, "running")


def test_at_window_end_is_paused_at_the_default_budget():
    """02:00 — the window just closed, so revert to default AND stop."""
    budget, state, _ = _plan(datetime(2026, 8, 2, 2, 0))
    assert (budget, state) == (200, "paused")


def test_long_after_the_window_is_not_touched():
    """The hourly safety poll at 05:00 must NOT stop anything — the window ended hours
    ago and was already handled. This is the case that separates state-of-the-world from
    'stop when a window ends'."""
    assert _plan(datetime(2026, 8, 2, 5, 0))[1] is None


def test_before_the_first_window_is_not_touched():
    """A schedule created at 14:00 for a 19:00 window: the 15:00 poll must leave the
    campaign alone, not stop it five hours early."""
    assert _plan(datetime(2026, 8, 1, 15, 0))[1] is None


def test_toggle_off_never_pauses():
    """With the toggle off the status is never written — the paused branch is dead."""
    for at in (datetime(2026, 8, 2, 2, 0), datetime(2026, 8, 2, 5, 0)):
        assert _plan(at, toggle=False)[1] is None
    # …but a rule that IS active still says running: starting is unconditional (AD7).
    assert _plan(datetime(2026, 8, 1, 20, 0), toggle=False)[1] == "running"


def test_adjacent_windows_never_stop_at_the_handover():
    """09:00-12:00 then 12:00-18:00: at 12:00 the second window is active, so the
    campaign keeps running and only the budget changes. An event-based 'stop when the
    timer ends' would stop and start it in the same minute."""
    a = {"type": "recurring", "days": [], "start_time": "09:00", "end_time": "12:00", "budget": 500}
    b = {"type": "recurring", "days": [], "start_time": "12:00", "end_time": "18:00", "budget": 800}
    budget, state, _ = _plan(datetime(2026, 8, 1, 12, 0), rules=(a, b))
    assert (budget, state) == (800, "running")


def test_window_just_ended_respects_the_grace():
    """Just past the end → yes; well past → no. The grace is the scheduler's misfire
    window, so a fire late enough to be 'missed' no longer counts as a window end."""
    rules = [WINDOW]
    assert _window_just_ended(rules, datetime(2026, 8, 2, 2, 0), grace_seconds=300) is True
    assert _window_just_ended(rules, datetime(2026, 8, 2, 2, 30), grace_seconds=300) is False


def test_plan_and_target_agree_on_the_budget():
    """plan_for_now is the whole decision; target_for_now is its budget-only view."""
    for at in (datetime(2026, 8, 1, 20, 0), datetime(2026, 8, 2, 5, 0)):
        assert _plan(at)[0] == target_for_now(200, [WINDOW], at)[0]


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
    print(f"\n{len(tests) - failed}/{len(tests)} budget-rule tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
