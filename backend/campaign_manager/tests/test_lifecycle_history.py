"""An automation's lifecycle, as the client reads it in History — no DB, no marketplace.

Four actions: `ended` and `reopened` (written by the reconciler's sweep), `settled` and
`settle-failed` (written by the run that performed — or finally failed — an automation's last
teardown). The pure row-building is tested directly; the engines are run for real against
fake adapters, so the wiring that decides WHICH rows get written is exercised too.

    python -m campaign_manager.tests.test_lifecycle_history
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.campaign_manager_v2 import CmRunLog
from campaign_manager import bid, budget, config, lifecycle, repo
from campaign_manager.tests.test_budget_apply import (
    NOW_AT_END, _ONE_TIME, _TENANT, FakeAdapter, _async_const, _async_noop,
)

NOW = datetime(2026, 9, 10, 9, 0)
CLOSE = datetime(2026, 9, 7, 23, 0)                    # a one-time 16:00–23:00 window on 09-07


def _bid(**over) -> SimpleNamespace:
    rule = SimpleNamespace(id="f830ff0b9e0a4e5da8457c6c904bf0a6", state="active",
                           campaign_id=637511, campaign_name="Soda KW (Pune)", keyword="soda",
                           type="once", date="2026-09-07", days=[], start_date=None,
                           stop_date=None, start_time="16:00", stop_time="23:00",
                           created_at=datetime(2026, 9, 1), ended_at=None, settled_at=None,
                           settle_attempts=0)
    rule.__dict__.update(over)
    return rule


def _sweep(bid_rules=(), budget_schedules=()) -> list[dict]:
    bid_markers = {r.id: lifecycle.bid_rule_markers(r, NOW) for r in bid_rules}
    budget_markers = {s.id: lifecycle.schedule_markers(s, rules, NOW) for s, rules in budget_schedules}
    return lifecycle.sweep_history(list(budget_schedules), list(bid_rules), bid_markers,
                                   budget_markers, tenant_id=_TENANT, platform="blinkit",
                                   run_id="run", now=NOW)


# ── The rows themselves ──────────────────────────────────────────────────────

def test_lifecycle_actions_never_count_as_writes_and_are_never_hidden():
    """Counted as writes they would eat the runaway-write budget; hidden as no-change rows the
    client would never see that an automation had finished."""
    assert not lifecycle.ACTIONS & set(repo._WRITE_ACTIONS)
    assert not lifecycle.ACTIONS & set(repo.NO_CHANGE_ACTIONS)


def test_a_lifecycle_row_fits_the_history_table():
    row = lifecycle.history_row(tenant_id=_TENANT, platform="blinkit", kind="bid",
                                action=lifecycle.SETTLED, campaign_id=1, campaign_name="c",
                                reason="r", timestamp=NOW, rule_id=12345)
    assert set(row) <= set(CmRunLog.model_fields), set(row) - set(CmRunLog.model_fields)
    assert row["rule_id"] == "12345", "cm_run_log.rule_id is TEXT"
    assert row["dry_run"] is False and row["old_value"] is None and row["new_value"] is None


def test_every_lifecycle_reason_is_one_readable_line():
    reasons = [lifecycle.ended_reason(CLOSE, False), lifecycle.ended_reason(CLOSE, True),
               lifecycle.REOPENED_REASON, lifecycle.settled_reason("bid"),
               lifecycle.settled_reason("budget"), lifecycle.settle_failed_reason("bid"),
               lifecycle.settle_failed_reason("budget")]
    for reason in reasons:
        assert reason and "\n" not in reason and "→" not in reason, reason
    assert str(config.SETTLE_MAX_ATTEMPTS) in lifecycle.settle_failed_reason("bid")


# ── The sweep's rows ─────────────────────────────────────────────────────────

def test_an_ending_is_recorded_at_the_close_not_when_it_was_swept():
    """The first reconcile after a deploy sweeps automations that ended days ago. Stamped with
    the sweep time, all of them would pile up at the top of History as if they had just ended."""
    [row] = _sweep(bid_rules=[_bid()])
    assert row["action"] == lifecycle.ENDED and row["timestamp"] == CLOSE
    assert row["kind"] == "bid" and row["keyword"] == "soda" and row["rule_id"] == _bid().id
    assert "07 Sep at 23:00" in row["reason"]


def test_reopening_is_recorded_when_it_happens():
    [row] = _sweep(bid_rules=[_bid(date="2026-09-20", ended_at=CLOSE, settled_at=CLOSE)])
    assert row["action"] == lifecycle.REOPENED and row["timestamp"] == NOW


def test_nothing_is_recorded_when_nothing_changes_state():
    assert _sweep(bid_rules=[_bid(ended_at=CLOSE)]) == []                      # already recorded
    assert _sweep(bid_rules=[_bid(date="2026-09-20")]) == []                   # live, never ended
    # Still ended, but its recorded close is out of date (its date was edited to another past day):
    # the marker is corrected, and no second `ended` row is written.
    assert _sweep(bid_rules=[_bid(ended_at=CLOSE - timedelta(days=3))]) == []


def test_an_automation_that_could_never_run_says_so():
    [row] = _sweep(bid_rules=[_bid(date=None)])
    assert row["action"] == lifecycle.ENDED and "never run" in row["reason"]
    assert row["timestamp"] == datetime(2026, 9, 1), "it ended when it was created"


def test_a_budget_schedule_ending_is_recorded_per_campaign():
    schedule = SimpleNamespace(id=112, state="active", campaign_id=637511,
                               campaign_name="Soda KW (Pune)", created_at=datetime(2026, 9, 1),
                               ended_at=None, settled_at=None, settle_attempts=0)
    rules = [SimpleNamespace(type="once", date="2026-09-07", days=[], time_slots=[],
                             start_date=None, end_date=None, start_time="16:00", end_time="23:00")]
    [row] = _sweep(budget_schedules=[(schedule, rules)])
    assert row["kind"] == "budget" and row["campaign_id"] == 637511
    assert row["keyword"] is None and row["rule_id"] is None and row["timestamp"] == CLOSE


# ── The budget engine's rows ─────────────────────────────────────────────────

def _budget_run(*, status: str, now: datetime, attempts: int = 0, dry_run: bool = False) -> dict:
    """Run the real budget engine on one fake schedule; capture History and the settle writes."""
    fake = FakeAdapter(status, 1500.0)
    schedule = SimpleNamespace(id=1, state="active", campaign_id=999001,
                               campaign_name="Test Campaign", default_budget=500.0,
                               stop_after_window=True, platform="blinkit",
                               settled_at=None, settle_attempts=attempts)
    seen = {"rows": [], "settled": {}, "bumped": []}

    async def write_run_log(rows):
        seen["rows"].extend(rows)

    async def mark_settled(kind, stamps):
        seen["settled"].update(stamps)

    async def bump_settle_attempts(kind, ids):
        ids = list(ids)
        seen["bumped"].extend(ids)
        return [i for i in ids if attempts + 1 == config.SETTLE_MAX_ATTEMPTS]

    patches = {
        (budget, "get_adapter"): lambda platform: fake,
        (repo, "get_budget_schedules"): _async_const([(schedule, [_ONE_TIME])]),
        (repo, "write_run_log"): write_run_log, (repo, "get_advertiser"): _async_const(19802),
        (repo, "recent_write_count"): _async_const(0),
        (repo, "get_tenant_name"): _async_const("Test Tenant"),
        (repo, "mark_settled"): mark_settled, (repo, "bump_settle_attempts"): bump_settle_attempts,
        (budget, "now_ist"): lambda: now,
    }
    originals = {key: getattr(*key) for key in patches}
    for (module, name), fake_fn in patches.items():
        setattr(module, name, fake_fn)
    try:
        asyncio.run(budget.run(_TENANT, dry_run=dry_run))
    finally:
        for (module, name), original in originals.items():
            setattr(module, name, original)
    seen["lifecycle"] = [r for r in seen["rows"] if r["action"] in lifecycle.ACTIONS]
    return seen


def test_the_budget_teardown_that_lands_is_recorded_as_finished():
    seen = _budget_run(status="running", now=NOW_AT_END)
    [row] = seen["lifecycle"]
    assert row["action"] == lifecycle.SETTLED and row["success"] is True
    assert row["kind"] == "budget" and row["campaign_id"] == 999001


def test_the_budget_teardown_that_runs_out_of_retries_is_recorded_once():
    """A status the transition table will not stop, on the last allowed attempt."""
    seen = _budget_run(status="SOMETHING_NEW", now=NOW_AT_END,
                       attempts=config.SETTLE_MAX_ATTEMPTS - 1)
    [row] = seen["lifecycle"]
    assert row["action"] == lifecycle.SETTLE_FAILED and row["success"] is False


def test_an_earlier_failed_attempt_records_no_lifecycle_row():
    """The run's own error / skip rows already say it failed; "couldn't finish" is for giving up."""
    seen = _budget_run(status="SOMETHING_NEW", now=NOW_AT_END, attempts=0)
    assert seen["bumped"] == [1] and seen["lifecycle"] == []


