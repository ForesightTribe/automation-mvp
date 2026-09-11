"""Selection is explicit: every rule loader must be told which automations it wants, on both
axes — pure, no DB, no marketplace.

The loaders used to return every row and let each engine filter. Every engine filtered on
`state`; none on the calendar — which is how automations that had ENDED kept being reset and
kept having their budgets enforced (2026-09-10). With both arguments required, "forgot to
filter" is a TypeError at the call site instead of a silent write to a live campaign.

    python -m campaign_manager.tests.test_selection
"""
import inspect
from datetime import datetime
from types import SimpleNamespace

from campaign_manager import repo, window

NOW = datetime(2026, 8, 12, 14, 0)          # a Wednesday afternoon


def _bid(**kw) -> SimpleNamespace:
    return SimpleNamespace(**{"state": "active", "type": "recurring", "date": None, "days": [],
                              "start_date": None, "stop_date": None, "start_time": None,
                              "stop_time": None, **kw})


def _budget(**kw) -> SimpleNamespace:
    return SimpleNamespace(**{"type": "recurring", "date": None, "days": [], "time_slots": [],
                              "start_date": None, "end_date": None, "start_time": None,
                              "end_time": None, **kw})


def _raises(fn, *args) -> bool:
    try:
        fn(*args)
    except ValueError:
        return True
    return False


# ── The contract ─────────────────────────────────────────────────────────────

def test_both_axes_are_required_keywords_on_every_loader():
    for loader in (repo.get_bid_rules, repo.get_budget_schedules):
        params = inspect.signature(loader).parameters
        for name in ("state", "calendar"):
            p = params[name]
            assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
                f"{loader.__name__}({name}=) must be keyword-only")
            assert p.default is inspect.Parameter.empty, (
                f"{loader.__name__}({name}=) must have no default — a default is what let "
                f"every caller forget the calendar")


def test_any_calendar_means_no_filter_and_needs_no_clock():
    assert repo._calendar_filter(repo.ANY_CALENDAR, None) is None


def test_a_real_calendar_filter_needs_the_callers_clock():
    assert _raises(repo._calendar_filter, {window.RUNNING}, None)
    assert repo._calendar_filter({window.RUNNING}, NOW) == frozenset({window.RUNNING})


def test_nonsense_calendar_arguments_are_refused():
    assert _raises(repo._calendar_filter, set(), NOW)                  # keeps nothing
    assert _raises(repo._calendar_filter, {"stopped"}, NOW)            # a USER state
    assert _raises(repo._calendar_filter, "running", NOW)              # a string is letters


# ── The calendar axis ────────────────────────────────────────────────────────

def test_a_bid_rule_is_kept_by_its_calendar_state():
    running = _bid(start_time="09:00", stop_time="20:00")
    scheduled = _bid(start_date="2026-08-13")
    ended = _bid(stop_date="2026-08-11")
    for rule, state in ((running, "running"), (scheduled, "scheduled"), (ended, "ended")):
        assert window.calendar_state(window.from_bid(rule), NOW) == state
        assert repo._bid_rule_in_calendar(rule, frozenset({state}), NOW)
        assert not repo._bid_rule_in_calendar(rule, repo.ANY_CALENDAR - {state}, NOW)
        assert repo._bid_rule_in_calendar(rule, None, NOW)             # None = no filter


def test_a_budget_schedule_ends_only_when_every_window_has():
    ended = _budget(type="once", date="2026-08-11", start_time="10:00", end_time="12:00")
    later = _budget(type="once", date="2026-08-13", start_time="10:00", end_time="12:00")
    open_now = _budget(start_time="12:00", end_time="18:00")

    def state(*rules):
        return window.schedule_calendar_state([window.from_budget(r) for r in rules], NOW)

    assert state(ended) == "ended"
    assert state(ended, later) == "scheduled"
    assert state(ended, open_now) == "running"
    assert repo._schedule_in_calendar([ended], frozenset({"ended"}), NOW)
    assert not repo._schedule_in_calendar([ended, later], frozenset({"ended"}), NOW)


def test_a_schedule_with_no_windows_never_ends():
    """Default-only: it enforces its default budget indefinitely, so there is nothing that
    could end — reading it as `ended` would switch it off."""
    assert window.schedule_calendar_state([], NOW) == "scheduled"
    assert not repo._schedule_in_calendar([], frozenset({"ended"}), NOW)


def test_the_calendar_says_nothing_about_the_user_axis():
    """A PAUSED rule inside its window is still `running` on the calendar. Folding `paused`
    into the calendar would destroy the paused-and-ended distinction Resume depends on."""
    paused = _bid(state="paused", start_time="09:00", stop_time="20:00")
    assert window.calendar_state(window.from_bid(paused), NOW) == "running"


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
    print(f"\n{len(tests) - failed}/{len(tests)} selection tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
