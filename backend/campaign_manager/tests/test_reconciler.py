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
    BID_JOB, BUDGET_JOB, Desired, _bid_split, _differs, _is_managed, budget_boundaries,
    desired_schedules,
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


def _desired(budget_schedules=None, bid_rules=None, now=NOW):
    return desired_schedules(T, MP, budget_schedules or [], bid_rules or [], now)


# ── CREATE: budget ───────────────────────────────────────────────────────────

def test_recurring_boundaries_and_poll():
    sched = (bsched(), [brule(start_time="13:00", end_time="20:00")])
    ds = _desired([sched])
    by = _by_name(ds)
    assert by["auto:cm:budget:T:blinkit:1300"].cron == "0 13 * * *"
    assert by["auto:cm:budget:T:blinkit:2000"].cron == "0 20 * * *"
    assert by["auto:cm:budget:T:blinkit:poll"].cron == "0 * * * *"
    assert all(d.repeat for d in ds)                                    # all recurring (+ cleanup)
    budget = [d for d in ds if ":cleanup:" not in d.name]
    assert all(d.job_type == BUDGET_JOB for d in budget)               # the budget work is BUDGET_JOB


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


def test_no_expiry_oneshot_is_scheduled():
    """There used to be a one-shot "reset to default" the morning after an end date. The
    rule's own last end boundary already reverts it, and by that morning the engine leaves an
    ended schedule alone — so the fire could only ever start a run that did nothing."""
    sched = (bsched(), [brule(id=3, start_time="13:00", end_time="20:00", end_date=FUTURE)])
    assert not any(":expire:" in d.name for d in _desired([sched]))


# ── Ended budget rules schedule nothing (2026-09-10) ─────────────────────────

def test_an_ended_recurring_budget_rule_schedules_nothing():
    """Its boundary crons and the hourly poll used to live as long as the rule did, firing the
    budget engine every day for an automation that had ended — Dobra's 19:40, 19:42 and hourly
    crons survived the cleanup that was supposed to prune them."""
    sched = (bsched(), [brule(start_time="13:00", end_time="20:00", end_date=PAST)])
    assert _desired([sched]) == []


def test_a_rule_ending_today_keeps_its_crons_until_its_last_window_closes():
    """Pruned at the minute its last window CLOSES — not the midnight after, and not before
    the end boundary that reverts it has had its chance to fire. Once that teardown has landed
    (`settled_at`), nothing at all is left for it."""
    rule = brule(start_time="13:00", end_time="20:00", end_date="2026-08-01")
    before = _names(_desired([(bsched(), [rule])], now=datetime(2026, 8, 1, 19, 0)))
    assert {"auto:cm:budget:T:blinkit:1300", "auto:cm:budget:T:blinkit:2000",
            "auto:cm:budget:T:blinkit:poll"} <= before
    settled = bsched()
    settled.settled_at = datetime(2026, 8, 1, 20, 0)
    assert _desired([(settled, [rule])], now=datetime(2026, 8, 1, 20, 30)) == []


# ── The settle-once safety net (lifecycle.py) ───────────────────────────────

def test_an_ended_schedule_whose_teardown_never_landed_keeps_the_hourly_pass():
    """The budget engine's hourly pass is what settles it, so the poll outlives the boundaries
    until the teardown lands — and not beyond the settle window."""
    rule = brule(start_time="13:00", end_time="20:00", end_date="2026-08-01")
    names = _names(_desired([(bsched(), [rule])], now=datetime(2026, 8, 1, 20, 30)))
    assert "auto:cm:budget:T:blinkit:poll" in names
    assert not {"auto:cm:budget:T:blinkit:1300", "auto:cm:budget:T:blinkit:2000"} & names
    assert _desired([(bsched(), [rule])], now=datetime(2026, 8, 3, 9, 0)) == []


def test_an_ended_bid_rule_whose_reset_never_landed_gets_a_settle_pass():
    rule = bidrule(True, "18:00", "23:00", type="once", date="2026-07-31")
    settle = _by_name(_desired(bid_rules=[rule]))["auto:cm:bid:T:blinkit:settle"]
    assert settle.cron == "37 * * * *" and settle.repeat
    assert settle.params == {"reset": "true", "marketplace": MP}
    rule.settled_at = datetime(2026, 7, 31, 23, 0)
    assert _desired(bid_rules=[rule]) == []


