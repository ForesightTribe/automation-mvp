"""Unit tests for refusal reasons reaching the History row (`writes._refused`).

The reason a write did not land always existed — every guardrail branch computes one and
hands it to Cloud Logging. But `apply_*` returned a bare bool, so it stopped there, and the
callers wrote rows saying what they already knew: `set_budget` recorded the literal string
"set-budget", the engines recorded the RULE that prompted the write. History could show
THAT nothing happened and never why.

2026-09-15 made it concrete. Blinkit began rejecting every UPDATE with "Start Date of
Campaign is not allowed to be changed" (a date-formatting bug in `build.fmt_date`), and the
refused rows in `cm_run_log` read `set-budget` — the one sentence that identified it, lost.

Run:  python -m campaign_manager.tests.test_refusal_reasons
"""
import asyncio

from campaign_manager import writes
from campaign_manager.set_activation import _reason as activation_reason
from campaign_manager.set_budget import _reason as budget_reason

REJECTED = "Start Date of Campaign is not allowed to be changed"


class _Adapter:
    """Accepts or refuses every write, as constructed."""
    MIN_BUDGET = MAX_BUDGET = MIN_BID = MAX_BID = None
    RESUME_RESUBMITS = True

    def __init__(self, resp):
        self._resp = resp

    async def apply_budget(self, client, campaign_id, budget):
        return self._resp

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type):
        return self._resp

    async def apply_status(self, client, campaign_id, target, *, budget=None):
        return self._resp


def _budget(resp, **kw):
    out = {}
    defaults = dict(run_id="t", campaign_id=1, target=210, current=220,
                    dry_run=False, recent_writes=0)
    defaults.update(kw)
    ok = asyncio.run(writes.apply_budget(_Adapter(resp), None, outcome=out, **defaults))
    return ok, out.get("reason")


def _status(resp, **kw):
    out = {}
    defaults = dict(run_id="t", campaign_id=1, target="paused", current="running",
                    dry_run=False, recent_writes=0)
    defaults.update(kw)
    ok = asyncio.run(writes.apply_status(_Adapter(resp), None, outcome=out, **defaults))
    return ok, out.get("reason")


def _bid(resp, **kw):
    out = {}
    defaults = dict(run_id="t", campaign_id=1, keyword="soda", new_cpm=450,
                    current_cpm=200, min_bid=100, max_bid=900, dry_run=False,
                    recent_writes=0)
    defaults.update(kw)
    ok = asyncio.run(writes.apply_bid(_Adapter(resp), None, outcome=out, **defaults))
    return ok, out.get("reason")


# ── The marketplace's own words ──────────────────────────────────────────────

def test_the_marketplace_reason_is_captured():
    # The exact production case: Blinkit refused, and this is the sentence that names why.
    ok, why = _budget({"status": False, "message": REJECTED})
    assert ok is False
    assert why == REJECTED


def test_a_refused_status_write_captures_its_reason():
    ok, why = _status({"status": False, "message": "campaign is not restartable"})
    assert ok is False and why == "campaign is not restartable"


def test_a_refused_bid_write_captures_its_reason():
    ok, why = _bid({"status": False, "message": "cpm below floor"})
    assert ok is False and "cpm below floor" in why


def test_an_empty_refusal_still_says_something():
    # A reply with no message at all: "no reason given" beats a blank row, because it says
    # the refusal came back empty rather than that we lost it.
    ok, why = _budget({"status": False})
    assert ok is False and "no reason given" in why


# ── Guardrail trips, which never reach the marketplace ───────────────────────

def test_a_noop_says_so():
    ok, why = _budget({"status": True}, target=210, current=210)
    assert ok is False and "already" in why


def test_out_of_bounds_says_so():
    ok, why = _budget({"status": True}, target=0)
    assert ok is False and "below min" in why


def test_the_rate_limit_says_so():
    ok, why = _budget({"status": True}, recent_writes=99)
    assert ok is False and "rate limit" in why


def test_a_terminal_state_says_so():
    ok, why = _status({"status": True}, target="running", current="ended", budget=500)
    assert ok is False and "COMPLETED" in why


def test_on_hold_explains_the_budget():
    # The one a person most needs: ON_HOLD is not "stopped", and the fix is a budget raise.
    ok, why = _status({"status": True}, target="running", current="held", budget=500)
    assert ok is False and "budget" in why


# ── A write that LANDS records nothing ───────────────────────────────────────

def test_a_successful_write_records_no_reason():
    for ok, why in (_budget({"status": True}), _status({"status": True}),
                    _bid({"status": True})):
        assert ok is True and why is None


def test_a_dry_run_records_no_reason():
    for ok, why in (_budget({"status": True}, dry_run=True),
                    _status({"status": True}, dry_run=True),
                    _bid({"status": True}, dry_run=True)):
        assert ok is True and why is None


