"""Zepto position attribution — which sponsored slot is THIS rule's?

Rows here are shaped as the public scraper returns them, and the `uclId`s are REAL
ones captured from live Zepto search on 2026-09-01.

    python -m campaign_manager.tests.test_zepto_positions
"""
from campaign_manager.marketplaces import get_adapter
from campaign_manager.marketplaces.zepto import positions

OUR_CAMPAIGN = "2373457"
OUR_VARIANT = "0e8e3c72-a70e-44c5-8987-1f16520b41ed"

# Real: our campaign, keyword `bakers dozen bread`, PHRASE — returned for the query
# `sourdough bread`.
UCL_OURS_PHRASE = (
    "101|27d77e75c84e4e518628b53f0c3e8451|1600|1788265895862|"
    "8e70a41c-7a6f-482b-ba44-277b0901fef7|||CPC|"
    "b9cea5fc-da5f-4045-9b67-c07831733746|b9cea5fc-da5f-4045-9b67-c07831733746||"
    f"{OUR_CAMPAIGN}|{OUR_CAMPAIGN}|042b55a7-bfcf-46e8-8cc2-56ba2b4dc7cf||0|P_INFO|||"
    f"{OUR_VARIANT}|49665e03-a09c-4a51-b5e0-cda18d152544|"
    "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5|30566884-bbd7-49fa-8c3f-43c90a571c9e|"
    "K_INFO|PHRASE|bakers dozen bread|0|0|0|0")

# Real: a competitor's (English Oven), keyword `bread`, EXACT.
UCL_THEIRS = (
    "101|80d1b3ce711548e497b1bd158713d66f|2750|1788264745312|"
    "30600a76-a175-4584-8140-e6d119ff2aa9|||CPC|"
    "c522b8bb-fba9-40ae-82a4-69077d495c7b|c522b8bb-fba9-40ae-82a4-69077d495c7b||"
    "2410741|2410741|300a1056-ad32-430e-b5e4-41624b0494ed||0|P_INFO|||"
    "fee489ea-b688-441f-bdd5-3a57c2411787|68c08f6d-4d38-459c-b87b-ce71f0560d01|"
    "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5|30566884-bbd7-49fa-8c3f-43c90a571c9e|"
    "K_INFO|EXACT|bread|0|10|0|0")

# Our campaign, a DIFFERENT keyword of ours.
UCL_OURS_OTHER_KW = UCL_OURS_PHRASE.replace(
    "K_INFO|PHRASE|bakers dozen bread", "K_INFO|PHRASE|bakers dozen sourdough")


def row(pos, *, ad=False, ucl="", variant=""):
    return {"position": pos, "is_ad": ad, "ucl_id": ucl, "variant_id": variant,
            "name": "Brik Oven Sourdough", "brand": "Brik Oven"}


def locate(results, keyword="bakers dozen bread", match_type="PHRASE"):
    return positions.locate(results, keyword, 12.9, 77.5,
                            campaign_id=OUR_CAMPAIGN, match_type=match_type,
                            variant_ids=[OUR_VARIANT])


# ── the happy path ───────────────────────────────────────────────────────────

def test_finds_our_slot_by_campaign_and_keyword():
    pos, src = locate([row(1, ad=True, ucl=UCL_THEIRS),
                       row(7, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT)])
    assert pos == 7 and "live(" in src


def test_best_slot_wins_when_we_hold_several():
    """A campaign can hold several slots for one keyword with different products.
    `min` matches Blinkit's convention so the two marketplaces report rank alike."""
    pos, _ = locate([row(9, ad=True, ucl=UCL_OURS_PHRASE),
                     row(3, ad=True, ucl=UCL_OURS_PHRASE)])
    assert pos == 3


def test_a_slot_won_by_another_keyword_still_counts_as_visibility():
    """CHANGED 2026-09-02. This used to return None on the reasoning that the slot was
    not this rule's to claim. Under best-position it counts: the shopper sees our
    product there. The reason string still says which keyword won it, so the
    distinction survives where it matters — in the log, not the decision."""
    pos, src = locate([row(7, ad=True, ucl=UCL_OURS_PHRASE)], match_type="EXACT")
    assert pos == 7
    assert "won by" in src and "bakers dozen bread" in src


