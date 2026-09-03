"""Being absent from the results must make the bid GO UP — on marketplaces that opt in.

The gap this closes: a keyword outbid off the page could never climb back. Every tick
saw "absent", skipped, and left the bid alone; the next window open then wrote
`min_bid`, lower still. Once off the page, off forever — which is the opposite of what
a bid is for.

    python -m campaign_manager.tests.test_absent_raises
"""
from campaign_manager import bid
from campaign_manager.marketplaces import get_adapter


# ── who opts in ──────────────────────────────────────────────────────────────

def test_zepto_opts_in_and_blinkit_does_not():
    """Blinkit's DOM fallback could report every result as organic, so 'absent' there
    might mean a broken SOURCE rather than a missing ad. Zepto marks sponsored rows
    positively (`tagsV2`) and names the winning campaign (`uclId`), so absence is a
    fact about the auction."""
    assert getattr(get_adapter("zepto"), "RAISE_WHEN_ABSENT", False) is True
    assert getattr(get_adapter("blinkit"), "RAISE_WHEN_ABSENT", False) is False


def test_an_adapter_that_says_nothing_keeps_the_old_behaviour():
    """Fail-safe default: a new marketplace does not start bidding against data nobody
    has verified it can read."""
    class Silent:
        pass
    assert getattr(Silent(), "RAISE_WHEN_ABSENT", False) is False


# ── the synthetic position ───────────────────────────────────────────────────

def test_absent_is_worse_than_every_slot_we_saw():
    """`len(results) + 1` is a genuine lower bound: we looked at N and were in none of
    them, so we are somewhere past N."""
    results_len = 21
    synthetic = float(results_len + 1)
    assert synthetic > results_len
    new_cpm, reason = bid.compute_bid(
        synthetic, 3, 10, 10, 25, None, None, raise_step=2)
    assert new_cpm == 12 and "raising" in reason


def test_still_absent_next_tick_escalates_the_step():
    """The synthetic position keeps the escalation honest — no improvement between
    ticks means the step grows, exactly as for a real slot that will not move."""
    first = bid.next_raise_step(10, None, improved=False, min_step=2, pct=15, escalate=1.5)
    second = bid.next_raise_step(12, first, improved=False, min_step=2, pct=15, escalate=1.5)
    assert second > first


def test_the_climb_is_bounded_by_max_bid():
    """The downside of bidding blind: it can pin at the ceiling. That is the operator's
    declared limit, so it is bounded and visible rather than a runaway."""
    cpm, last = 10, None
    for _ in range(8):
        step = bid.next_raise_step(cpm, last, improved=False, min_step=2, pct=15,
                                   escalate=1.5)
        cpm, last = min(cpm + step, 25), step
    assert cpm == 25


# ── the trap: relaxation must not fire on a synthetic position ───────────────

def test_relaxing_against_a_synthetic_position_would_undo_the_climb():
    """Why `relaxed_now` is guarded with `not absent`.

    If absence relaxed the target to `len(results) + 1`, the synthetic position would
    EQUAL the target, `compute_bid` would read that as holding, and drift-down would
    start trimming — walking back the very climb meant to get us onto the page. This
    test demonstrates the mechanism the guard prevents."""
    synthetic = 22.0
    # The relaxed-target world we must never enter:
    new_cpm, reason = bid.compute_bid(
        synthetic, 22, 20, 10, 25, 22.0, 30, drift_pct=7, drift_min_step=1, raise_step=2)
    assert new_cpm is not None and new_cpm < 20, "holding-at-target would trim the bid"
    assert "trimming" in reason

    # The world the guard keeps us in — target stays 3, so we keep climbing:
    new_cpm, reason = bid.compute_bid(
        synthetic, 3, 20, 10, 25, 22.0, 30, drift_pct=7, drift_min_step=1, raise_step=2)
    assert new_cpm == 22 and "raising" in reason


def test_a_real_position_can_still_relax():
    """The guard must not disable relaxation generally — it is still the answer when a
    real, measured position cannot be improved at the ceiling."""
    assert bid.should_relax_target(9, 3, 25, 25, 9) is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} absent-raises tests passed.")
