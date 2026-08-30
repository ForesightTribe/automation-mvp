"""The marketplace bid floor (V7.6) — pure, no Blinkit, no DB.

Two things under test: `effective_floor` (which minimum actually applies) and the
match-type mapping the floor lookup depends on. The second matters more than it looks —
`apply_bid` sends a BROAD rule to Blinkit as SMART, so a floor looked up under the wrong
name would compare a BROAD bid against the exact-match minimum.

Run: ./venv/Scripts/python.exe -m campaign_manager.tests.test_bid_floor
"""
from campaign_manager.bid import effective_floor
from campaign_manager.marketplaces.blinkit.adapter import _api_match

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


def test_marketplace_floor_wins_when_higher():
    """The whole point: a rule written weeks ago cannot know today's minimum, and below it
    the write is refused or silently raised anyway."""
    check("floor above rule", effective_floor(150, 200), 200)


def test_rule_wins_when_higher():
    """A rule's min_bid is the CLIENT's floor, not a claim about the auction — so a client
    who wants to never bid under ₹500 keeps that, even where Blinkit would allow ₹200."""
    check("rule above floor", effective_floor(500, 200), 500)


def test_equal_is_unchanged():
    check("equal", effective_floor(200, 200), 200)


def test_unknown_floor_falls_back_to_the_rule():
    """None = we could not read a floor (lookup failed, or a keyword the campaign does not
    carry yet). Falling back keeps bidding; refusing because a READ failed would be worse
    than bidding at the configured minimum."""
    check("no floor known", effective_floor(150, None), 150)


def test_real_observed_floors():
    """Numbers read off the live account 2026-08-27 — the floor genuinely varies per
    keyword, which is why there is no single constant to hardcode."""
    check("mango ₹50", effective_floor(20, 50), 50)
    check("soda ₹100", effective_floor(20, 100), 100)
    check("protein chips ₹200", effective_floor(20, 200), 200)
    check("cocktail ₹400", effective_floor(20, 400), 400)


def test_match_type_maps_broad_to_smart():
    """`apply_bid` sends BROAD as SMART, so the floor must be read under SMART too."""
    check("BROAD→SMART", _api_match("BROAD"), "SMART")
    check("EXACT", _api_match("EXACT"), "EXACT")
    check("exact_match key", _api_match("exact_match"), "EXACT")
    check("smart_match key", _api_match("smart_match"), "SMART")
    check("legacy EXACT_MATCH", _api_match("EXACT_MATCH"), "EXACT")
    check("None defaults to EXACT", _api_match(None), "EXACT")


def test_floor_and_ceiling_can_conflict():
    """A floor above the rule's ceiling is a rule that cannot be satisfied. `effective_floor`
    does not resolve that — `writes.clamp_bid` does, and the engine logs it — but the floor
    must still report the true number rather than quietly capping itself at the ceiling."""
    check("floor above ceiling still reported", effective_floor(100, 900), 900)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)
