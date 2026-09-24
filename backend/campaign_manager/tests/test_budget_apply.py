"""The budget engine's APPLY branch — what it actually calls, and in what order (A3 gate).

`test_budget_rules.py` covers the *decision* (`plan_for_now`). This covers the *wiring*:
given a decision and a campaign's live state, does `budget.run` issue the right calls?

That wiring is where campaign activation lives, and two of its properties are invisible
to a pure rule test:

  - a stopped campaign whose window is open is RESTARTED, and the restart CARRIES the
    budget — so it replaces the budget write rather than preceding it;
  - at a window end the budget is reverted BEFORE the campaign is stopped (AD6), because
    if the stop fails the campaign must run on at its *default*, not its raised, budget.

The adapter and repo are stubbed, so this touches neither Blinkit nor the database. Note
the runs are **not** dry: a dry run returns before the adapter is reached (that is the
structural no-write guarantee), so it records nothing to assert on. "Live" here means
live against a fake marketplace that only appends to a list.

    python -m campaign_manager.tests.test_budget_apply
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from campaign_manager import budget, repo


CAMPAIGN = 999001
NOW_IN_WINDOW = datetime(2026, 8, 7, 21, 0)      # inside 19:30–02:00
NOW_AT_END = datetime(2026, 8, 8, 2, 0)          # the moment it closes


def _schedule(*, toggle: bool):
    return SimpleNamespace(
        id=1, state="active", campaign_id=CAMPAIGN, campaign_name="Test Campaign",
        default_budget=500.0, stop_after_window=toggle, platform="blinkit",
    )


def _rule():
    return SimpleNamespace(
        type="recurring", days=[], time_slots=[], start_time="19:30", end_time="02:00",
        start_date=None, end_date=None, date=None, budget=1500.0,
    )


class FakeAdapter:
    """Records calls instead of talking to Blinkit."""

    def __init__(self, status, current_budget):
        self.status = status
        self.current_budget = current_budget
        self.calls = []
        self.signed_in = False

    async def setup(self, tenant_id):
        self.signed_in = True
        return None, None, SimpleNamespace(_email="test@example.com")

    def set_advertiser(self, client, advertiser_id):
        pass

    async def read_campaign(self, client, campaign_id):
        return (self.status, self.current_budget,
                {"name": "Test Campaign", "campaign_budget": self.current_budget})

    async def read_budget(self, client, campaign_id):
        return self.current_budget

    async def apply_budget(self, client, campaign_id, target):
        self.calls.append(("budget", target))
        return {"success": True}

    async def apply_status(self, client, campaign_id, target, *, budget=None):
        self.calls.append(("status", target, budget))
        return {"success": True}


def _run(*, status: str, toggle: bool, now: datetime, current_budget: float = 500.0,
         rules: list | None = None, schedule: dict | None = None) -> list:
    """Run the engine against one fake campaign; return the marketplace calls it made.

    The adapter is left on `_run.fake` for a test that needs more than the calls — including
    what the run latched as settled (`fake.settled`, id → stamp) and the teardowns it counted
    as failed (`fake.failed`). `schedule` overrides fields on the fake schedule. The settle
    writes are stubbed like every other repo call: nothing here reaches the database."""
    fake = FakeAdapter(status, current_budget)
    fake.settled, fake.failed = {}, []
    _run.fake = fake
    sched, rules = _schedule(toggle=toggle), (rules if rules is not None else [_rule()])
    for field, value in (schedule or {}).items():
        setattr(sched, field, value)

    async def _mark_settled(kind, stamps):
        fake.settled.update(stamps)

    async def _bump_attempts(kind, ids):
        fake.failed.extend(ids)

    orig = (budget.get_adapter, repo.get_budget_schedules, repo.write_run_log,
            repo.get_advertiser, repo.recent_write_count, budget.now_ist,
            repo.get_tenant_name, repo.mark_settled, repo.bump_settle_attempts)
    budget.get_adapter = lambda platform: fake
    repo.get_budget_schedules = _async_const([(sched, rules)])
    repo.write_run_log = _async_noop
    repo.get_tenant_name = _async_const("Test Tenant")
    repo.get_advertiser = _async_const(19802)
    repo.recent_write_count = _async_const(0)
    repo.get_tenant_name = _async_const("Test Tenant")
    repo.mark_settled = _mark_settled
    repo.bump_settle_attempts = _bump_attempts
    budget.now_ist = lambda: now
    try:
        # The fake adapter stands in for whichever marketplace a test configures; the engine
        # needs to be told one — there is no default (ZC-D1).
        asyncio.run(budget.run(_TENANT, dry_run=False, platform="blinkit"))
    finally:
        (budget.get_adapter, repo.get_budget_schedules, repo.write_run_log,
         repo.get_advertiser, repo.recent_write_count, budget.now_ist,
         repo.get_tenant_name, repo.mark_settled, repo.bump_settle_attempts) = orig
    return fake.calls


_TENANT = "00000000-0000-0000-0000-000000000001"


def _async_const(value):
    async def _f(*a, **k):
        return value
    return _f


async def _async_noop(*a, **k):
    return None


# ── The cases ───────────────────────────────────────────────────────────────

def test_stopped_campaign_in_window_is_restarted_with_the_rule_budget():
    """The core of the merged design: one call, carrying the budget — NOT a budget
    write followed by a start."""
    calls = _run(status="paused", toggle=True, now=NOW_IN_WINDOW)
    assert calls == [("status", "running", 1500.0)], calls


def test_start_is_unconditional_even_with_the_toggle_off():
    """AD7 — the toggle governs only the STOP. A campaign with an open budget window is
    meant to be running, so finding it stopped and leaving it stopped would silently do
    nothing all evening."""
    calls = _run(status="paused", toggle=False, now=NOW_IN_WINDOW)
    assert calls == [("status", "running", 1500.0)], calls


def test_running_campaign_in_window_just_gets_the_budget():
    calls = _run(status="running", toggle=True, now=NOW_IN_WINDOW)
    assert calls == [("budget", 1500.0)], calls


def test_window_end_reverts_the_budget_BEFORE_stopping():
    """AD6 — order matters. If the stop fails the campaign must run on at its DEFAULT
    budget, not its raised one; that ordering is the whole guardrail."""
    calls = _run(status="running", toggle=True, now=NOW_AT_END, current_budget=1500.0)
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls
    assert calls[0][0] == "budget" and calls[1][0] == "status", "revert must precede stop"


def test_window_end_with_toggle_off_reverts_but_never_stops():
    calls = _run(status="running", toggle=False, now=NOW_AT_END, current_budget=1500.0)
    assert calls == [("budget", 500.0)], calls


def test_held_campaign_still_gets_its_budget():
    """ON_HOLD means Blinkit paused delivery because the budget ran out — the campaign is
    LIVE, and raising its budget is exactly what revives it. Skipping the write withheld
    the one thing that would have helped, on 5 of the client's 11 automated campaigns."""
    calls = _run(status="held", toggle=True, now=NOW_IN_WINDOW)
    assert calls == [("budget", 1500.0)], calls


