"""The three guardrails added with Z6a.6-8.

    python -m campaign_manager.tests.test_zepto_bid_guards
"""
import asyncio

from campaign_manager import writes
from campaign_manager.marketplaces import get_adapter
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import transport as ztr


# ── platform bid bounds (Q1) ────────────────────────────────────────────────

class _Adapter:
    """Stand-in exposing only what writes.apply_bid consults."""

    def __init__(self, **bounds):
        for k, v in bounds.items():
            setattr(self, k, v)
        self.sent = None

    async def apply_bid(self, client, campaign_id, keyword, cpm, match_type="EXACT"):
        self.sent = cpm
        return {"success": True}


def _apply(adapter, new_cpm, *, min_bid=1, max_bid=10000, dry_run=True):
    return asyncio.run(writes.apply_bid(
        adapter, None, run_id="t", campaign_id=1, keyword="kw", new_cpm=new_cpm,
        current_cpm=999999, min_bid=min_bid, max_bid=max_bid, dry_run=dry_run))


def test_a_marketplace_floor_refuses_rather_than_clamping_up():
    """Silently raising a bid above what the operator configured is not a guardrail's
    call to make — and a rule whose range sits under the platform floor is a config
    error that should be visible, not quietly corrected."""
    a = _Adapter(MIN_BID=10)
    assert _apply(a, 5, min_bid=1, max_bid=100) is False
    assert a.sent is None


def test_a_marketplace_ceiling_refuses_too():
    assert _apply(_Adapter(MAX_BID=50), 80, min_bid=1, max_bid=100) is False


def test_a_value_inside_the_platform_range_passes():
    assert _apply(_Adapter(MIN_BID=10, MAX_BID=50), 30, min_bid=1, max_bid=100) is True


def test_an_adapter_declaring_nothing_is_unbounded_by_this_check():
    """Blinkit declares no bid bounds, so the new check must be a no-op there — the
    rule's own clamp remains the only limit, exactly as before."""
    assert _apply(_Adapter(), 5) is True
    assert _apply(_Adapter(), 9999) is True


def test_zepto_declares_the_bid_floor_zepto_actually_enforces():
    """₹10, learned from a live 400 on 2026-09-02:

        keyword bid validation failed: keyword 'pink toffee' (EXACT)
        bid 8.00 is below minimum bid 10.00

    NOT the ₹8 in `campaigns/metadata` — that is
    `bid_multiplier_types[pdp].minimum_bid`, a per-PLACEMENT floor. Had we adopted it,
    the guardrail would have sat BELOW the real limit and every such write would have
    travelled to Zepto to be refused. Metadata's only true floor is the ₹500 budget one.
    """
    assert get_adapter("zepto").MIN_BID == 10


def test_the_zepto_floor_is_above_the_metadata_red_herring():
    """Pins the distinction itself, so a future 'tidy-up' toward the published 8 fails
    here rather than in production."""
    assert get_adapter("zepto").MIN_BID > 8


def test_a_rule_below_the_zepto_floor_is_refused_before_the_PUT():
    """The point of declaring it: a doomed bid never becomes a whole-campaign PUT.
    That write carries geo targeting, the product list and every sibling bid, so not
    sending it is materially safer than sending it and reading the 400."""
    assert _apply(get_adapter("zepto"), 8, min_bid=8, max_bid=30) is False


def test_the_pure_bounds_predicate():
    assert writes.bid_out_of_bounds(10, min_bid=10) is None
    assert writes.bid_out_of_bounds(50, max_bid=50) is None
    assert "below" in writes.bid_out_of_bounds(9, min_bid=10)
    assert "above" in writes.bid_out_of_bounds(51, max_bid=50)
    assert writes.bid_out_of_bounds(None) == "bid is None"
    assert writes.bid_out_of_bounds(5) is None          # nothing declared → no opinion


# ── cross-run re-login bound (§5.4) ─────────────────────────────────────────

def test_the_cross_run_interval_is_a_real_gap_not_a_token_one():
    """The bid optimizer ticks every 15 min in a FRESH subprocess, so the floor has to
    exceed one tick or it bounds nothing at all."""
    assert ztr.MIN_REAUTH_INTERVAL_SECONDS > 15 * 60


def test_both_bounds_still_exist_and_answer_different_questions():
    """Per-run stops a ping-pong inside one process; cross-run stops it across the 16
    processes a 4-hour window spawns. Removing either leaves a real hole."""
    assert ztr.MAX_REAUTH_PER_RUN >= 1
    assert ztr.MIN_REAUTH_INTERVAL_SECONDS >= 1


def test_the_auth_store_exposes_the_cross_run_signal():
    """An in-process counter cannot see across subprocesses; `last_login_at` can, and
    the circuit breaker cannot help because eviction logins SUCCEED."""
    from platform_auth import store as auth_store
    assert callable(getattr(auth_store, "last_login", None))


# ── one read per bid write (§5.2) ───────────────────────────────────────────

def test_keyword_index_is_pure_and_reads_the_payload_it_is_given():
    """It used to fetch its own copy, so the index came from one read and the mutation
    was applied to another — if the keyword list changed in between, the index pointed
    at the wrong keyword and we would have moved a bid nobody asked to move."""
    payload = {"keyword_targeting": [
        {"text": "bread", "match_type": "EXACT", "bid_value": 10},
        {"text": "bread", "match_type": "PHRASE", "bid_value": 14},
    ]}
    assert zad._keyword_index(payload, 1, "bread", "EXACT") == 0
    assert zad._keyword_index(payload, 1, "bread", "PHRASE") == 1
    assert not asyncio.iscoroutinefunction(zad._keyword_index)


def test_an_absent_keyword_refuses_instead_of_adding_one():
    try:
        zad._keyword_index({"keyword_targeting": []}, 7, "nope", "EXACT")
    except RuntimeError as e:
        assert "adding a keyword is not a bid change" in str(e)
    else:
        raise AssertionError("must refuse")


def test_apply_bid_reads_the_campaign_exactly_once():
    """Counts the reads. Two would widen the window in which a parallel budget write
    can land between our read and our PUT."""
    reads = []

    async def fake_rebased(client, campaign_id):
        reads.append(campaign_id)
        return ({"daily_budget": 500,
                 "keyword_targeting": [{"text": "kw", "match_type": "EXACT",
                                        "bid_value": 10}]}, {})

    async def fake_update(client, campaign_id, payload):
        return {"ok": True}

    orig_rebased, orig_update = zad._rebased_payload, zad.zc.update_campaign
    zad._rebased_payload, zad.zc.update_campaign = fake_rebased, fake_update
    try:
        asyncio.run(zad.apply_bid(None, 42, "kw", 12, "EXACT"))
    finally:
        zad._rebased_payload, zad.zc.update_campaign = orig_rebased, orig_update

    assert reads == [42], f"expected exactly one read, got {len(reads)}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto bid-guard tests passed.")
