"""ZC-A2 — a Zepto write that fails must be ONE failed write, never a dead run.

The Zepto adapter used to raise a bare `RuntimeError` for every failure: the one-field
diff guard, a missing keyword, and any non-200 from the PUT. `writes.py` catches only
`WriteRefused` / `WriteUnverified`, and the budget engine wraps only the campaign READ —
so one refused Zepto budget write escaped the choke point and aborted the whole budget
run, skipping every campaign after it. Zepto's own reason never reached History.

Two things are pinned here:

  1. `zepto.client._write` sorts every outcome by "could this have changed the campaign?"
     — refused (nothing sent / Zepto said no), unverified (may have landed), or a dead
     session.
  2. The choke point resolves an unverified BUDGET or STATUS write by reading it back, the
     way it already did for bids — and a bid is read back under its own match type.

    python -m campaign_manager.tests.test_zepto_write_outcomes
"""
import asyncio

import httpx

from campaign_manager import writes
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import client as zc

_REQ = httpx.Request("PUT", "https://fcc.zepto.co.in/ads-bff/api/v1/campaigns/pla/2427461")


class _Client:
    """A ZeptoClient stand-in whose one request returns — or raises — what it is given."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.brand_id = "b9cea5fc-da5f-4045-9b67-c07831733746"
        self.brand_ids = [self.brand_id]

    async def request(self, method, path, **kw):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _resp(status, *, json=None, text=None):
    if json is not None:
        return httpx.Response(status, json=json, request=_REQ)
    return httpx.Response(status, text=text or "", request=_REQ)


def _write(outcome):
    return asyncio.run(zc.update_campaign(_Client(outcome), 2427461, {"daily_budget": 700}))


def _raises(outcome, exc_type):
    try:
        _write(outcome)
    except exc_type as e:
        return str(e)
    except Exception as e:                                  # the wrong kind is a failure
        raise AssertionError(f"expected {exc_type.__name__}, got {type(e).__name__}: {e}")
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


# ── 1. classification ───────────────────────────────────────────────────────

def test_a_clean_200_returns_the_body():
    assert _write(_resp(200, json={"message": "Campaign updated successfully"})) == {
        "message": "Campaign updated successfully"}


def test_a_4xx_is_a_refusal_carrying_zeptos_own_words():
    """The sentence a person needs in History — not "HTTP 400"."""
    msg = _raises(_resp(400, json={"message": "keyword bid validation failed: keyword "
                                              "'pink toffee' (EXACT) bid 8.00 is below "
                                              "minimum bid 10.00"}), writes.WriteRefused)
    assert "below minimum bid 10.00" in msg


def test_a_4xx_with_no_json_still_says_something():
    assert "not allowed" in _raises(_resp(422, text="not allowed"), writes.WriteRefused)


def test_a_5xx_may_have_landed():
    """Zepto's gateway answers 500 when its upstream is slow, and the upstream may finish."""
    _raises(_resp(500, text="Internal Server Error"), writes.WriteUnverified)


def test_a_200_that_is_not_json_may_have_landed():
    _raises(_resp(200, text="<html>ok</html>"), writes.WriteUnverified)


def test_a_read_timeout_may_have_landed():
    _raises(httpx.ReadTimeout("read timed out", request=_REQ), writes.WriteUnverified)


def test_a_connect_failure_sent_nothing():
    _raises(httpx.ConnectError("refused", request=_REQ), writes.WriteRefused)


def test_a_waf_challenge_sent_nothing():
    """202/429 come from CloudFront before the origin sees the request."""
    _raises(_resp(202), writes.WriteRefused)
    _raises(_resp(429), writes.WriteRefused)


def test_a_401_is_a_dead_session_not_a_verdict():
    """Every later write in the run would fail the same way — the one outcome that should
    still stop a run."""
    _raises(_resp(401, json={"message": "unauthorized"}), writes.SessionExpired)


def test_pause_and_activate_are_classified_the_same_way():
    try:
        asyncio.run(zc.set_status(_Client(_resp(400, json={"error": "campaign has ended"})),
                                  2427461, pause=False))
    except writes.WriteRefused as e:
        assert "campaign has ended" in str(e)
    else:
        raise AssertionError("a refused activate must be a WriteRefused")


