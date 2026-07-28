"""Unit tests for budget rule-matching (V1) — pure logic, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_budget_rules

Uses a fixed reference time and derives the weekday from it, so the tests are
independent of the real calendar.
"""
from datetime import datetime, timedelta

from campaign_manager.budget import target_for_now

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