def test_a_dry_run_records_no_lifecycle_row():
    seen = _budget_run(status="running", now=NOW_AT_END, dry_run=True)
    assert seen["lifecycle"] == [] and seen["settled"] == {} and seen["bumped"] == []


# ── The bid reset's rows (the real `_floor_bids`) ────────────────────────────

class _BidAdapter:
    """Just enough marketplace for `_floor_bids`: one campaign, one keyword, a write that
    lands or is rejected."""

    def __init__(self, current: int, accept: bool = True):
        self.current, self.accept, self.writes = current, accept, []

    async def setup(self, tenant_id):
        return None, None, SimpleNamespace()

    def set_advertiser(self, client, advertiser_id):
        pass

    async def read_campaign(self, client, campaign_id):
        return "running", 500.0, {"bids": {"soda": self.current}}

    def bids_from_detail(self, detail):
        return dict(detail["bids"])

    async def read_bid_floors(self, client, campaign_id, detail):
        return {}

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        self.writes.append((keyword, cpm))
        return {"success": self.accept}


def _floor(adapter: _BidAdapter, *, final: bool = True, exhausted: bool = False) -> dict:
    target = bid._Target(campaign_id=637511, keyword="soda", min_bid=100,
                         campaign_name="Soda KW (Pune)", id="abc", target_position=1)
    seen = {"rows": [], "settled": {}, "bumped": []}

    async def write_run_log(rows):
        seen["rows"].extend(rows)

    async def mark_settled(kind, stamps):
        seen["settled"].update(stamps)

    async def bump_settle_attempts(kind, ids):
        ids = list(ids)
        seen["bumped"].extend(ids)
        return ids if exhausted else []

    patches = {
        (bid, "get_adapter"): lambda platform: adapter,
        (repo, "get_advertiser"): _async_const(19802), (repo, "write_bid_runtime"): _async_noop,
        (repo, "write_run_log"): write_run_log, (repo, "mark_settled"): mark_settled,
        (repo, "bump_settle_attempts"): bump_settle_attempts,
    }
    originals = {key: getattr(*key) for key in patches}
    for (module, name), fake_fn in patches.items():
        setattr(module, name, fake_fn)
    try:
        asyncio.run(bid._floor_bids(
            _TENANT, "blinkit", [target], run_id="run", dry_run=False,
            phrase="the window closed", empty_note="",
            settle_closes={"abc": CLOSE} if final else {}))
    finally:
        for (module, name), original in originals.items():
            setattr(module, name, original)
    seen["lifecycle"] = [r for r in seen["rows"] if r["action"] in lifecycle.ACTIONS]
    return seen