def test_a_paused_rule_that_ended_is_never_settled_automatically():
    """Paused means no writes. A person tears it down with Reset."""
    rule = bidrule(True, "18:00", "23:00", type="once", date="2026-07-31", state="paused")
    assert _desired(bid_rules=[rule]) == []


def test_only_the_live_rules_of_a_schedule_keep_boundaries():
    sched = (bsched(), [brule(id=1, start_time="13:00", end_time="20:00", end_date=PAST),
                        brule(id=2, start_time="10:00", end_time="11:00")])
    assert budget_boundaries([sched], NOW) == {(10, 0), (11, 0)}
    assert "auto:cm:budget:T:blinkit:poll" in _names(_desired([sched]))


# ── CREATE: bid ──────────────────────────────────────────────────────────────

def test_bid_window_cron():
    ds = _desired(bid_rules=[bidrule(active=True, start_time="09:00", stop_time="20:00")])
    opt = _by_name(ds)["auto:cm:bid:T:blinkit:opt"]
    assert opt.cron == "*/15 9-19 * * *" and opt.job_type == BID_JOB


def test_bid_windows_unioned():
    rules = [bidrule(True, "09:00", "12:00"), bidrule(True, "11:00", "15:00")]
    assert _by_name(_desired(bid_rules=rules))["auto:cm:bid:T:blinkit:opt"].cron == "*/15 9-14 * * *"


def test_bid_overnight_window():
    # 18:00–02:00 wraps midnight → hours {18..23, 0..1} → compressed cron field
    rules = [bidrule(True, "18:00", "02:00")]
    assert _by_name(_desired(bid_rules=rules))["auto:cm:bid:T:blinkit:opt"].cron == "*/15 0-1,18-23 * * *"


def test_bid_once_expired_dropped():
    live = bidrule(True, "09:00", "12:00", type="once", date=FUTURE)
    dead = bidrule(True, "18:00", "20:00", type="once", date=PAST)
    names = _names(_desired(bid_rules=[live, dead]))
    assert "auto:cm:bid:T:blinkit:once:20260815" in names
    assert not any(PAST.replace("-", "") in n for n in names)    # expired once contributes nothing


def test_bid_once_is_date_bound_not_recurring():
    # The once-recurs bug: a `once` bid rule must NOT get a daily cron. It gets a date-pinned
    # cron (day+month), and NO recurring `opt` cron.
    ds = _desired(bid_rules=[bidrule(True, "16:00", "18:00", type="once", date=FUTURE)])
    by = _by_name(ds)
    assert "auto:cm:bid:T:blinkit:opt" not in by
    assert by["auto:cm:bid:T:blinkit:once:20260815"].cron == "*/15 16-17 15 8 *"


def test_a_one_time_overnight_window_gets_a_cron_for_its_tail():
    """Pinned to its start date alone, a 19:30–02:00 one-time window's 00:00–02:00 never ran:
    the optimizer was simply never started for those hours."""
    by = _by_name(_desired(bid_rules=[bidrule(True, "19:30", "02:00", type="once", date=FUTURE)]))
    assert by["auto:cm:bid:T:blinkit:once:20260815"].cron == "*/15 19-23 15 8 *"
    assert by["auto:cm:bid:T:blinkit:once:20260816"].cron == "*/15 0-1 16 8 *"


def test_an_overnight_rule_survives_until_its_tail_has_run():
    """Dropped when its last window CLOSES, not when its date passes. Dropping at midnight
    deleted the tail's reset fire on any reconcile before 02:00 — and every rule edit
    triggers one."""
    once = bidrule(True, "18:00", "02:00", type="once", date="2026-08-01")
    recurring = bidrule(True, "18:00", "02:00", stop_date="2026-08-01")
    for rule in (once, recurring):
        recs, onces = _bid_split([rule], datetime(2026, 8, 2, 1, 0))
        assert recs or any(onces.values()), f"{rule.type} rule dropped mid-tail"
        recs, onces = _bid_split([rule], datetime(2026, 8, 2, 3, 0))
        assert not recs and not any(onces.values()), f"{rule.type} rule kept after its tail"


