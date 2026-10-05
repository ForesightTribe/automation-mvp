"""Unit tests for the advertiser account guardrail (B3) — no real Blinkit.

Run standalone:  python -m campaign_manager.tests.test_advertiser

The live-write account is stored PER-TENANT and injected onto the client so the write
sends it. These fakes stand in for the client/adapter; the key test proves a budget write
actually carries the injected advertiser id.
"""
import asyncio

from campaign_manager import writes
from campaign_manager.marketplaces.blinkit import adapter
from campaign_manager.marketplaces.blinkit.client import BlinkitClient

_CAMPAIGNS = "/adservice/v1/advertisers/campaigns"
_ADVERTISERS = "/adservice/v1/advertisers"


def _r(coro):
    return asyncio.run(coro)


def _client(campaigns_resp, advertisers_resp=None):
    """A real BlinkitClient whose network call is replaced, so `get_advertiser_id`'s own
    logic runs. Records every path it was asked for."""
    c = object.__new__(BlinkitClient)
    c.calls = []

    async def fake_fetch(method, path, body=None, **_):
        c.calls.append(path)
        if path == _CAMPAIGNS:
            return campaigns_resp
        if path == _ADVERTISERS:
            return advertisers_resp
        raise AssertionError(f"unexpected call {method} {path}")

    c._fetch = fake_fetch
    return c


def _raises(coro) -> str:
    try:
        _r(coro)
    except RuntimeError as e:
        return str(e)
    raise AssertionError("expected RuntimeError")


# The advertiser list exactly as Blinkit returned it for Sereko (2026-10-03), trimmed.
_ONE_ADVERTISER = {"success": True, "items": [
    {"id": 1996, "name": "SUSH ESSENTIALS PRIVATE LIMITED", "status": "ACTIVE"},
]}
# Sereko's campaign list: campaigns, but no advertiser_id anywhere.
_NO_ID = {"data": {"campaigns": [{"id": 1}]}}


class DeriveClient:
    """resolve_advertiser reads Blinkit's own derivation (get_advertiser_id)."""
    def __init__(self, adv):
        self._adv = adv

    async def get_advertiser_id(self):
        return self._adv


class WriteCaptureClient:
    """Captures the advertiser_id a budget write would send."""
    def __init__(self):
        self.captured = "unset"

    async def get_campaign_detail(self, cid):
        return ({"pacing_type": "DAILY"}, {})

    async def update_campaign(self, cid, changes, *, advertiser_id=None):
        self.captured = advertiser_id
        return {"success": True}


class FakeAdapter:
    def set_advertiser(self, client, adv):
        client.cm_advertiser_id = int(adv)


class Obj:
    pass


def test_resolve_returns_derived():
    assert _r(adapter.resolve_advertiser(DeriveClient(19802))) == 19802


def test_set_advertiser_sets_attr():
    c = Obj()
    adapter.set_advertiser(c, 19802)
    assert c.cm_advertiser_id == 19802


def test_arm_live_refuses_without_stored():
    try:
        _r(writes.arm_live(FakeAdapter(), Obj(), "run", None))
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_arm_live_sets_and_returns():
    c = Obj()
    assert _r(writes.arm_live(FakeAdapter(), c, "run", 19802)) == 19802
    assert c.cm_advertiser_id == 19802


def test_budget_write_sends_stored_advertiser():   # the "would-send" proof
    c = WriteCaptureClient()
    adapter.set_advertiser(c, 19802)
    _r(adapter.apply_budget(c, 574687, 800))
    assert c.captured == 19802


def test_budget_write_without_stored_sends_none():   # dry/unarmed path → falls back downstream
    c = WriteCaptureClient()
    _r(adapter.apply_budget(c, 574687, 800))
    assert c.captured is None


# ── get_advertiser_id: campaign list first, then a SINGLE-advertiser list ─────────────

def test_campaign_list_id_wins_without_a_second_call():   # Dobra's shape
    c = _client({"data": {"advertiser_id": 19802, "campaigns": []}})
    assert _r(c.get_advertiser_id()) == 19802
    assert c.calls == [_CAMPAIGNS]


def test_falls_back_to_the_sole_advertiser():   # Sereko's shape
    c = _client(_NO_ID, _ONE_ADVERTISER)
    assert _r(c.get_advertiser_id()) == 1996
    assert c.calls == [_CAMPAIGNS, _ADVERTISERS]


def test_refuses_to_pick_between_several_advertisers():   # an agency login across brands
    c = _client(_NO_ID, {"items": [{"id": 1996, "name": "SUSH ESSENTIALS"},
                                   {"id": 19802, "name": "DOBRA"}]})
    msg = _raises(c.get_advertiser_id())
    assert "2 advertisers" in msg and "1996 (SUSH ESSENTIALS)" in msg and "19802 (DOBRA)" in msg


def test_refuses_when_the_list_is_empty():
    assert "0 usable" in _raises(_client(_NO_ID, {"items": []}).get_advertiser_id())


def test_refuses_a_missing_list():
    assert "Refusing to guess" in _raises(_client(_NO_ID, {"success": False}).get_advertiser_id())


def test_rejects_ids_that_are_not_positive_ints():
    for bad in (0, -5, True, "1996", None, 1996.0):
        c = _client({"data": {"advertiser_id": bad}}, {"items": [{"id": bad}]})
        _raises(c.get_advertiser_id())


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
    print(f"\n{len(tests) - failed}/{len(tests)} advertiser-guardrail tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