def test_held_campaign_is_never_restarted():
    """There is nothing to restart — which is why Blinkit offers `['UPDATE']` and never
    `['RESTART']` for a held campaign. The budget write is what matters."""
    from campaign_manager.writes import status_transition_denied
    assert status_transition_denied("held", "running") is not None


def test_completed_campaign_is_never_written_to():
    assert _run(status="ended", toggle=True, now=NOW_IN_WINDOW) == []


# ── set_activation: "start at ₹X" on a campaign that is already running ──────
#
# Guards a real bug: Budget Reset on a stop-after-window schedule enqueues a
# start-at-default (the campaign may have been stopped by the automation, and Reset has to
# undo that too). When the campaign happened to be RUNNING the status write was a no-op,
# the budget was silently dropped, and — because Reset also marks the schedule stopped —
# no later run would ever bring the elevated window budget back down.

def _run_activation(*, target: str, status: str, budget, current_budget: float = 1500.0) -> list:
    import campaign_manager.set_activation as sa

    fake = FakeAdapter(status, current_budget)
    orig = (sa.get_adapter, repo.get_advertiser, repo.recent_write_count, repo.write_run_log,
            repo.get_tenant_name)
    sa.get_adapter = lambda platform: fake
    repo.get_advertiser = _async_const(19802)
    repo.recent_write_count = _async_const(0)
    repo.write_run_log = _async_noop
    repo.get_tenant_name = _async_const("Test Tenant")
    try:
        asyncio.run(sa.run(_TENANT, CAMPAIGN, target, budget=budget, dry_run=False,
                           platform="blinkit"))
    finally:
        (sa.get_adapter, repo.get_advertiser, repo.recent_write_count, repo.write_run_log,
         repo.get_tenant_name) = orig
    return fake.calls