def test_keyword_comparison_is_normalised():
    pos, src = locate([row(4, ad=True, ucl=UCL_OURS_PHRASE)],
                      keyword="  Bakers   Dozen Bread ", match_type="phrase")
    assert pos == 4 and "won by" not in src      # matched this rule exactly


# ── organic counts, and the best row wins ────────────────────────────────────

def test_organic_appearance_is_a_position_not_a_skip():
    """THE change. A bid cannot move the organic ROW, but it can add a paid row above
    it — so best-position does respond to bidding. And when organic already meets the
    target, drift-down trims the bid and we keep the placement for free, which the
    sponsored-only model could not even see."""
    pos, src = locate([row(2, variant=OUR_VARIANT)])
    assert pos == 2 and "organic" in src


def test_organic_is_only_ours_on_a_product_id_match():
    """There is no tracking id on an organic row, so a product-id match is the only
    proof. A stranger's organic row must not become our position."""
    pos, _ = locate([row(2, variant="someone-else")])
    assert pos is None


def test_the_better_of_organic_and_paid_wins():
    """Verified live on `ricotta`: the same product at 8 organic and 9 sponsored."""
    pos, src = locate([row(8, variant=OUR_VARIANT),
                       row(9, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT)])
    assert pos == 8 and "organic" in src


def test_paid_wins_when_it_is_the_higher_slot():
    pos, src = locate([row(3, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT),
                       row(11, variant=OUR_VARIANT)])
    assert pos == 3 and "sponsored" in src


# ── absent ───────────────────────────────────────────────────────────────────

def test_a_competitors_ad_is_not_ours():
    pos, reason = locate([row(1, ad=True, ucl=UCL_THEIRS)])
    assert pos is None and "not in these results" in reason


def test_absent_when_nothing_on_the_page_is_ours():
    pos, reason = locate([row(2, variant="someone-else"),
                          row(1, ad=True, ucl=UCL_THEIRS)])
    assert pos is None and "not in these results" in reason


def test_our_product_in_an_unattributable_paid_slot_still_counts():
    """Sponsored, our product, tracking id undecodable — another campaign of ours, or
    a malformed id. Either way the shopper sees us there."""
    pos, src = locate([row(6, ad=True, ucl="garbage", variant=OUR_VARIANT)])
    assert pos == 6 and "not attributable" in src


def test_empty_results_are_not_an_error_here():
    """`fetch_positions` raises when it could not LOOK. Reaching locate with nothing
    means we looked and were not there."""
    pos, reason = locate([])
    assert pos is None and "not in these results" in reason


# ── the adapter seam ─────────────────────────────────────────────────────────

def test_adapter_passes_products_through_as_variant_ids():
    """`read_products` returns `{pid, name}` on every marketplace; Zepto's pid IS the
    variant id consumer search reports, so the join is exact. Without it an ORGANIC
    row of ours cannot be recognised at all."""
    pos, _ = get_adapter("zepto").locate_position(
        [row(6, variant=OUR_VARIANT)], "bakers dozen bread", 12.9, 77.5,
        products=[{"pid": OUR_VARIANT, "name": ""}],
        campaign_id=OUR_CAMPAIGN, match_type="PHRASE", brand_name=None)
    assert pos == 6


def test_both_adapters_accept_the_same_call():
    """The engine passes `campaign_id`/`match_type` unconditionally. Blinkit has no
    per-slot attribution and must simply ignore them rather than raise."""
    for mp in ("blinkit", "zepto"):
        out = get_adapter(mp).locate_position(
            [], "kw", 12.9, 77.5, products=[], campaign_id=1,
            match_type="EXACT", brand_name=None)
        assert isinstance(out, tuple) and out[0] is None, mp


def test_blinkit_still_matches_on_product_identity():
    """The extraction moved out of bid.py into the adapter — this proves it still
    happens, rather than quietly producing empty lists like it would have on Zepto."""
    results = [{"position": 3, "is_ad": True, "name": "Dobra Goli Soda", "pid": "p1"}]
    pos, _ = get_adapter("blinkit").locate_position(
        results, "goli soda", 12.9, 77.5,
        products=[{"pid": "p1", "name": "Dobra Goli Soda"}],
        campaign_id=99, match_type="EXACT", brand_name="dobra")
    assert pos == 3


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto-position tests passed.")
