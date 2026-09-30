"""Zepto keyword-bid automations are OFF for now (2026-09-29, Deepansh — "option C").

Zepto's firewall refuses the VM's address for the shopper search the bid engine needs, and
a residential proxy was judged not worth its cost yet. Budget automations, start/stop and
one-time ops are unaffected. These pin the switch: refused on create AND on resume (API and
CLI both go through the repo), Blinkit untouched, and `CM_ZEPTO_KEYWORD_BIDDING` turns it
back on. No DB, no Zepto.

    python -m campaign_manager.tests.test_zepto_keyword_bidding_off
"""
import asyncio
import uuid
from types import SimpleNamespace

from campaign_manager import config, repo
from campaign_manager.marketplaces import keyword_bidding_refusal
from campaign_manager.tests._zepto_flags import zepto_bidding_on

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")


def test_zepto_keyword_bidding_is_off_by_default():
    assert config.ZEPTO_KEYWORD_BIDDING is False
    said = keyword_bidding_refusal("zepto")
    assert said and "Zepto" in said and "Budget automations" in said


def test_blinkit_keyword_bidding_is_untouched():
    assert keyword_bidding_refusal("blinkit") is None


@zepto_bidding_on
def test_the_setting_turns_it_back_on():
    assert keyword_bidding_refusal("zepto") is None


def test_creating_a_zepto_keyword_automation_is_refused_before_anything_else():
    """Refused first — no catalogue lookup, no store placement, nothing written."""
    saved = repo.require_automatable

    async def _must_not_run(*a, **k):
        raise AssertionError("the refusal must come before any other check")

    repo.require_automatable = _must_not_run
    try:
        try:
            asyncio.run(repo.create_bid_rule(TENANT, "zepto", 2427461, "Tech Test",
                                             "bread", 3, 10, 20))
        except repo.NotAutomatable as e:
            assert "Nothing was created" in str(e)
        else:
            raise AssertionError("a Zepto keyword automation must be refused")
    finally:
        repo.require_automatable = saved


class _Session:
    """Stands in for AsyncSessionLocal: hands back one paused Zepto rule, records commits."""

    def __init__(self, rule):
        self.rule, self.committed = rule, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, _model, _id):
        return self.rule

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        pass


def test_resuming_a_paused_zepto_keyword_automation_is_refused_and_it_stays_paused():
    rule = SimpleNamespace(id="r1", tenant_id=TENANT, platform="zepto", campaign_id=1,
                           keyword="bread", match_type="EXACT", state="paused", active=False)
    session = _Session(rule)
    saved = repo.AsyncSessionLocal
    repo.AsyncSessionLocal = lambda: session
    try:
        try:
            asyncio.run(repo.set_bid_state("r1", "active"))
        except repo.NotAutomatable as e:
            assert "stays paused" in str(e)
        else:
            raise AssertionError("resuming a Zepto keyword automation must be refused")
    finally:
        repo.AsyncSessionLocal = saved
    assert rule.state == "paused" and rule.active is False and not session.committed


def test_pausing_is_still_allowed():
    """Only turning bidding ON is refused — pausing never is."""
    rule = SimpleNamespace(id="r1", tenant_id=TENANT, platform="zepto", campaign_id=1,
                           keyword="bread", match_type="EXACT", state="active", active=True)
    session = _Session(rule)
    saved = repo.AsyncSessionLocal
    repo.AsyncSessionLocal = lambda: session
    try:
        asyncio.run(repo.set_bid_state("r1", "paused"))
    finally:
        repo.AsyncSessionLocal = saved
    assert rule.state == "paused" and session.committed


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
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