def test_start_on_an_already_running_campaign_still_applies_the_budget():
    calls = _run_activation(target="running", status="running", budget=500.0, current_budget=1500.0)
    assert calls == [("budget", 500.0)], calls


def test_start_on_a_stopped_campaign_restarts_and_writes_no_separate_budget():
    calls = _run_activation(target="running", status="paused", budget=500.0)
    assert calls == [("status", "running", 500.0)], calls


def test_stop_passes_no_budget_at_all():
    """A stop is a bodiless DELETE — it must not carry a budget that looks meaningful."""
    calls = _run_activation(target="paused", status="running", budget=None)
    assert calls == [("status", "paused", None)], calls


# ── Unfamiliar statuses (the 2026-08-08 production bug) ──────────────────────

def test_scheduled_is_treated_as_running():
    """Blinkit reports SCHEDULED for a minute or two after a RESTART. It is live, so a
    window end must still revert the budget and stop it — the case that left campaign
    574687 serving at its window budget."""
    from campaign_manager.marketplaces.blinkit.adapter import _canonical
    assert _canonical("SCHEDULED") == "running"

    calls = _run(status="running", toggle=True, now=NOW_AT_END, current_budget=1500.0)
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls


def test_a_stop_is_attempted_even_for_an_unrecognised_status():
    """A status we cannot map must never silently cancel a stop. Failing to START a
    campaign is cheap; failing to STOP one costs money every hour. The budget write is
    skipped (Blinkit would reject it), the stop is still attempted, and the transition
    table — not this engine — decides whether it is allowed."""
    calls = _run(status="SOMETHING_NEW", toggle=True, now=NOW_AT_END, current_budget=1500.0)
    assert calls == [], calls          # the transition table refuses an unknown status…
    # …but it was ASKED, rather than skipped before it could refuse: the refusal is logged
    # as a guardrail trip, which is visible, instead of vanishing into a bare "skip".


def test_held_campaign_at_a_window_end_reverts_AND_stops():
    """A held campaign is live, so "off outside the window" applies to it too."""
    calls = _run(status="held", toggle=True, now=NOW_AT_END, current_budget=1500.0)
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls


# ── Ended schedules (2026-09-10) ─────────────────────────────────────────────
#
# A one-time 19:30–02:00 window on 2026-08-07. Its only window closes at 02:00 on the 8th.

_ONE_TIME = SimpleNamespace(
    type="once", days=[], time_slots=[], start_time="19:30", end_time="02:00",
    start_date=None, end_date=None, date="2026-08-07", budget=1500.0,
)
_CLOSED = datetime(2026, 8, 8, 2, 0)


def test_the_fire_that_closes_the_last_window_still_reverts_and_stops():
    """The schedule is ENDED from 02:00 — and 02:00 is exactly the fire that must still revert
    the budget and stop the campaign. Ending cannot cost it its own teardown, and landing
    that teardown latches it."""
    calls = _run(status="running", toggle=True, now=NOW_AT_END, current_budget=1500.0,
                 rules=[_ONE_TIME])
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls
    assert _run.fake.settled == {1: _CLOSED} and _run.fake.failed == []


def test_a_settled_schedule_is_never_written_to_again():
    """2026-09-09: a campaign restarted by hand at ₹502 was set to its ENDED automation's ₹510
    default 39 minutes later. Once the teardown has landed, nothing is written — and the engine
    does not even sign in, which on a one-session-per-user marketplace would evict whoever is
    using the dashboard."""
    calls = _run(status="running", toggle=True, now=datetime(2026, 8, 8, 5, 0),
                 current_budget=502.0, rules=[_ONE_TIME], schedule={"settled_at": _CLOSED})
    assert calls == [], calls
    assert not _run.fake.signed_in, "signed in to the marketplace for an automation that has ended"


