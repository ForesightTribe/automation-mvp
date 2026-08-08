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

    async def setup(self, tenant_id):
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


def _run(*, status: str, toggle: bool, now: datetime, current_budget: float = 500.0) -> list:
    """Run the engine against one fake campaign; return the marketplace calls it made."""
    fake = FakeAdapter(status, current_budget)
    sched, rules = _schedule(toggle=toggle), [_rule()]

    orig = (budget.get_adapter, repo.get_budget_schedules, repo.write_run_log,
            repo.get_advertiser, repo.recent_write_count, budget.now_ist)
    budget.get_adapter = lambda platform: fake
    repo.get_budget_schedules = _async_const([(sched, rules)])
    repo.write_run_log = _async_noop
    repo.get_advertiser = _async_const(19802)
    repo.recent_write_count = _async_const(0)
    budget.now_ist = lambda: now
    try:
        asyncio.run(budget.run(_TENANT, dry_run=False))
    finally:
        (budget.get_adapter, repo.get_budget_schedules, repo.write_run_log,
         repo.get_advertiser, repo.recent_write_count, budget.now_ist) = orig
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


def test_held_campaign_is_never_written_to():
    """ON_HOLD is Blinkit-imposed. Blinkit reports `allowed_transitions: ['UPDATE']` for
    it, but the campaign isn't serving and the hold isn't ours to work around."""
    assert _run(status="held", toggle=True, now=NOW_IN_WINDOW) == []


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
    orig = (sa.get_adapter, repo.get_advertiser, repo.recent_write_count, repo.write_run_log)
    sa.get_adapter = lambda platform: fake
    repo.get_advertiser = _async_const(19802)
    repo.recent_write_count = _async_const(0)
    repo.write_run_log = _async_noop
    try:
        asyncio.run(sa.run(_TENANT, CAMPAIGN, target, budget=budget, dry_run=False))
    finally:
        (sa.get_adapter, repo.get_advertiser,
         repo.recent_write_count, repo.write_run_log) = orig
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
