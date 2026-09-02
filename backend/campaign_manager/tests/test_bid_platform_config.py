"""Per-marketplace bid tuning — and the guarantee that Blinkit did not move.

Zepto bids in CPC at ~₹10-25; Blinkit bids CPM up to ~₹900. Every rupee-denominated
constant therefore needs a per-platform value. What must NOT happen is that giving
Zepto its own numbers quietly changes the live Blinkit optimizer, so the first test
here is the one that matters most.

    python -m campaign_manager.tests.test_bid_platform_config
"""
from campaign_manager import bid, config


# ── the guarantee ────────────────────────────────────────────────────────────

def test_blinkit_resolves_to_the_module_defaults_exactly():
    """THE regression this file exists for. Blinkit has no override entry, so every
    tunable must resolve to the same value it had before per-platform tuning existed.
    Compared against the module constants themselves, so an env override moves both
    sides together and this stays a statement about the LOOKUP, not about a number."""
    for name, default in (
        ("BID_RAISE_MIN_STEP", config.BID_RAISE_MIN_STEP),
        ("BID_RAISE_PCT", config.BID_RAISE_PCT),
        ("BID_RAISE_ESCALATE", config.BID_RAISE_ESCALATE),
        ("BID_DRIFT_PCT", config.BID_DRIFT_PCT),
        ("BID_DRIFT_MIN_STEP", config.BID_DRIFT_MIN_STEP),
        ("BID_DRIFT_PAUSE_MINUTES", config.BID_DRIFT_PAUSE_MINUTES),
        ("BID_MAX_ABSOLUTE", config.BID_MAX_ABSOLUTE),
    ):
        assert config.bid_tuning("blinkit", name) == default, name


def test_an_unknown_marketplace_also_gets_the_defaults():
    """A platform with no override block is not an error — it simply has nothing to
    override. Failing here would make adding MP#3 a config chore before it is a
    working adapter."""
    assert config.bid_tuning("mystery-mart", "BID_RAISE_MIN_STEP") == \
        config.BID_RAISE_MIN_STEP


def test_a_typo_raises_instead_of_silently_defaulting():
    """A misspelled tunable resolving to a fallback is the kind of bug that only shows
    up as a campaign spending oddly."""
    try:
        config.bid_tuning("zepto", "BID_RAISE_MINSTEP")
    except KeyError as e:
        assert "BID_RAISE_MIN_STEP" in str(e)   # names the known set
    else:
        raise AssertionError("an unknown tunable must raise")


# ── Zepto's overrides ────────────────────────────────────────────────────────

def test_zepto_overrides_only_the_rupee_denominated_values():
    """Percentages already scale across a 40x difference in bid size; only the absolute
    floors need re-basing. A constant with no override is provably identical on both
    marketplaces, which is what makes the guarantee above cheap to keep."""
    for name in ("BID_RAISE_MIN_STEP", "BID_DRIFT_MIN_STEP", "BID_MAX_ABSOLUTE"):
        assert config.bid_tuning("zepto", name) != config.bid_tuning("blinkit", name), name
    for name in ("BID_RAISE_ESCALATE", "BID_DRIFT_PCT", "BID_DRIFT_PAUSE_MINUTES"):
        assert config.bid_tuning("zepto", name) == config.bid_tuning("blinkit", name), name


def test_zepto_steps_are_sane_against_a_real_zepto_bid():
    """Guards the numbers against Blinkit-scale drift. Observed live: our campaign bids
    ₹10-12, competitors' winning bids ₹15-21."""
    step = config.bid_tuning("zepto", "BID_RAISE_MIN_STEP")
    assert step < 12, f"a ₹{step} raise floor is over 100% of a real ₹12 Zepto bid"
    assert config.bid_tuning("zepto", "BID_DRIFT_MIN_STEP") <= 2
    ceiling = config.bid_tuning("zepto", "BID_MAX_ABSOLUTE")
    assert 21 < ceiling <= 1000, "ceiling must clear the winning bid but stay a real cap"


# ── the integer-escalation trap ──────────────────────────────────────────────

def test_zepto_min_step_is_large_enough_for_escalation_to_fire():
    """Escalation is integer: `int(1 * 1.5) == 1`. At a ₹1 step it NEVER grows, so a
    climb is a flat ₹1/tick and a window is spent underbidding. This pins the reason
    the floor is 2 and not 1 — the constraint is invisible from the value alone."""
    min_step = config.bid_tuning("zepto", "BID_RAISE_MIN_STEP")
    esc = config.bid_tuning("zepto", "BID_RAISE_ESCALATE")
    assert int(min_step * esc) > min_step, (
        f"min_step={min_step} with escalate={esc} cannot grow — escalation is dead")


def test_a_one_rupee_step_would_stall_the_climb():
    """The counter-example, kept executable so nobody 'tidies' the floor down to 1."""
    stalled = bid.next_raise_step(12, 1, improved=False, min_step=1, pct=15, escalate=1.5)
    assert stalled == 1, "int(1*1.5)==1 — this is the stall being guarded against"


def test_zepto_climb_crosses_a_competitive_bid_within_the_hour():
    """₹8 floor to past a ₹21 winning bid, four ticks of a */15 window. Walks the real
    escalation rather than asserting a hardcoded table."""
    cpm, last = 8, None
    for _ in range(4):
        step = bid.next_raise_step(
            cpm, last, improved=False,
            min_step=config.bid_tuning("zepto", "BID_RAISE_MIN_STEP"),
            pct=config.bid_tuning("zepto", "BID_RAISE_PCT"),
            escalate=config.bid_tuning("zepto", "BID_RAISE_ESCALATE"))
        cpm, last = cpm + step, step
    assert cpm > 21, f"reached only ₹{cpm} in four ticks — too slow to matter in a window"


def test_blinkit_climb_is_untouched_by_any_of_this():
    """Same walk on Blinkit's numbers, as the paired guarantee: a ₹400 CPM still moves
    in Blinkit-sized steps."""
    step = bid.next_raise_step(
        400, None, improved=False,
        min_step=config.bid_tuning("blinkit", "BID_RAISE_MIN_STEP"),
        pct=config.bid_tuning("blinkit", "BID_RAISE_PCT"),
        escalate=config.bid_tuning("blinkit", "BID_RAISE_ESCALATE"))
    assert step >= 32, f"Blinkit step collapsed to ₹{step}"


# ── the deleted ladder ───────────────────────────────────────────────────────

def test_the_dynamic_step_ladder_is_gone():
    """₹100/50/25/12.5 was rupee-denominated at Blinkit's scale — a ₹12.5-₹100 step on a
    ₹12 Zepto bid — and reachable ONLY via the kill switch, i.e. exactly when someone is
    already having a bad day. Deleted 2026-09-01; this stops it coming back."""
    assert not hasattr(bid, "_dynamic_step")


def test_the_kill_switch_freezes_on_both_marketplaces():
    """`drift_pct=0` must mean HOLD, not 'step down by some other rule'. Checked at both
    scales so a future re-introduction fails here rather than in production."""
    for cpm, min_bid, max_bid in ((400, 100, 900), (12, 8, 100)):
        new, reason = bid.compute_bid(1, 3, cpm, min_bid, max_bid, 1, 30,
                                      drift_pct=0, raise_step=2)
        assert new is None, f"drift-off stepped to {new} at cpm={cpm}"
        assert "switched off" in reason


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} bid platform-config tests passed.")