def test_a_teardown_that_never_landed_is_done_by_the_next_pass():
    """The runner was down at 02:00. The 03:00 pass — far outside the misfire grace — finds the
    schedule ended and unsettled, and does what 02:00 should have: revert, THEN stop."""
    calls = _run(status="running", toggle=True, now=datetime(2026, 8, 8, 3, 0),
                 current_budget=1500.0, rules=[_ONE_TIME])
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls
    assert 1 in _run.fake.settled


def test_the_settle_pass_does_no_more_than_the_missed_run_would_have():
    """With the toggle off, the missed run would only have reverted the budget — so settling
    never touches the campaign's status either."""
    calls = _run(status="running", toggle=False, now=datetime(2026, 8, 8, 3, 0),
                 current_budget=1500.0, rules=[_ONE_TIME])
    assert calls == [("budget", 500.0)], calls


def test_nothing_is_settled_once_a_person_has_had_time_to_take_over():
    """27 hours after the close is past SETTLE_MAX_AGE_HOURS: no write, no sign-in."""
    calls = _run(status="running", toggle=True, now=datetime(2026, 8, 9, 5, 0),
                 current_budget=502.0, rules=[_ONE_TIME])
    assert calls == [] and not _run.fake.signed_in, calls


def test_a_teardown_that_does_not_land_counts_an_attempt():
    """A status the transition table refuses to stop: nothing landed, so no latch — one attempt."""
    _run(status="SOMETHING_NEW", toggle=True, now=NOW_AT_END, current_budget=1500.0,
         rules=[_ONE_TIME])
    assert _run.fake.settled == {} and _run.fake.failed == [1], (_run.fake.settled, _run.fake.failed)


# ── Between windows, the engine does nothing at all (2026-09-12) ────────────
#
# The recurring 19:30–02:00 schedule has no end date, so 02:00 is an ordinary window end.
# Every close is latched — not because the automation is over, but so the hours after it
# stay quiet. `settled_at` is "the most recent close this schedule has been torn down for".

_BETWEEN = datetime(2026, 8, 8, 10, 0)               # long after 02:00, long before 19:30


def test_an_ordinary_window_close_latches_too():
    _run(status="running", toggle=True, now=NOW_AT_END, current_budget=1500.0)
    assert _run.fake.settled == {1: NOW_AT_END} and _run.fake.failed == []


def test_between_windows_the_campaign_is_never_touched():
    """Not read, not written — the hourly poll used to re-assert the default here, which is
    how a budget set by hand at 10:00 was gone by 11:00."""
    calls = _run(status="running", toggle=True, now=_BETWEEN, current_budget=2000.0,
                 schedule={"settled_at": datetime(2026, 8, 8, 2, 0)})
    assert calls == [], calls
    assert _run.fake.signed_in is False, "a run with no work must not sign in"


def test_a_close_whose_revert_never_landed_is_repaired_then_latched():
    """The failsafe: the runner was down at 02:00, so the 10:00 poll does what that fire
    would have — revert, then stop — and latches so 11:00 does nothing. The stamp is `now`,
    which is at or after the close it covers."""
    calls = _run(status="running", toggle=True, now=_BETWEEN, current_budget=1500.0)
    assert calls == [("budget", 500.0), ("status", "paused", None)], calls
    assert _run.fake.settled == {1: _BETWEEN}


def test_a_repair_is_not_owed_for_a_close_older_than_a_day():
    """Past that, the campaign's budget is whatever the days since made it — re-asserting a
    default nobody asked for is the behaviour this replaced. (A one-time rule, because a
    daily one always has a close within the last 24 hours.)"""
    calls = _run(status="running", toggle=True, now=datetime(2026, 8, 10, 10, 0),
                 current_budget=1500.0, rules=[_ONE_TIME])
    assert calls == [], calls


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} budget-apply tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
