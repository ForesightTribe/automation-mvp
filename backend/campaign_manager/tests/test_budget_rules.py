"""Unit tests for budget rule-matching (V1) — pure logic, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_budget_rules

Uses a fixed reference time and derives the weekday from it, so the tests are
independent of the real calendar.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

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


# ── Campaign activation: the state half of the plan (docs/campaign-manager.md) ──
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


def test_plan_and_target_agree_while_a_window_is_open():
    """plan_for_now is what this RUN should do; target_for_now is what the calendar says.
    Inside a window they agree; outside one they answer different questions — the calendar
    still says "the default", and the run says "nothing of mine"."""
    at = datetime(2026, 8, 1, 20, 0)
    assert _plan(at)[0] == target_for_now(200, [WINDOW], at)[0] == 1000


# ── Between windows the budget is not ours (2026-09-12) ─────────────────────
#
# The engine used to answer `default_budget` whenever no rule matched, so every hourly poll
# re-asserted it — and a budget someone set by hand at 10:00 was gone by 11:00.

def test_between_windows_there_is_nothing_to_enforce():
    budget, state, reason = _plan(datetime(2026, 8, 2, 5, 0))
    assert budget is None and state is None
    assert "not this automation's to set" in reason


def test_a_window_close_still_reverts_to_the_default():
    assert _plan(datetime(2026, 8, 2, 2, 0))[0] == 200


def test_an_owed_revert_reverts_long_after_the_close():
    """The failsafe: the 02:00 fire never landed, so the 05:00 one does its work — and
    stops the campaign too, which is what the missed fire would have done."""
    budget, state, reason = plan_for_now(200, [WINDOW], datetime(2026, 8, 2, 5, 0),
                                         stop_after_window=True, revert_owed=True)
    assert (budget, state) == (200, "paused")
    assert "never put back" in reason


def test_a_schedule_with_no_rules_still_holds_its_default():
    """It has no windows to be between — enforcing the default is the whole of what it does."""
    assert plan_for_now(200, [], datetime(2026, 8, 2, 5, 0))[0] == 200


# ── Short windows (the 2026-08-08 production bug) ───────────────────────
#
# `_window_just_ended` used to probe a SINGLE instant at `now - grace`. Any window shorter
# than the grace fell straight through the gap: the probe landed before the window had
# even opened, so the campaign was never stopped.

SHORT = {"type": "once", "date": "2026-08-08", "start_time": "15:46",
         "end_time": "15:49", "days": [], "budget": 205}


def test_short_window_still_triggers_the_stop():
    """3-minute window, 5-minute grace — the exact case that left 574687 running."""
    budget, state, _ = plan_for_now(200, [SHORT], datetime(2026, 8, 8, 15, 50),
                                    stop_after_window=True)
    assert (budget, state) == (200, "paused")


def test_short_window_is_running_inside_it():
    assert plan_for_now(200, [SHORT], datetime(2026, 8, 8, 15, 47),
                        stop_after_window=True)[1] == "running"


def test_short_window_is_left_alone_well_afterwards():
    """Still AD2: an hour later is not a window end, so nothing is touched."""
    assert plan_for_now(200, [SHORT], datetime(2026, 8, 8, 16, 30),
                        stop_after_window=True)[1] is None


def test_a_late_fire_within_the_grace_still_stops():
    """The fire ran two minutes late — a point probe would have missed the window."""
    assert plan_for_now(200, [SHORT], datetime(2026, 8, 8, 15, 51),
                        stop_after_window=True)[1] == "paused"


# ── UI status: a spent one-time rule must read "Ended", not "Scheduled" ──────

def test_spent_once_rule_reads_as_ended_the_same_day():
    """It used to compare only `date < today`, so a one-time automation that had already
    run and reverted still showed as upcoming for the rest of the day."""
    from campaign_manager import window

    assert window.window_close("2026-08-08", "15:46", "15:49").hour == 15
    assert window.window_close("2026-08-08", "19:30", "02:00").day == 9     # overnight tail
    assert window.window_close("2026-08-08", "19:30", None).day == 9        # runs to midnight
    after = datetime(2026, 8, 8, 15, 50)
    spent = window.Window(type="once", date="2026-08-08", start_time="15:46", end_time="15:49")
    assert window.is_expired(spent, after) is True                          # same day, after
    assert window.calendar_state(spent, after) == "ended"
    # A future-dated rule is never expired.
    future = window.Window(type="once", date="2099-01-01", start_time="15:46", end_time="15:49")
    assert window.is_expired(future, after) is False


# ── The engine acts on a window's edges, never between windows ──────────────
#
# `_has_work` decides whether the engine acts on a schedule at all. Two real campaigns from
# 2026-09-09 are the cases: both had their budgets overwritten between windows — one by an
# automation that had ENDED (fixed 2026-09-10), one by an automation that was still live and
# simply re-asserting its default every hour (fixed here).

_SODA = {"type": "once", "date": "2026-09-07", "start_time": "16:00", "end_time": "23:00",
         "budget": 750}
_TECH_TEST = {"days": ["wednesday"], "start_date": "2026-09-09", "end_date": "2026-09-09",
              "start_time": "19:40", "end_time": "19:42", "budget": 105}
_DAILY = {"start_time": "19:00", "end_time": "21:00", "budget": 900}


def _sched(**kw):
    """A schedule row as the engine reads it — `settled_at` is the latch that says its last
    close has already been put back to the default."""
    return SimpleNamespace(**{"id": 1, "state": "active", "created_at": datetime(2026, 1, 1),
                              "settled_at": None, "settle_attempts": 0, **kw})


def _work(rules, at, *, settled_at=None, **kw):
    from campaign_manager.budget import _has_work
    return _has_work(_sched(settled_at=settled_at, **kw), rules, at, 300)


def test_an_ended_schedule_is_left_alone():
    """Campaign 637511: restarted by hand at ₹502 on 2026-09-09, set to its ended automation's
    ₹510 default at 21:01 — two days after the automation's only window. Too old to repair
    and too late to matter, whether or not the revert ever landed."""
    assert _work([_SODA], datetime(2026, 9, 9, 21, 1)) is False
    assert _work([_SODA], datetime(2026, 9, 9, 21, 1),
                 settled_at=datetime(2026, 9, 7, 23, 0)) is False


def test_the_fire_that_closes_a_window_is_always_work():
    """That fire reverts the budget and stops the campaign; ending must not cost it."""
    assert _work([_SODA], datetime(2026, 9, 7, 23, 0)) is True
    assert _work([_SODA], datetime(2026, 9, 7, 23, 4)) is True      # late, inside the grace


def test_a_close_whose_revert_never_landed_is_still_work():
    """The failsafe. Past the grace the close is no longer an edge, but the budget is still
    raised — so the next fire repairs it, and only until it is latched."""
    late = datetime(2026, 9, 7, 23, 10)
    assert _work([_SODA], late) is True
    assert _work([_SODA], late, settled_at=datetime(2026, 9, 7, 23, 0)) is False


def test_a_live_schedule_is_quiet_between_its_windows():
    """The change: a schedule whose last close has been reverted has nothing to do until the
    next one. It used to re-assert its default on every hourly poll."""
    latched = datetime(2026, 9, 8, 21, 0)                           # last night's close
    assert _work([_DAILY], datetime(2026, 9, 9, 3, 0), settled_at=latched) is False
    assert _work([_DAILY], datetime(2026, 9, 9, 20, 0), settled_at=latched) is True  # in window
    upcoming = {"type": "once", "date": "2026-09-20", "start_time": "10:00",
                "end_time": "12:00", "budget": 900}
    assert _work([upcoming], datetime(2026, 9, 9, 3, 0)) is False   # never opened yet


def test_a_close_from_before_the_schedule_existed_is_not_its_business():
    """A schedule created at 14:00 must not revert for a window that closed at 02:00 that
    morning — it was not there to raise the budget, so it has nothing to put back."""
    assert _work([_DAILY], datetime(2026, 9, 9, 22, 30),
                 created_at=datetime(2026, 9, 9, 22, 0)) is False


def test_a_schedule_with_no_rules_is_always_work():
    """Its default is all it has, so enforcing that default is the whole of what it does."""
    assert _work([], datetime(2026, 9, 9, 3, 0)) is True


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
