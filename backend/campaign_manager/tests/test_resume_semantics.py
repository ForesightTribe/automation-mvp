"""Resume is NOT the same operation on both marketplaces.

Blinkit's resume is a RESTART — a full campaign re-submission that rewrites budget,
keywords, bids and dates. It therefore needs a budget, and `writes.apply_status`
subjects that budget to the same bounds guardrail a budget write gets.

Zepto's resume is a dedicated endpoint that flips the campaign back on with its own
values intact. Nothing is re-submitted and no budget is carried.

Before the adapters declared this, `writes.apply_status` assumed Blinkit's semantics
for everyone — so **every legitimate Zepto resume was refused as "budget is None"**.
These tests pin the distinction in both directions, because the failure was silent
in one and would be silent again.

    python -m campaign_manager.tests.test_resume_semantics
"""
import asyncio

from campaign_manager import writes
from campaign_manager.marketplaces import get_adapter


class _Adapter:
    """Minimal stand-in; only the attributes writes.apply_status consults."""

    def __init__(self, resubmits):
        self.RESUME_RESUBMITS = resubmits
        self.called_with = None

    async def apply_status(self, client, campaign_id, target, *, budget=None):
        self.called_with = {"target": target, "budget": budget}
        return {"success": True}


def _resume(adapter, *, budget, dry_run=True, current="paused"):
    return asyncio.run(writes.apply_status(
        adapter, None, run_id="t", campaign_id=1, target="running",
        current=current, dry_run=dry_run, budget=budget))


def test_blinkit_style_resume_requires_a_budget():
    """A restart rewrites the budget, so no budget means we cannot say what it
    would be set to — refusing beats guessing."""
    assert _resume(_Adapter(resubmits=True), budget=None) is False


def test_blinkit_style_resume_budget_passes_the_bounds_guardrail():
    """The restart's budget is not allowed to sneak past the check a plain budget
    write would face."""
    assert _resume(_Adapter(resubmits=True), budget=500) is True
    assert _resume(_Adapter(resubmits=True), budget=0) is False


def test_zepto_style_resume_needs_no_budget():
    """THE regression this file exists for. Zepto's activate restores the
    campaign's own budget, so requiring one refuses every valid resume."""
    assert _resume(_Adapter(resubmits=False), budget=None) is True


def test_an_adapter_that_says_nothing_gets_the_STRICTER_behaviour():
    """Defaulting to 'resume re-submits' means a new adapter that has not thought
    about this fails closed — refusing a resume — rather than silently starting a
    campaign with an unknown budget."""
    class Silent:
        async def apply_status(self, client, cid, target, *, budget=None):
            return {"success": True}

    assert _resume(Silent(), budget=None) is False


def test_live_resume_without_a_budget_does_not_crash_the_log_line():
    """`budget=₹{budget:g}` raises on None. A successful write must not die while
    reporting itself."""
    a = _Adapter(resubmits=False)
    assert _resume(a, budget=None, dry_run=False) is True
    assert a.called_with == {"target": "running", "budget": None}


def test_pausing_never_requires_a_budget_on_either_marketplace():
    for resubmits in (True, False):
        a = _Adapter(resubmits=resubmits)
        ok = asyncio.run(writes.apply_status(
            a, None, run_id="t", campaign_id=1, target="paused",
            current="running", dry_run=True, budget=None))
        assert ok is True, f"pause refused with RESUME_RESUBMITS={resubmits}"


def test_real_adapters_declare_opposite_semantics():
    assert get_adapter("blinkit").RESUME_RESUBMITS is True
    assert get_adapter("zepto").RESUME_RESUBMITS is False


def test_campaign_name_is_read_per_marketplace():
    """Blinkit calls it `name`, Zepto `campaign_name`. Asking the adapter beats a
    fallback chain that quietly returns None for a shape nobody checked."""
    assert get_adapter("blinkit").campaign_name({"name": "Rose Apple"}) == "Rose Apple"
    assert get_adapter("zepto").campaign_name(
        {"campaign_name": "Tech Test"}) == "Tech Test"
    for mp in ("blinkit", "zepto"):
        assert get_adapter(mp).campaign_name({}) is None


def test_zepto_resume_overwrites_nothing():
    """Blinkit reports what a restart will silently rewrite; Zepto has nothing to
    report because it rewrites nothing."""
    assert get_adapter("zepto").resume_overwrites({"campaign_name": "x"}, 500) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} resume-semantics tests passed.")