def test_the_outcome_param_is_optional():
    # Nine call sites read the bool; none of them must be forced to pass a dict.
    assert asyncio.run(writes.apply_budget(
        _Adapter({"status": True}), None, run_id="t", campaign_id=1, target=210,
        current=220, dry_run=False, recent_writes=0)) is True


# ── What the History row ends up saying ──────────────────────────────────────

def test_the_history_row_carries_the_cause_alone():
    # No "not applied" prefix: the UI already frames it as "Nothing changed - {reason}"
    # and History has an Action column reading `skip`. Prefixing says it twice.
    assert budget_reason(False, {"reason": REJECTED}) == REJECTED
    assert not budget_reason(False, {"reason": REJECTED}).startswith("not applied")


def test_a_landed_row_says_what_was_done_in_words():
    # It used to be the job's name — "set-budget" — which tells a client nothing.
    assert budget_reason(True, {}, 450) == "the budget was set to ₹450 on request"
    done = "the campaign was started on request"
    assert activation_reason(True, {}, done) == done


def test_a_missing_reason_never_renders_empty():
    assert budget_reason(False, {}) == "no reason given"
    assert activation_reason(False, {}, "the campaign was stopped on request") == "no reason given"


# ── Not needed is not refused ────────────────────────────────────────────────
#
# "The bid is already ₹200" is the choke point answering correctly, not a failure. Filed
# unsuccessful it showed in red under Failed; filed as a successful `skip` it sat beside the
# real refusals, indistinguishable from them. It is a `no-op`, and only it is.

def _outcome(fn, resp, **kw):
    out = {}
    fn_kw = {"budget": dict(run_id="t", campaign_id=1, target=210, current=220),
             "status": dict(run_id="t", campaign_id=1, target="paused", current="running"),
             "bid": dict(run_id="t", campaign_id=1, keyword="soda", new_cpm=450,
                         current_cpm=200, min_bid=100, max_bid=900)}[fn]
    fn_kw.update(dry_run=False, recent_writes=0)
    fn_kw.update(kw)
    call = {"budget": writes.apply_budget, "status": writes.apply_status,
            "bid": writes.apply_bid}[fn]
    asyncio.run(call(_Adapter(resp), None, outcome=out, **fn_kw))
    return out


def test_an_already_correct_value_is_marked_not_needed():
    assert writes.not_needed(_outcome("budget", {"status": True}, current=210))
    assert writes.not_needed(_outcome("bid", {"status": True}, current_cpm=450))
    assert writes.not_needed(_outcome("status", {"status": True}, current="paused"))


def test_a_refusal_is_never_marked_not_needed():
    assert not writes.not_needed(_outcome("budget", {"status": False, "message": REJECTED}))
    assert not writes.not_needed(_outcome("bid", {"status": True}, recent_writes=99))
    assert not writes.not_needed(_outcome("status", {"status": True}, current="ended"))
    assert not writes.not_needed(None) and not writes.not_needed({})


def test_every_engine_files_the_three_outcomes_the_same_way():
    """Landed / not needed / refused → (action, success) — identical across the writers, so
    the Execution logs can read `success` as "did what it meant to"."""
    from campaign_manager import bid, budget, set_activation, set_budget
    noop = {"reason": "the value is already X", "noop": True}
    refused = {"reason": REJECTED, "noop": False}
    verdicts = [
        lambda ok, o: bid._write_verdict(ok, None, o, mp="Blinkit", landed="apply", why="w")[:2],
        lambda ok, o: budget._verdict(ok, o, "w")[:2],
        lambda ok, o: set_budget._verdict(ok, o, 450)[:2],
        lambda ok, o: set_activation._verdict(ok, o, "w")[:2],
    ]
    for v in verdicts:
        assert v(True, {}) == ("apply", True)
        assert v(False, noop) == ("no-op", True)
        assert v(False, refused) == ("skip", False)


def test_a_refused_row_carries_the_refusal_after_the_decision():
    from campaign_manager import bid
    action, success, reason = bid._write_verdict(
        False, None, {"reason": "rate limit (12 recent writes)", "noop": False},
        mp="Blinkit", landed="apply", why="raising to ₹605 because position 13 is worse")
    assert (action, success) == ("skip", False)
    assert reason.startswith("raising to ₹605") and "not applied: rate limit" in reason


def test_a_write_that_could_not_be_sent_is_an_error():
    from campaign_manager import bid
    action, success, reason = bid._write_verdict(
        False, RuntimeError("boom"), {}, mp="Blinkit", landed="open", why="the window opened")
    assert (action, success) == ("error", False) and "could not be sent to Blinkit" in reason


def _run() -> int:
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
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} refusal-reason tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
