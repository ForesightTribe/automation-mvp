"""Pause / Resume / Reset / Delete — the rules that decide whether an action makes sense.

The shape being enforced (2026-09-07):

  * A bid rule is `active` or `paused`. There is no `stopped`; it was mechanically
    identical to `paused` and gave the UI a button with no undo.
  * **Pause** freezes everything and deliberately does NOT lower the bid.
  * **Resume** discards everything the engine learned, keeps `updated_at`, and repairs a
    window that ended during the pause.
  * **Reset** is refused only while the rule is RUNNING — including, importantly, allowed
    on an ENDED rule, which is the one case that can otherwise never be fixed: a rule
    paused across its window end lost its de-escalation and cannot be resumed.
  * **Delete** works with or without a reset.

    python -m campaign_manager.tests.test_lifecycle_actions
"""
import asyncio
from datetime import datetime, timedelta

from app.services import campaign_manager_service as svc
from campaign_manager import bid, repo


NOW = datetime(2026, 9, 7, 14, 0)
TENANT = "a870fd8d-7373-47ec-ad69-5dd08ce35542"


class _Rule:
    """A bid rule with only the fields the lifecycle gates read."""

    def __init__(self, **over):
        self.id = "f830ff0b9e0a4e5da8457c6c904bf0a6"
        self.tenant_id = TENANT
        self.campaign_id, self.campaign_name = 637511, "Soda KW (Pune)"
        self.keyword, self.match_type = "soda", "EXACT"
        self.min_bid, self.max_bid, self.target_position = 100, None, 1
        self.state, self.type, self.date = "active", "recurring", None
        self.start_time, self.stop_time = "09:00", "21:00"
        self.start_date, self.stop_date = None, None
        self.days = []
        # Fields `BidRuleOut` needs to serialise the response.
        self.platform, self.active = "blinkit", True
        self.__dict__.update(over)
        self.lat, self.lon, self.location_name = 18.55, 73.93, "Borate Vasti"
        self.__dict__.update(over)


def _run(coro_fn, rule, **extra):
    """Call a service action against `rule`, with the DB and the queue stubbed out."""
    calls = {"state": None, "cleared": False, "enqueued": [], "deleted": False,
             "reconciled": False}

    async def get_bid_rule(rule_id):
        return rule

    async def set_bid_state(rule_id, state):
        calls["state"] = state
        rule.state = state
        return rule

    async def clear_bid_runtime(rule_id):
        calls["cleared"] = True
        return True

    async def delete_bid_rule(rule_id):
        calls["deleted"] = True
        return True

    async def get_armed(tenant_id, platform="blinkit"):
        return True

    async def enqueue(session, *, job_type, tenant_id, params, priority=100):
        calls["enqueued"].append({"type": job_type, "params": params, "priority": priority})

        class _Job:
            id = "job-1"
        return _Job()

    async def _reconcile(session, tenant_id):
        calls["reconciled"] = True

    originals = (repo.get_bid_rule, repo.set_bid_state, repo.clear_bid_runtime,
                 repo.delete_bid_rule, repo.get_armed, svc.enqueue, svc._reconcile,
                 svc.now_ist)
    repo.get_bid_rule, repo.set_bid_state = get_bid_rule, set_bid_state
    repo.clear_bid_runtime, repo.delete_bid_rule = clear_bid_runtime, delete_bid_rule
    repo.get_armed, svc.enqueue, svc._reconcile = get_armed, enqueue, _reconcile
    svc.now_ist = lambda: NOW
    try:
        calls["result"] = asyncio.run(coro_fn(None, TENANT, rule.id, **extra))
        calls["error"] = None
    except svc.StateError as e:
        calls["result"], calls["error"] = None, str(e)
    finally:
        (repo.get_bid_rule, repo.set_bid_state, repo.clear_bid_runtime,
         repo.delete_bid_rule, repo.get_armed, svc.enqueue, svc._reconcile,
         svc.now_ist) = originals
    return calls


# ── the action matrix ───────────────────────────────────────────────────────

def test_pause_freezes_and_does_not_touch_the_bid():
    c = _run(svc.pause_bid_rule, _Rule())
    assert c["state"] == "paused" and c["reconciled"]
    assert c["enqueued"] == [], "pause must not write a bid — that is Reset's job"
    assert not c["cleared"], (
        "runtime must survive a pause: `updated_at` is what Resume reads to decide "
        "whether the window still counts as opened")


def test_pause_is_refused_on_an_ended_rule():
    ended = _Rule(type="once", date="2026-09-01")
    assert "already ended" in _run(svc.pause_bid_rule, ended)["error"]


def test_pause_is_refused_when_already_paused():
    assert "already paused" in _run(svc.pause_bid_rule, _Rule(state="paused"))["error"]


def test_resume_clears_what_the_engine_learned():
    c = _run(svc.resume_bid_rule, _Rule(state="paused"))
    assert c["state"] == "active" and c["cleared"] and c["reconciled"]


def test_resume_inside_the_window_does_not_reset():
    """14:00 sits inside 09:00-21:00 — the automation simply carries on."""
    c = _run(svc.resume_bid_rule, _Rule(state="paused"))
    assert c["enqueued"] == []


def test_resume_after_the_window_closed_repairs_the_missed_reset():
    """The gap pause creates: freezing removes the end-of-window reset, so a rule paused
    across its window end is still sitting on the bid the optimizer climbed to."""
    c = _run(svc.resume_bid_rule, _Rule(state="paused", start_time="01:00", stop_time="02:00"))
    assert len(c["enqueued"]) == 1
    job = c["enqueued"][0]
    assert job["type"] == "cm.set_bid" and job["params"]["cpm"] == "100"


