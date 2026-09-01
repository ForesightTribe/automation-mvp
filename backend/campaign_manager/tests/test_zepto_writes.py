"""The Zepto write guard: exactly one field may change, or nothing is sent.

This is the test that matters most in the Zepto adapter. Budget and bid are both a
PUT of the WHOLE campaign, so a wrong payload does not fail — it silently rewrites
geo targeting, the product list, or another keyword's bid. The guard exists to make
that impossible; these tests exist to prove the guard actually fires.

The fixtures are the same real captures the golden translate test uses.

    python -m campaign_manager.tests.test_zepto_writes
"""
import asyncio

from campaign_manager.marketplaces.zepto import adapter, client as zc
from campaign_manager.tests.test_zepto_translate import (
    CAMPAIGN_ID, GET_DETAIL, TARGETING_OPTIONS,
)


class _FakeClient:
    """Serves the captured detail and records what would be PUT."""

    def __init__(self, detail=None):
        self.brand_ids = ["b9cea5fc-da5f-4045-9b67-c07831733746"]
        self.detail = detail or GET_DETAIL
        self.sent = None

    @property
    def brand_id(self):
        return self.brand_ids[0]


def _install(monkey_detail=None):
    """Point the client module's network calls at the fixtures."""
    async def get_detail(client, campaign_id):
        return monkey_detail or client.detail

    async def get_options(client):
        return TARGETING_OPTIONS

    async def update(client, campaign_id, payload):
        client.sent = payload
        return {"message": "Campaign updated successfully"}

    zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign = (
        get_detail, get_options, update)


_ORIG = (zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign)


def _restore():
    zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign = _ORIG


def test_budget_write_sends_exactly_one_changed_field():
    _install()
    try:
        c = _FakeClient()
        asyncio.run(adapter.apply_budget(c, CAMPAIGN_ID, 700))
        assert c.sent is not None, "nothing was sent"
        assert c.sent["daily_budget"] == 700
        # Everything else must be the campaign as it was.
        assert c.sent["keyword_targeting"][0]["bid_value"] == 10
        assert c.sent["geo_targeting"]["type"] == "ALL"
        assert len(c.sent["geo_targeting"]["city"]["include"]) == 9
        assert c.sent["product_config"]["product_variant_ids"] == [
            "4770571e-2278-4efa-a152-9e5664eaae0b"]
    finally:
        _restore()


def test_bid_write_touches_only_the_named_keyword():
    _install()
    try:
        c = _FakeClient()
        asyncio.run(adapter.apply_bid(c, CAMPAIGN_ID, "pink toffee", 14,
                                      match_type="EXACT"))
        assert c.sent["keyword_targeting"][0]["bid_value"] == 14
        assert c.sent["daily_budget"] == GET_DETAIL["daily_budget"]
    finally:
        _restore()


def test_bid_write_refuses_an_absent_keyword():
    """Adding a keyword is not a bid change. Writing one in would silently expand
    what the campaign targets."""
    _install()
    try:
        c = _FakeClient()
        try:
            asyncio.run(adapter.apply_bid(c, CAMPAIGN_ID, "not a keyword", 14))
        except RuntimeError as e:
            assert "no keyword" in str(e)
            assert c.sent is None, "must not send anything"
        else:
            raise AssertionError("an unknown keyword must refuse the write")
    finally:
        _restore()


def test_bid_write_distinguishes_match_types():
    """Same text, different match type = a different bid target. Writing to the
    wrong one would move a bid nobody asked to move."""
    detail = {**GET_DETAIL, "keyword_config": [
        {"keyword": "pink toffee", "match_type": "EXACT", "bid_value": 10,
         "is_negative": False},
        {"keyword": "pink toffee", "match_type": "BROAD", "bid_value": 4,
         "is_negative": False},
    ]}
    _install(detail)
    try:
        c = _FakeClient(detail)
        asyncio.run(adapter.apply_bid(c, CAMPAIGN_ID, "pink toffee", 9,
                                      match_type="BROAD"))
        sent = {(k["text"], k["match_type"]): k["bid_value"]
                for k in c.sent["keyword_targeting"]}
        assert sent == {("pink toffee", "EXACT"): 10, ("pink toffee", "BROAD"): 9}
    finally:
        _restore()


def test_guard_refuses_when_the_mutation_touches_a_second_field():
    """The core safety property. A mutation that changes more than intended must
    send NOTHING — this is what stands between a budget edit and a wiped campaign."""
    _install()
    try:
        c = _FakeClient()

        def greedy(payload):
            payload["daily_budget"] = 700
            payload["geo_targeting"]["type"] = "MANUAL"   # collateral damage

        try:
            asyncio.run(adapter._put_one_field(
                c, CAMPAIGN_ID, ".daily_budget", greedy))
        except RuntimeError as e:
            assert "REFUSED" in str(e)
            assert "geo_targeting" in str(e), "the reason should name what moved"
            assert c.sent is None, "a refused write must send nothing"
        else:
            raise AssertionError("a multi-field mutation must be refused")
    finally:
        _restore()


def test_guard_refuses_a_mutation_that_changes_nothing():
    """A no-op reaching the adapter means the caller's intent was not expressed —
    better to refuse than to spend a write proving nothing."""
    _install()
    try:
        c = _FakeClient()
        try:
            asyncio.run(adapter._put_one_field(
                c, CAMPAIGN_ID, ".daily_budget", lambda p: None))
        except RuntimeError as e:
            assert "no change" in str(e)
            assert c.sent is None
        else:
            raise AssertionError("a no-op mutation must be refused")
    finally:
        _restore()


def test_status_write_ignores_budget_and_maps_vocabulary():
    """Blinkit needs a budget to restart because it re-submits the campaign; Zepto's
    activate restores its own. Accepting the argument keeps the contract; using it
    would be wrong."""
    seen = {}

    async def fake_status(client, campaign_id, *, pause):
        seen["pause"] = pause
        return {"message": "ok"}

    orig = zc.set_status
    zc.set_status = fake_status
    try:
        c = _FakeClient()
        asyncio.run(adapter.apply_status(c, CAMPAIGN_ID, "paused"))
        assert seen["pause"] is True
        asyncio.run(adapter.apply_status(c, CAMPAIGN_ID, "running", budget=999))
        assert seen["pause"] is False
        try:
            asyncio.run(adapter.apply_status(c, CAMPAIGN_ID, "sideways"))
        except RuntimeError as e:
            assert "unknown target status" in str(e)
        else:
            raise AssertionError("an unknown status must be refused")
    finally:
        zc.set_status = orig


def test_platform_budget_floor_is_declared_for_policy_to_enforce():
    """Zepto publishes a ₹500 minimum. The adapter declares it; writes.py enforces
    it, so a sub-minimum target is skipped with a reason rather than 400ing."""
    from campaign_manager import writes
    assert adapter.MIN_BUDGET == 500
    assert writes.budget_out_of_bounds(300, min_budget=adapter.MIN_BUDGET)
    assert writes.budget_out_of_bounds(500, min_budget=adapter.MIN_BUDGET) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto-write tests passed.")
