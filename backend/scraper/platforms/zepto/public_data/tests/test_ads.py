"""Zepto sponsored-slot detection and `uclId` decoding.

Every `uclId` below is a REAL id captured from live Zepto search on 2026-09-01 —
four advertisers including our own. Synthetic ids are marked as such and exist only
to pin a guard.

    python -m scraper.platforms.zepto.public_data.tests.test_ads
"""
from scraper.platforms.zepto.public_data import ads

# ── real captured ids ────────────────────────────────────────────────────────
EN_OVEN = ("101|80d1b3ce711548e497b1bd158713d66f|2750|1788264745312|"
           "30600a76-a175-4584-8140-e6d119ff2aa9|||CPC|"
           "c522b8bb-fba9-40ae-82a4-69077d495c7b|c522b8bb-fba9-40ae-82a4-69077d495c7b||"
           "2410741|2410741|300a1056-ad32-430e-b5e4-41624b0494ed||0|P_INFO|||"
           "fee489ea-b688-441f-bdd5-3a57c2411787|68c08f6d-4d38-459c-b87b-ce71f0560d01|"
           "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5|30566884-bbd7-49fa-8c3f-43c90a571c9e|"
           "K_INFO|EXACT|bread|0|10|0|0")

# Ours. The campaign keyword is a COMPETITOR's brand, and it is not the query that
# was searched (`sourdough bread` was).
BRIK_PHRASE = ("101|27d77e75c84e4e518628b53f0c3e8451|1600|1788265895862|"
               "8e70a41c-7a6f-482b-ba44-277b0901fef7|||CPC|"
               "b9cea5fc-da5f-4045-9b67-c07831733746|b9cea5fc-da5f-4045-9b67-c07831733746||"
               "2373457|2373457|042b55a7-bfcf-46e8-8cc2-56ba2b4dc7cf||0|P_INFO|||"
               "0e8e3c72-a70e-44c5-8987-1f16520b41ed|49665e03-a09c-4a51-b5e0-cda18d152544|"
               "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5|30566884-bbd7-49fa-8c3f-43c90a571c9e|"
               "K_INFO|PHRASE|bakers dozen bread|0|0|0|0")

# Ours, matched SEMANTICALLY — a second mode beside K_INFO.
BRIK_SEMANTIC = ("101|801c427680094ca6a1562d804ae16249|1600|1788265902468|"
                 "2b52badd-153b-4383-b49d-fb045dfdb4a4|||CPC|"
                 "b9cea5fc-da5f-4045-9b67-c07831733746|b9cea5fc-da5f-4045-9b67-c07831733746||"
                 "2373457|2373457|5ec071fd-78df-41f6-b3ae-7298d9f96a3d||0|P_INFO|||"
                 "06d0fc37-fa97-430c-8d3f-07a808bb5920|5e4a9b9b-26b1-4f21-883b-43fa72837ba1|"
                 "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5|30566884-bbd7-49fa-8c3f-43c90a571c9e|"
                 "K_INFO_SEMANTIC|EXACT|bakers dozen sourdough bread|0|0|0|0")

# The brand id we store in cm_platform_accounts.account_ref for Zepto.
OUR_ADVERTISER = "b9cea5fc-da5f-4045-9b67-c07831733746"


def _pr(tags=None, **meta):
    return {"meta": {**meta, **({"tagsV2": tags} if tags is not None else {})}}


# ── is_sponsored ─────────────────────────────────────────────────────────────

def test_sponsored_tag_is_found_by_type_not_by_slot_key():
    """`tagsV2` is keyed by badge slot. Zepto put Sponsored at P3 and a discount at
    P0, but the slot is presentation, not meaning — matching the key would break on
    a renumber."""
    assert ads.is_sponsored(_pr({"P3": {"tagType": "SPONSORED"}})) is True
    assert ads.is_sponsored(_pr({"P9": {"tagType": "SPONSORED"}})) is True
    assert ads.is_sponsored(_pr({"P0": {"tagType": "SPONSORED"}})) is True


def test_a_discount_badge_is_not_an_ad():
    assert ads.is_sponsored(_pr({"P0": {"tagType": "DISCOUNT",
                                        "tagName": "Product Discount"}})) is False


def test_real_shape_both_badges_present():
    """What a live sponsored row actually looks like: a discount badge AND a
    sponsored badge together."""
    assert ads.is_sponsored(_pr({
        "P0": {"tagType": "DISCOUNT", "tagName": "Product Discount"},
        "P3": {"tagType": "SPONSORED", "tagName": "Sponsored"},
    })) is True


