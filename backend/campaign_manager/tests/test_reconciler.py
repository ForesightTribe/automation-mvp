"""Unit tests for the reconciler's planning + diff logic — pure, no Blinkit, no DB.

Run standalone:  python -m campaign_manager.tests.test_reconciler

Feeds hand-built rule objects (SimpleNamespace fakes — the reconciler only reads a
handful of attributes) into `desired_schedules(...)` and the diff helpers, and asserts
the exact schedules that come out. Covers the four reconciler behaviours:
CREATE (right rows), UPDATE/DELETE (via `_differs` / set diff), and IDEMPOTENCY
(run-again → zero changes, even as a recurring row's next_run_at drifts).

Recurring `next_run_at` is computed from the wall clock (arming), so tests never assert
on it; one-shot fire times ARE deterministic (derived from `now`) and are asserted.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from campaign_manager.reconciler import (
    BID_JOB, BUDGET_JOB, Desired, _differs, _is_managed, bid_active_hours,
    budget_boundaries, desired_schedules,
)

T = "T"                       # fake tenant (name segment only)
MP = "blinkit"
NOW = datetime(2026, 8, 1, 9, 0)
FUTURE = "2026-08-15"
PAST = "2026-07-01"


# ── fakes ────────────────────────────────────────────────────────────────────

def bsched(enabled=True, state="active"):
    return SimpleNamespace(state=state, enabled=enabled, campaign_id=1, campaign_name="c", default_budget=500)


def brule(id=1, type="recurring", start_time=None, end_time=None, date=None, end_date=None, budget=1000):
    return SimpleNamespace(id=id, type=type, days=[], time_slots=[], start_time=start_time,
                           end_time=end_time, start_date=None, end_date=end_date, date=date, budget=budget)


def bidrule(active=True, start_time=None, stop_time=None, type="recurring", date=None,
            start_date=None, stop_date=None, state="active"):
    return SimpleNamespace(state=state, active=active, start_time=start_time, stop_time=stop_time,
                           type=type, date=date, start_date=start_date, stop_date=stop_date)


def _names(ds):
    return {d.name for d in ds}


def _by_name(ds):
    return {d.name: d for d in ds}


def _desired(budget_schedules=None, bid_rules=None):
    return desired_schedules(T, MP, budget_schedules or [], bid_rules or [], NOW)


# ── CREATE: budget ───────────────────────────────────────────────────────────

def test_recurring_boundaries_and_poll():
    sched = (bsched(), [brule(start_time="13:00", end_time="20:00")])
    ds = _desired([sched])
    by = _by_name(ds)
    assert by["auto:cm:budget:T:blinkit:1300"].cron == "0 13 * * *"
    assert by["auto:cm:budget:T:blinkit:2000"].cron == "0 20 * * *"
    assert by["auto:cm:budget:T:blinkit:poll"].cron == "0 * * * *"
    assert all(d.job_type == BUDGET_JOB and d.repeat for d in ds)


def test_boundaries_deduped_across_campaigns():
    s1 = (bsched(), [brule(id=1, start_time="13:00", end_time="20:00")])
    s2 = (bsched(), [brule(id=2, start_time="13:00", end_time="22:00")])
    ds = _desired([s1, s2])
    # 13:00 appears once even though two campaigns transition then.
    assert sum(1 for d in ds if d.name.endswith(":1300")) == 1
    assert "auto:cm:budget:T:blinkit:2000" in _names(ds)
    assert "auto:cm:budget:T:blinkit:2200" in _names(ds)


def test_once_creates_two_oneshots():
    sched = (bsched(), [brule(id=7, type="once", date=FUTURE, start_time="10:00", end_time="12:00")])
    ds = _desired([sched])
    by = _by_name(ds)
    on = by["auto:cm:budget:T:blinkit:once:20260815T1000"]        # deduped by fire time, not rule id
    off = by["auto:cm:budget:T:blinkit:once:20260815T1200"]
    assert on.repeat is False and on.cron is None
    assert on.next_run_at == datetime(2026, 8, 15, 10, 0)
    assert off.next_run_at == datetime(2026, 8, 15, 12, 0)
    assert "auto:cm:budget:T:blinkit:poll" not in _names(ds)      # once-only → no perpetual poll


def test_once_fires_deduped_across_campaigns():
    # Many campaigns sharing a once window → ONE apply + ONE revert, not one pair per rule
    # (the 10-campaign 19:30–02:00 bug). Also: no poll for an all-once set.
    s1 = (bsched(), [brule(id=1, type="once", date=FUTURE, start_time="19:30", end_time="02:00")])
    s2 = (bsched(), [brule(id=2, type="once", date=FUTURE, start_time="19:30", end_time="02:00")])
    ds = _desired([s1, s2])
    once = [d for d in ds if ":once:" in d.name]
    assert len(once) == 2                                          # one on + one off, NOT four
    assert "auto:cm:budget:T:blinkit:poll" not in _names(ds)


def test_once_past_is_skipped():
    sched = (bsched(), [brule(id=7, type="once", date=PAST, start_time="10:00", end_time="12:00")])
    ds = _desired([sched])
    assert not any(":once:" in d.name for d in ds)   # nothing in the past
    assert "auto:cm:budget:T:blinkit:poll" not in _names(ds)  # once-only → no perpetual poll


def test_expiry_oneshot():
    sched = (bsched(), [brule(id=3, start_time="13:00", end_time="20:00", end_date=FUTURE)])
    ds = _desired([sched])
    exp = _by_name(ds)["auto:cm:budget:T:blinkit:expire:3"]
    assert exp.repeat is False and exp.next_run_at == datetime(2026, 8, 16, 0, 5)


# ── CREATE: bid ──────────────────────────────────────────────────────────────

def test_bid_window_cron():
    ds = _desired(bid_rules=[bidrule(active=True, start_time="09:00", stop_time="20:00")])
    opt = _by_name(ds)["auto:cm:bid:T:blinkit:opt"]
    assert opt.cron == "*/15 9-19 * * *" and opt.job_type == BID_JOB


def test_bid_windows_unioned():
    rules = [bidrule(True, "09:00", "12:00"), bidrule(True, "11:00", "15:00")]
    assert bid_active_hours(rules, NOW) == {9, 10, 11, 12, 13, 14}
    assert _by_name(_desired(bid_rules=rules))["auto:cm:bid:T:blinkit:opt"].cron == "*/15 9-14 * * *"


def test_bid_overnight_window():
    # 18:00–02:00 wraps midnight → hours {18..23, 0..1} → compressed cron field
    rules = [bidrule(True, "18:00", "02:00")]
    assert bid_active_hours(rules, NOW) == {18, 19, 20, 21, 22, 23, 0, 1}
    assert _by_name(_desired(bid_rules=rules))["auto:cm:bid:T:blinkit:opt"].cron == "*/15 0-1,18-23 * * *"


def test_bid_once_expired_dropped():
    live = bidrule(True, "09:00", "12:00", type="once", date=FUTURE)
    dead = bidrule(True, "18:00", "20:00", type="once", date=PAST)
    assert bid_active_hours([live, dead], NOW) == {9, 10, 11}   # expired once contributes nothing


def test_paused_bid_skipped():
    ds = _desired(bid_rules=[bidrule(state="paused", start_time="09:00", stop_time="20:00")])
    assert not any(d.job_type == BID_JOB for d in ds)   # paused → no control cron


# ── DELETE / empty ───────────────────────────────────────────────────────────

def test_empty_rules_empty_desired():
    assert _desired([], []) == []                       # clean slate → nothing wanted


def test_stopped_schedule_yields_nothing():
    sched = (bsched(state="stopped"), [brule(start_time="13:00", end_time="20:00")])
    assert _desired([sched]) == []                      # stopped → no boundaries, no poll


# ── _is_managed: never touch foreign rows ────────────────────────────────────

def test_is_managed_scoping():
    assert _is_managed("auto:cm:budget:T:blinkit:1300", "blinkit") is True
    assert _is_managed("auto:cm:bid:T:zepto:09-19", "blinkit") is False   # other MP
    assert _is_managed("Dobra marketing daily", "blinkit") is False       # manual row
    assert _is_managed(None, "blinkit") is False


# ── IDEMPOTENCY: run again → zero changes, drift doesn't churn ────────────────

def _existing_like(d: Desired, drift: bool = False):
    """A JobSchedule-ish row as a prior reconcile would have written it."""
    nra = d.next_run_at
    if d.repeat and drift:                              # recurring next_run_at moves as it fires
        nra = (nra or NOW) + timedelta(days=99)
    return SimpleNamespace(
        name=d.name, job_type=d.job_type, cron=d.cron, repeat=d.repeat,
        priority=d.priority, catchup=d.catchup, params=dict(d.params or {}),
        enabled=True, next_run_at=nra,
    )


def test_second_run_is_a_noop():
    sched = (bsched(), [brule(id=3, start_time="13:00", end_time="20:00", end_date=FUTURE)])
    ds = _desired([sched], [bidrule(True, "09:00", "20:00")])
    existing = {d.name: _existing_like(d, drift=True) for d in ds}
    # No creates, no deletes.
    assert set(existing) == _names(ds)
    # No updates — even though every recurring row's next_run_at drifted 99 days.
    assert not any(_differs(existing[d.name], d) for d in ds)


def test_differs_detects_a_real_change():
    d = Desired("auto:cm:budget:T:blinkit:1300", BUDGET_JOB, "0 13 * * *", True, NOW)
    same = _existing_like(d)
    assert _differs(same, d) is False
    changed = _existing_like(d)
    changed.cron = "0 14 * * *"                         # user moved the boundary
    assert _differs(changed, d) is True


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
    print(f"\n{len(tests) - failed}/{len(tests)} reconciler tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