def test_a_final_reset_that_lands_is_recorded_as_finished_and_latched():
    adapter = _BidAdapter(current=300)
    seen = _floor(adapter)
    assert adapter.writes == [("soda", 100)]
    [row] = seen["lifecycle"]
    assert row["action"] == lifecycle.SETTLED and row["keyword"] == "soda" and row["rule_id"] == "abc"
    assert seen["settled"]["abc"] >= CLOSE, "the latch must cover the ending it tore down"


def test_a_bid_already_at_its_floor_is_a_teardown_that_landed():
    adapter = _BidAdapter(current=100)
    seen = _floor(adapter)
    assert adapter.writes == [], "no PUT for a bid that is already there"
    assert [r["action"] for r in seen["lifecycle"]] == [lifecycle.SETTLED]


def test_a_final_reset_rejected_on_its_last_attempt_is_recorded_once():
    seen = _floor(_BidAdapter(current=300, accept=False), exhausted=True)
    assert seen["bumped"] == ["abc"] and seen["settled"] == {}
    [row] = seen["lifecycle"]
    assert row["action"] == lifecycle.SETTLE_FAILED and row["success"] is False


def test_an_ordinary_window_end_records_nothing_about_the_lifecycle():
    """A recurring rule's nightly reset is not its final teardown."""
    seen = _floor(_BidAdapter(current=300), final=False)
    assert seen["lifecycle"] == [] and seen["settled"] == {} and seen["bumped"] == []


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
    print(f"\n{len(tests) - failed}/{len(tests)} lifecycle-history tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
