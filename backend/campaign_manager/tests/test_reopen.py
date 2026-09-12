"""Reopening an ended automation — moving its dates forward — end to end through the API layer.

An automation that has ended is inert: nothing fires for it, Pause and Resume refuse it, and
the settle-once latch records that its final teardown landed. Reopening needs no special
transition because none of that is stored as a gate:

  * the engines recompute the calendar from the dates, so the edit alone brings it back;
  * every edit enqueues a reconcile, whose sweep clears `ended_at` and the stale latch;
  * a latch only covers endings before it, so the NEXT ending is covered by the safety net
    even if the sweep has not run yet.

The service runs for real; only the DB and the job queue are replaced with in-memory fakes.

    python -m campaign_manager.tests.test_reopen
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.schemas.campaign_manager import BidRuleUpdate, BudgetRuleUpdate
from app.services import campaign_manager_service as svc
from campaign_manager import lifecycle, repo

NOW = datetime(2026, 9, 7, 14, 0)
TENANT = "a870fd8d-7373-47ec-ad69-5dd08ce35542"
EARLIER_CLOSE = datetime(2026, 9, 1, 21, 0)        # when the one-time window it had closed


def _bid_rule(**over) -> SimpleNamespace:
    """A one-time 09:00–21:00 bid rule on 2026-09-01: ended, recorded as ended, and settled."""
    rule = SimpleNamespace(
        id="f830ff0b9e0a4e5da8457c6c904bf0a6", tenant_id=TENANT, platform="blinkit",
        campaign_id=637511, campaign_name="Soda KW (Pune)", keyword="soda", match_type="EXACT",
        min_bid=100, max_bid=None, target_position=1, state="active", active=True,
        type="once", date="2026-09-01", days=[], start_date=None, stop_date=None,
        start_time="09:00", stop_time="21:00", lat=18.55, lon=73.93, location_name="Borate Vasti",
        ended_at=EARLIER_CLOSE, settled_at=EARLIER_CLOSE, settle_attempts=0,
        created_at=datetime(2026, 8, 30, 12, 0))
    rule.__dict__.update(over)
    return rule


def _budget() -> tuple[SimpleNamespace, SimpleNamespace]:
    """A budget schedule whose only window — one-time, 2026-09-01 16:00–23:00 — has ended."""
    close = datetime(2026, 9, 1, 23, 0)
    schedule = SimpleNamespace(
        id=112, tenant_id=TENANT, platform="blinkit", campaign_id=637511,
        campaign_name="Soda KW (Pune)", name=None, default_budget=510.0, stop_after_window=True,
        state="active", ended_at=close, settled_at=close, settle_attempts=0,
        created_at=datetime(2026, 8, 30, 12, 0))
    rule = SimpleNamespace(
        id=7, schedule_id=112, budget=750.0, type="once", date="2026-09-01", days=[],
        time_slots=[], start_time="16:00", end_time="23:00", start_date=None, end_date=None)
    return schedule, rule


class _Service:
    """Calls the real service with the DB and the job queue replaced by fakes."""

    def __init__(self, *, bid_rule=None, schedule=None, rules=()):
        self.bid_rule, self.schedule, self.rules = bid_rule, schedule, list(rules)
        self.enqueued: list[str] = []
        self.updates: list[dict] = []
        self.reconciles = 0

    def call(self, action, *args):
        me = self

        async def get_bid_rule(rule_id):
            return me.bid_rule

        async def update_bid_rule(rule_id, fields):
            me.updates.append(fields)
            me.bid_rule.__dict__.update(fields)
            return me.bid_rule

        async def set_bid_state(rule_id, state):
            me.bid_rule.state = state
            return me.bid_rule

        async def get_keyword_floor(*args, **kwargs):
            return None

        async def get_budget_rule(rule_id):
            return next(r for r in me.rules if r.id == rule_id)

        async def get_budget_schedule(schedule_id):
            return me.schedule

        async def update_budget_rule(rule_id, fields):
            me.updates.append(fields)
            (await get_budget_rule(rule_id)).__dict__.update(fields)

        async def get_budget_schedules(tenant_id, platform="blinkit", **kwargs):
            return [(me.schedule, me.rules)]

        async def get_armed(tenant_id, platform="blinkit"):
            return True

        async def enqueue(session, *, job_type, tenant_id, params=None, priority=100):
            me.enqueued.append(job_type)
            return SimpleNamespace(id="job-1")

        async def reconcile(session, tenant_id):
            me.reconciles += 1

        fakes = {
            (repo, "get_bid_rule"): get_bid_rule, (repo, "update_bid_rule"): update_bid_rule,
            (repo, "set_bid_state"): set_bid_state, (repo, "get_keyword_floor"): get_keyword_floor,
            (repo, "get_budget_rule"): get_budget_rule,
            (repo, "get_budget_schedule"): get_budget_schedule,
            (repo, "update_budget_rule"): update_budget_rule,
            (repo, "get_budget_schedules"): get_budget_schedules, (repo, "get_armed"): get_armed,
            (svc, "enqueue"): enqueue, (svc, "_reconcile"): reconcile,
            (svc, "now_ist"): lambda: NOW,
        }
        originals = {key: getattr(*key) for key in fakes}
        for (module, name), fake in fakes.items():
            setattr(module, name, fake)
        try:
            return asyncio.run(action(None, TENANT, *args))
        finally:
            for (module, name), original in originals.items():
                setattr(module, name, original)


def _refused(service, action, *args, error=svc.EditError) -> str | None:
    try:
        service.call(action, *args)
    except error as e:
        return str(e)
    return None


# ── Bid rules ────────────────────────────────────────────────────────────────

def test_an_ended_rule_reads_as_ended_and_cannot_be_paused_or_resumed():
    rule = _bid_rule()
    assert svc._bid_status(rule, NOW) == "ended"
    service = _Service(bid_rule=rule)
    assert "already ended" in _refused(service, svc.pause_bid_rule, rule.id, error=svc.StateError)
    rule.state = "paused"
    assert "already ended" in _refused(service, svc.resume_bid_rule, rule.id, error=svc.StateError)


def test_moving_its_date_forward_reopens_it():
    """Today's 09:00–21:00 window is open at 14:00, so it is running again at once — and an
    in-window edit also asks the optimizer to apply it now rather than at the next tick."""
    rule = _bid_rule()
    service = _Service(bid_rule=rule)
    out = service.call(svc.update_bid_rule, rule.id, BidRuleUpdate(date="2026-09-07"))
    assert out.status == "running", out.status
    assert service.reconciles == 1, "the edit must enqueue the reconcile that restores its crons"
    assert "cm.bid_optimizer" in service.enqueued
    paused = service.call(svc.pause_bid_rule, rule.id)
    assert paused.status == "paused", "a reopened automation can be paused again"


def test_extending_an_ended_recurring_rule_reopens_it():
    rule = _bid_rule(type="recurring", date=None, stop_date="2026-09-01")
    assert svc._bid_status(rule, NOW) == "ended"
    service = _Service(bid_rule=rule)
    out = service.call(svc.update_bid_rule, rule.id, BidRuleUpdate(stop_date="2026-09-30"))
    assert out.status == "running", out.status


def test_moving_it_to_another_past_date_is_refused():
    rule = _bid_rule()
    service = _Service(bid_rule=rule)
    message = _refused(service, svc.update_bid_rule, rule.id, BidRuleUpdate(date="2026-09-05"))
    assert message and "already ended" in message
    assert service.updates == [] and service.reconciles == 0, "a refused edit changes nothing"


def test_editing_an_ended_rule_without_moving_its_dates_says_how_to_run_it_again():
    """The message used to read "This one-time window has already ended" — wrong for a
    recurring rule, and it did not say what would work."""
    for rule in (_bid_rule(), _bid_rule(type="recurring", date=None, stop_date="2026-09-01")):
        message = _refused(_Service(bid_rule=rule), svc.update_bid_rule, rule.id,
                           BidRuleUpdate(min_bid=150))
        assert message and "move its dates forward" in message, message
        assert "one-time" not in message


def test_the_reconcile_after_reopening_clears_the_old_ending():
    rule = _bid_rule()
    _Service(bid_rule=rule).call(svc.update_bid_rule, rule.id, BidRuleUpdate(date="2026-09-07"))
    assert lifecycle.bid_rule_markers(rule, NOW) == {"ended_at": None}


def test_its_next_ending_is_covered_even_before_that_reconcile_runs():
    """No unlatching: the old latch predates the new close, so if tonight's reset never lands
    the settle pass still picks it up."""
    rule = _bid_rule()
    _Service(bid_rule=rule).call(svc.update_bid_rule, rule.id, BidRuleUpdate(date="2026-09-07"))
    tonight = datetime(2026, 9, 7, 21, 0)
    assert rule.settled_at == EARLIER_CLOSE                        # untouched by the edit
    assert lifecycle.bid_rule_needs_settle(rule, tonight + timedelta(hours=1)) is True


# ── Budget schedules ─────────────────────────────────────────────────────────

def test_moving_a_budget_windows_date_forward_reopens_its_schedule():
    schedule, rule = _budget()
    assert svc._budget_status(schedule, [rule], NOW) == "ended"
    service = _Service(schedule=schedule, rules=[rule])
    out = service.call(svc.update_budget_rule, rule.id, BudgetRuleUpdate(date="2026-09-08"))
    assert out.status == "scheduled", out.status
    assert out.rules[0].status == "scheduled"
    assert service.reconciles == 1 and "cm.budget_scheduler" in service.enqueued
    # The stamp is left alone — it records the close that WAS torn down, and the new ending
    # is later than it, so nothing suppresses the next settle (`lifecycle.revert_owed`).
    assert lifecycle.schedule_markers(schedule, [rule], NOW) == {"ended_at": None}


def test_a_budget_window_moved_to_another_past_date_is_refused():
    schedule, rule = _budget()
    service = _Service(schedule=schedule, rules=[rule])
    message = _refused(service, svc.update_budget_rule, rule.id,
                       BudgetRuleUpdate(date="2026-09-02"))
    assert message and "move its dates forward" in message
    assert service.updates == []


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
    print(f"\n{len(tests) - failed}/{len(tests)} reopen tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
