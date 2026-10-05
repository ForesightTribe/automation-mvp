"""Zepto ad-slot attribution — which sponsored slot is THIS rule's?

Rows here are shaped as the public scraper returns them, and the `uclId`s are REAL
ones captured from live Zepto search on 2026-09-01.

Since 2026-10-05 the answer is an AD SLOT (campaign_manager/ad_slots.py): our place among the
sponsored rows. Organic rows of ours are recorded, never a slot.

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


def theirs(pos):
    return row(pos, ad=True, ucl=UCL_THEIRS, variant="someone-else")


def locate(results, keyword="bakers dozen bread", match_type="PHRASE"):
    return positions.locate(results, keyword, 12.9, 77.5,
                            campaign_id=OUR_CAMPAIGN, match_type=match_type,
                            variant_ids=[OUR_VARIANT])


# ── the happy path ───────────────────────────────────────────────────────────

def test_finds_our_slot_by_campaign_and_keyword():
    p = locate([theirs(1), row(7, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT)])
    assert (p.slot, p.page_position, p.ad_positions) == (2, 7, (1, 7))
    assert "live(" in p.reason


def test_the_slot_is_counted_among_ads_only():
    """Deepansh's example (2026-10-05): ads at 2, 5, 6, 9, 11 are slots 1-5, so our ad at
    page position 5 is Ad #2 — and our organic listings at 1 and 4 change nothing."""
    p = locate([row(1, variant=OUR_VARIANT), theirs(2), row(4, variant=OUR_VARIANT),
                row(5, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT),
                theirs(6), theirs(9), theirs(11)])
    assert (p.slot, p.page_position) == (2, 5)
    assert p.ad_positions == (2, 5, 6, 9, 11)
    assert p.organic_positions == (1, 4)


def test_best_slot_wins_when_we_hold_several():
    """A campaign can hold several slots for one keyword with different products."""
    p = locate([row(9, ad=True, ucl=UCL_OURS_PHRASE), row(3, ad=True, ucl=UCL_OURS_PHRASE)])
    assert (p.slot, p.page_position) == (1, 3)


def test_a_slot_won_by_another_keyword_still_counts():
    """The shopper sees our ad there, whichever of our keywords won it. The reason says
    which, so the distinction survives in the log, not the decision."""
    p = locate([row(7, ad=True, ucl=UCL_OURS_PHRASE)], match_type="EXACT")
    assert p.slot == 1
    assert "won by" in p.reason and "bakers dozen bread" in p.reason


def test_keyword_comparison_is_normalised():
    p = locate([row(4, ad=True, ucl=UCL_OURS_PHRASE)],
               keyword="  Bakers   Dozen Bread ", match_type="phrase")
    assert p.slot == 1 and "won by" not in p.reason      # matched this rule exactly


# ── organic is recorded, never a slot ────────────────────────────────────────

def test_organic_alone_is_no_ad_slot():
    """CHANGED 2026-10-05 (was "organic is a position", 2026-09-02). The engine pushes the ad
    where the client asked whatever organic does, so organic-only reads as "not showing" and
    the bid climbs. The organic listing is kept for the overlap warning."""
    p = locate([row(2, variant=OUR_VARIANT)])
    assert p.slot is None and p.organic_positions == (2,)
    assert "organic only" in p.reason


def test_organic_is_only_ours_on_a_product_id_match():
    """There is no tracking id on an organic row, so a product-id match is the only
    proof. A stranger's organic row must not become our organic listing."""
    p = locate([row(2, variant="someone-else")])
    assert p.slot is None and p.organic_positions == ()


def test_organic_above_our_ad_does_not_replace_it():
    """Verified live on `ricotta`: the same product at 8 organic and 9 sponsored. The slot is
    the sponsored one; the organic row is only recorded."""
    p = locate([row(8, variant=OUR_VARIANT),
                row(9, ad=True, ucl=UCL_OURS_PHRASE, variant=OUR_VARIANT)])
    assert (p.slot, p.page_position, p.organic_positions) == (1, 9, (8,))
    assert "sponsored" in p.reason


# ── absent ───────────────────────────────────────────────────────────────────

def test_a_competitors_ad_is_not_ours():
    p = locate([theirs(1)])
    assert p.slot is None and "not in these results" in p.reason
    assert p.ad_positions == (1,)


def test_absent_when_nothing_on_the_page_is_ours():
    p = locate([row(2, variant="someone-else"), theirs(1)])
    assert p.slot is None and "not in these results" in p.reason


def test_our_product_in_an_unattributable_paid_slot_still_counts():
    """Sponsored, our product, tracking id undecodable — another campaign of ours, or
    a malformed id. Either way the shopper sees our ad there."""
    p = locate([theirs(2), row(6, ad=True, ucl="garbage", variant=OUR_VARIANT)])
    assert (p.slot, p.page_position) == (2, 6) and "not attributable" in p.reason


def test_empty_results_are_not_an_error_here():
    """`fetch_positions` raises when it could not LOOK. Reaching locate with nothing
    means we looked and were not there."""
    p = locate([])
    assert p.slot is None and p.ad_positions == () and "not in these results" in p.reason


# ── the adapter seam ─────────────────────────────────────────────────────────

def test_adapter_passes_products_through_as_variant_ids():
    """`read_products` returns `{pid, name}` on every marketplace; Zepto's pid IS the
    variant id consumer search reports, so the join is exact. Without it neither an
    unattributable ad nor an organic row of ours could be recognised."""
    p = get_adapter("zepto").locate_position(
        [row(3, ad=True, ucl="garbage", variant=OUR_VARIANT), row(6, variant=OUR_VARIANT)],
        "bakers dozen bread", 12.9, 77.5,
        products=[{"pid": OUR_VARIANT, "name": ""}],
        campaign_id=OUR_CAMPAIGN, match_type="PHRASE", brand_name=None)
    assert (p.slot, p.organic_positions) == (1, (6,))


def test_both_adapters_accept_the_same_call():
    """The engine passes `campaign_id`/`match_type` unconditionally. Blinkit has no
    per-slot attribution and must simply ignore them rather than raise."""
    for mp in ("blinkit", "zepto"):
        p = get_adapter(mp).locate_position(
            [], "kw", 12.9, 77.5, products=[], campaign_id=1,
            match_type="EXACT", brand_name=None)
        assert p.slot is None and p.ad_positions == (), mp


def test_blinkit_still_matches_on_product_identity():
    """The extraction moved out of bid.py into the adapter — this proves it still
    happens, rather than quietly producing empty lists like it would have on Zepto."""
    results = [{"position": 1, "is_ad": True, "name": "Other Brand Cola", "pid": "x"},
               {"position": 3, "is_ad": True, "name": "Dobra Goli Soda", "pid": "p1"}]
    p = get_adapter("blinkit").locate_position(
        results, "goli soda", 12.9, 77.5,
        products=[{"pid": "p1", "name": "Dobra Goli Soda"}],
        campaign_id=99, match_type="EXACT", brand_name="dobra")
    assert (p.slot, p.page_position) == (2, 3)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto-position tests passed.")