def test_a_failed_pre_write_read_is_a_refusal():
    """The adapter re-reads the campaign before every PUT. If that read fails, nothing was
    sent — one failed write, not a crash."""
    orig = zc.get_campaign_detail

    async def broken(client, campaign_id):
        raise RuntimeError("Zepto GET /ads-bff/api/v1/campaigns/pla/2427461 -> 503")

    zc.get_campaign_detail = broken
    try:
        asyncio.run(zad.apply_budget(_Client(None), 2427461, 700))
    except writes.WriteRefused as e:
        assert "nothing was sent" in str(e)
    else:
        raise AssertionError("a failed pre-write read must refuse the write")
    finally:
        zc.get_campaign_detail = orig


# ── 2. the choke point survives and reads back ──────────────────────────────

class _Adapter:
    """What `writes.apply_budget` / `apply_status` consult. `raise_` is what the write
    raises; `live_*` is what a read-back reports afterwards. Zepto-shaped: a resume is a
    flip, not a re-submission, so it carries no budget."""

    RESUME_RESUBMITS = False

    def __init__(self, raise_, *, live_budget=None, live_status=None):
        self.raise_ = raise_
        self.live_budget, self.live_status = live_budget, live_status

    async def apply_budget(self, client, campaign_id, budget):
        raise self.raise_

    async def apply_status(self, client, campaign_id, target, *, budget=None):
        raise self.raise_

    async def read_budget(self, client, campaign_id):
        return self.live_budget

    async def read_status(self, client, campaign_id):
        return self.live_status


def _budget(adapter, outcome=None):
    return asyncio.run(writes.apply_budget(
        adapter, None, run_id="t", campaign_id=2427461, target=700, current=600,
        dry_run=False, outcome=outcome))


def _status(adapter, target="running"):
    return asyncio.run(writes.apply_status(
        adapter, None, run_id="t", campaign_id=2427461, target=target, current="paused",
        dry_run=False))


def test_a_refused_budget_write_returns_false_with_the_reason():
    """The bug itself: this used to raise out of the choke point and end the run."""
    outcome: dict = {}
    ok = _budget(_Adapter(writes.WriteRefused("Zepto refused to update campaign 2427461: "
                                              "daily budget cannot be below spend")), outcome)
    assert ok is False
    assert "below spend" in outcome["reason"]


def test_an_unverified_budget_write_that_landed_counts():
    assert _budget(_Adapter(writes.WriteUnverified("no answer"), live_budget=700)) is True


def test_an_unverified_budget_write_that_did_not_land_does_not():
    outcome: dict = {}
    assert _budget(_Adapter(writes.WriteUnverified("no answer"), live_budget=600),
                   outcome) is False
    assert "did not change" in outcome["reason"]


def test_an_unverified_start_that_landed_counts():
    assert _status(_Adapter(writes.WriteUnverified("no answer"), live_status="running")) is True


def test_a_start_that_came_back_held_did_land():
    """Live but held for budget/wallet — the start happened; lifting the hold is not ours."""
    assert _status(_Adapter(writes.WriteUnverified("no answer"), live_status="held")) is True


def test_an_unverified_start_that_did_not_land_does_not():
    assert _status(_Adapter(writes.WriteUnverified("no answer"), live_status="paused")) is False


def test_a_refused_status_write_returns_false():
    assert _status(_Adapter(writes.WriteRefused("campaign has ended"))) is False


class _BidAdapter:
    """Zepto bids one keyword under several match types. The text-keyed read collapses
    them; the pair-keyed one does not."""

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        raise writes.WriteUnverified("no answer")

    async def read_bids(self, client, campaign_id):
        return {"soda": 150}                    # PHRASE's value won the collapse

    async def read_bids_by_match(self, client, campaign_id):
        return {("soda", "EXACT"): 100, ("soda", "PHRASE"): 150}


def _bid(match_type):
    return asyncio.run(writes.apply_bid(
        _BidAdapter(), None, run_id="t", campaign_id=1, keyword="soda", new_cpm=150,
        current_cpm=100, min_bid=10, max_bid=1000, match_type=match_type, dry_run=False))


def test_a_bid_is_verified_under_its_own_match_type():
    """EXACT was written to ₹150 and did not land; PHRASE happens to sit at ₹150. Reading
    back by text would have 'confirmed' a change that never happened."""
    assert _bid("EXACT") is False
    assert _bid("PHRASE") is True


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
    print(f"\n{len(tests) - failed}/{len(tests)} zepto write-outcome tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