def test_resume_is_refused_when_already_running():
    assert "already running" in _run(svc.resume_bid_rule, _Rule())["error"]


def test_resume_is_refused_on_an_ended_rule():
    ended = _Rule(state="paused", type="once", date="2026-09-01")
    assert "already ended" in _run(svc.resume_bid_rule, ended)["error"]


def test_reset_is_refused_while_the_rule_is_running():
    """Refusing beats spending a write the next tick undoes 15 minutes later."""
    assert "running right now" in _run(svc.reset_bid_rule, _Rule())["error"]


def test_reset_is_allowed_on_a_paused_rule():
    c = _run(svc.reset_bid_rule, _Rule(state="paused"))
    assert c["error"] is None and c["enqueued"][0]["type"] == "cm.set_bid"


def test_reset_is_allowed_before_the_window_opens():
    """Active but out of window — nothing will undo the reset until the window opens, and
    the window opens at the floor anyway."""
    c = _run(svc.reset_bid_rule, _Rule(start_time="20:00", stop_time="23:00"))
    assert c["error"] is None and len(c["enqueued"]) == 1


def test_reset_is_allowed_on_an_ended_rule():
    """THE case that must not be gated. A rule paused across its window end never got its
    de-escalation, and Resume is refused on an ended rule — so Reset is the only way left
    to bring that bid down."""
    ended = _Rule(state="paused", type="once", date="2026-09-01")
    c = _run(svc.reset_bid_rule, ended)
    assert c["error"] is None and len(c["enqueued"]) == 1


def test_reset_jumps_the_queue():
    c = _run(svc.reset_bid_rule, _Rule(state="paused"))
    assert c["enqueued"][0]["priority"] == 10, (
        "a person is waiting on this; the default 100 would sit behind scheduled work")


def test_delete_without_reset_writes_no_bid():
    c = _run(svc.delete_bid_rule, _Rule(), reset=False)
    assert c["deleted"] and c["enqueued"] == []


def test_delete_with_reset_enqueues_before_deleting():
    """Order matters: a refused enqueue must leave the rule (and its bid) alone rather than
    orphaning a high bid with no automation left to lower it."""
    c = _run(svc.delete_bid_rule, _Rule(), reset=True)
    assert c["deleted"] and len(c["enqueued"]) == 1
    assert c["enqueued"][0]["params"]["keyword"] == "soda"


def test_delete_with_reset_works_on_a_running_rule():
    """Unlike Reset, no gate — the rule is about to stop existing, so nothing can undo it."""
    c = _run(svc.delete_bid_rule, _Rule(), reset=True)
    assert c["error"] is None and c["deleted"]


# ── the reset job carries values, not a rule id ─────────────────────────────

def test_the_reset_job_targets_the_rules_own_marketplace():
    """The CM API is Blinkit-only, but `get_bid_rule` looks up by id and does not filter by
    platform — so a Zepto rule reaching Reset must not be enqueued as a Blinkit job. The
    argv builder defaults `marketplace` to blinkit, which would send a Zepto campaign id to
    the wrong ad account with live writes armed."""
    c = _run(svc.reset_bid_rule, _Rule(state="paused", platform="zepto", campaign_id=2427461))
    assert c["enqueued"][0]["params"]["marketplace"] == "zepto"


def test_the_reset_job_is_self_contained():
    """Delete + reset removes the rule before the job runs, so anything that had to look
    one up would find nothing. Params must fully describe the write."""
    c = _run(svc.reset_bid_rule, _Rule(state="paused"))
    params = c["enqueued"][0]["params"]
    for key in ("campaign", "keyword", "cpm", "match_type"):
        assert key in params, f"{key} must ride in the job, not be looked up later"
    assert "rule" not in params and "rule_id" not in params


def test_a_target_can_stand_in_for_a_rule():
    """`_floor_bids` is shared by the window-close reset (which has rules) and the
    on-demand one (which may not), so the target's field names must match a rule's."""
    t = bid._Target(campaign_id=1, keyword="soda", min_bid=100)
    for field in ("campaign_id", "campaign_name", "keyword", "id", "target_position"):
        assert hasattr(t, field), f"_record_run_blocked reads .{field} off these"


# ── the `updated_at` invariant ──────────────────────────────────────────────

def test_resume_never_clears_updated_at():
    """The load-bearing detail. `runtime.updated_at >= window_start` is how the engine
    decides whether this window has already been opened, so Resume keeping it is what
    makes both cases correct with no special-casing: resumed inside the same window →
    carry on from the live bid; resumed after a new window started → re-open at the floor."""
    assert "updated_at" not in repo._RUNTIME_MEMORY


def test_resume_does_not_go_through_write_bid_runtime():
    """`write_bid_runtime` stamps `updated_at = now()` on every call, so using it here
    would make every resume look mid-window and silently skip the floor."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(repo.clear_bid_runtime).lstrip()).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body   # code only, not the docstring
    code = "\n".join(ast.unparse(node) for node in body)
    assert "write_bid_runtime" not in code
    assert "updated_at" not in code, "the body must never assign updated_at"


# ── state vocabulary ────────────────────────────────────────────────────────

def test_stopped_is_gone_from_the_lifecycle():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    routes = (root / "app" / "routes" / "campaign_manager.py").read_text(encoding="utf-8")
    assert "/stop" not in routes, "the Stop endpoint was removed with the state"
    assert '"stopped"' not in (root / "app" / "services" /
                               "campaign_manager_service.py").read_text(
        encoding="utf-8").split("# ── Pause / Resume / Reset")[1]


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} lifecycle tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