def test_bid_reset_fires_one_minute_BEFORE_the_stop():
    """The reset must beat the budget engine to the campaign: `cm_bid` and `cm_ops` run in
    PARALLEL lanes, and once the budget engine stops a campaign Blinkit refuses bid writes.
    So a 23:00 window's reset fires at 22:59, not 23:00."""
    ds = _desired(bid_rules=[bidrule(True, "19:00", "23:00")])
    reset = _by_name(ds)["auto:cm:bid:T:blinkit:reset:2259"]
    assert reset.cron == "59 22 * * *" and reset.repeat
    # `marketplace` is stamped onto EVERY schedule: the runner builds argv from params,
    # never from the name, and a missing key silently defaults to Blinkit — which sent
    # Zepto's rules at Blinkit's ad account. See test_reconciler_marketplace.py.
    assert reset.params == {"reset": "true", "marketplace": MP}
    assert "auto:cm:bid:T:blinkit:reset:2300" not in _by_name(ds)


def test_bid_reset_lead_wraps_past_midnight():
    """A window stopping at 00:00 leads back to 23:59 the previous day, not to -1 minutes."""
    reset = _by_name(_desired(bid_rules=[bidrule(True, "18:00", "00:00")]))
    assert "auto:cm:bid:T:blinkit:reset:2359" in reset
    assert reset["auto:cm:bid:T:blinkit:reset:2359"].cron == "59 23 * * *"


def test_bid_reset_fire_once_overnight_is_oneshot():
    ds = _desired(bid_rules=[bidrule(True, "19:30", "02:00", type="once", date=FUTURE)])
    reset = _by_name(ds)["auto:cm:bid:T:blinkit:reset:20260816T0159"]   # overnight → next day, less the lead
    assert reset.cron is None and reset.repeat is False
    assert reset.params == {"reset": "true", "marketplace": MP}


def test_all_day_rules_reset_only_where_their_run_of_days_ends():
    """An all-day rule closes at midnight — but only where its run of days ends. A weekday
    filter or an end date → a daily 23:59 fire (the engine picks the right night). Every day
    with no end date never closes → no reset at all (2026-09-18)."""
    fri_sun = bidrule(True)
    fri_sun.days = ["friday", "saturday", "sunday"]
    whole_week = bidrule(True)
    whole_week.days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for rule, wanted in ((fri_sun, True), (bidrule(True, stop_date=FUTURE), True),
                         (bidrule(True), False), (whole_week, False),
                         (bidrule(True, start_time="09:00"), False)):
        resets = {n for n in _names(_desired(bid_rules=[rule])) if ":reset:" in n}
        assert resets == ({"auto:cm:bid:T:blinkit:reset:2359"} if wanted else set()), rule


def test_all_day_once_rule_resets_at_2359_on_its_date():
    ds = _desired(bid_rules=[bidrule(True, type="once", date=FUTURE)])
    reset = _by_name(ds)["auto:cm:bid:T:blinkit:reset:20260815T2359"]
    assert reset.cron is None and reset.repeat is False
    assert reset.next_run_at == datetime(2026, 8, 15, 23, 59)


def test_armed_merges_live_into_reset_params():
    ds = desired_schedules(T, MP, [], [bidrule(True, "19:00", "23:00")], NOW, live=True)
    assert _by_name(ds)["auto:cm:bid:T:blinkit:reset:2259"].params == {
        "reset": "true", "live": "true", "marketplace": MP}


def test_cleanup_reconcile_present_and_live():
    ds = _desired(bid_rules=[bidrule(True, "19:00", "23:00")])
    clean = _by_name(ds)["auto:cm:cleanup:T:blinkit"]
    assert clean.cron == "0 4 * * *"
    assert clean.params == {"live": "true", "marketplace": MP}


def test_no_active_rules_no_cleanup():
    assert not any(":cleanup:" in d.name for d in _desired())   # nothing to maintain → no cleanup


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