def test_is_fly_wheel_ad_is_NOT_the_ad_flag():
    """THE regression this file exists for. `is_fly_wheel_ad` sits on the same meta
    block and is false on confirmed ads — it marks organic re-ranking. Reading it as
    an ad flag is what made ads look invisible."""
    # A real sponsored row: flagged by the tag, while is_fly_wheel_ad says False.
    assert ads.is_sponsored(_pr({"P3": {"tagType": "SPONSORED"}},
                                is_fly_wheel_ad=False)) is True
    # And the converse must never be read as an ad.
    assert ads.is_sponsored(_pr({}, is_fly_wheel_ad=True)) is False


def test_unprovable_rows_report_organic_never_ad():
    """Absent, empty and malformed tag blocks all under-count ads rather than
    inventing them."""
    for bad in ({}, {"meta": {}}, {"meta": {"tagsV2": None}},
                {"meta": {"tagsV2": []}}, {"meta": {"tagsV2": {"P3": None}}},
                {"meta": {"tagsV2": {"P3": "SPONSORED"}}}):
        assert ads.is_sponsored(bad) is False, bad
    assert ads.is_sponsored(None) is False


# ── parse_ucl_id ─────────────────────────────────────────────────────────────

def test_decodes_a_real_competitor_ad():
    got = ads.parse_ucl_id(EN_OVEN)
    assert got["model"] == "CPC"
    assert got["advertiser_id"] == "c522b8bb-fba9-40ae-82a4-69077d495c7b"
    assert got["campaign_id"] == "2410741"
    assert got["store_id"] == "300a1056-ad32-430e-b5e4-41624b0494ed"
    assert got["match_type"] == "EXACT"
    assert got["keyword"] == "bread"


def test_our_own_advertiser_id_matches_the_account_ref_we_store():
    """Cross-check against cm_platform_accounts: the id Zepto stamps on our ads is
    the same brand id our write path asserts before going live."""
    assert ads.parse_ucl_id(BRIK_PHRASE)["advertiser_id"] == OUR_ADVERTISER
    assert ads.parse_ucl_id(BRIK_SEMANTIC)["advertiser_id"] == OUR_ADVERTISER


def test_the_keyword_is_the_CAMPAIGNS_not_the_query():
    """Searching `sourdough bread` returned this ad, but it was won by the campaign
    keyword `bakers dozen bread`. A consumer must attribute on the uclId keyword,
    never on the query it searched."""
    got = ads.parse_ucl_id(BRIK_PHRASE)
    assert got["keyword"] == "bakers dozen bread"
    assert got["match_type"] == "PHRASE"
    assert got["keyword"] != "sourdough bread"


def test_semantic_matching_is_a_second_mode():
    got = ads.parse_ucl_id(BRIK_SEMANTIC)
    assert got["keyword_mode"] == "K_INFO_SEMANTIC"
    assert got["match_type"] == "EXACT"
    assert got["keyword"] == "bakers dozen sourdough bread"


def test_multi_word_keywords_survive_the_pipe_split():
    assert " " in ads.parse_ucl_id(BRIK_SEMANTIC)["keyword"]


def test_campaign_id_requires_the_repeat():
    """Synthetic. The id is full of bare integers (a price, a timestamp); only the
    campaign id appears twice in a row. Without that guard the first 6-8 digit
    number wins and we attribute the slot to a campaign that does not exist."""
    fake = "101|abc|999999|1788264745312|x|||CPC|" + ("a" * 8 + "-1234-1234-1234-" + "b" * 12) \
           + "|" + ("a" * 8 + "-1234-1234-1234-" + "b" * 12) + "||K_INFO|EXACT|kw|0|0|0|0"
    assert "campaign_id" not in ads.parse_ucl_id(fake)


def test_the_trailing_four_are_kept_but_not_named():
    """They differ across ads (0|10|0|0 vs 0|0|70|0) and no meaning is established.
    Kept verbatim so the question stays answerable; deliberately not called 'bid'."""
    assert ads.parse_ucl_id(EN_OVEN)["unnamed_tail"] == [0, 10, 0, 0]
    assert "bid" not in ads.parse_ucl_id(EN_OVEN)


def test_missing_or_junk_ids_return_empty():
    for bad in (None, "", "not-a-ucl-id", 12345, "|||||"):
        assert ads.parse_ucl_id(bad) == {}


def test_every_key_is_optional_for_callers():
    """A partial id must not raise — it yields fewer keys."""
    got = ads.parse_ucl_id("101|abc|CPC|nope")
    assert isinstance(got, dict)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} Zepto ad-marker tests passed.")
