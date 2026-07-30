"""Unit tests for the advertiser account guardrail (B3) — no real Blinkit.

Run standalone:  python -m campaign_manager.tests.test_advertiser

The live-write account is stored PER-TENANT and injected onto the client so the write
sends it. These fakes stand in for the client/adapter; the key test proves a budget write
actually carries the injected advertiser id.
"""
import asyncio

from campaign_manager import writes
from campaign_manager.marketplaces.blinkit import adapter


def _r(coro):
    return asyncio.run(coro)


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

    async def update_campaign(self, cid, changes, *, empty_pids=False, advertiser_id=None):
        self.captured = advertiser_id
        return {"success": True}


class FakeAdapter:
    def set_advertiser(self, client, adv):
        client.cm_advertiser_id = int(adv)


class Obj:
    pass


def test_resolve_returns_derived():
    assert _r(adapter.resolve_advertiser(DeriveClient(234))) == 234


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
