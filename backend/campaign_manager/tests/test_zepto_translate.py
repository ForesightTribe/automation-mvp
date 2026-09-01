"""Golden-payload test for the Zepto campaign PUT.

**The most important test in the Zepto adapter**, and for the same reason as its
Blinkit sibling `test_restart_payload.py`: budget and bid are both a WHOLE-campaign
PUT, so a drift in the translator does not fail loudly — it silently rewrites live
campaign config. Geo targeting, the product list and every other keyword's bid all
ride in the same body.

## The proof

`GET_DETAIL` and `TARGETING_OPTIONS` are the real responses Zepto returned for
campaign 2427461 on 2026-08-21, and `CAPTURED_PUT` is the body Zepto's OWN DASHBOARD
then sent when a human changed the daily budget from 500 to 502.

So: feed the GET through `translate.to_put()` and diff against `CAPTURED_PUT`. The
only difference must be `daily_budget: 500 -> 502` — the edit the human actually
made. Anything else is a bug in us, not in the test.

That is a stronger claim than "the translator produces something plausible": it says
our payload is byte-equivalent to what the dashboard itself produces from the same
state. It is also how the `start_date` bug was found — the GET returns a full ISO
timestamp where the PUT wants a bare date, which no amount of reading would reveal.

Pure — no Zepto, no DB, no browser. Run with:

    python -m campaign_manager.tests.test_zepto_translate
"""
from campaign_manager.marketplaces.zepto import translate

CAMPAIGN_ID = 2427461

# ── The real thing, captured from Zepto's own network traffic ───────────────

GET_DETAIL = {
    "last_updated_on": "2026-08-21T12:20:31.201033+05:30",
    "brand_id": "b9cea5fc-da5f-4045-9b67-c07831733746",
    "brand_name": "Brik Oven",
    "campaign_id": 0,
    "id": 2427461,
    "client_id": 30003703,
    "campaign_type": "PLA",
    "budget_type": "DAILY_BUDGET_WITH_MAX_CAP",
    "campaign_name": "Foresight | Tech Test",
    "ro_id": "",
    "alias": "",
    "campaign_sub_type": "AUCTION_UP_SELL",
    "status": "ACTIVE",
    "effective_status": "",
    "bid": 0,
    "chargeable_bid": 0,
    "budget": -1,
    "spend_cap": 0,
    "spend": 0,
    "creation_date": "2026-08-21T12:20:30.808264+05:30",
    "start_date": "2026-08-21T12:20:30.808196+05:30",
    "end_date": None,
    "bidding_strategy_type": "FIXED",
    "spend_last_updated_on": None,
    "daily_budget": 500,
    "daily_budget_type": "",
    "daily_budget_last_update": None,
    "keyword_bidding_strategy": "",
    "keyword_targeting_enabled": False,
    "original_start_date": None,
    "ad_assets_pla": [
        {
            "id": 0,
            "campaign_id": 0,
            "filter_name": "",
            "product_variant_id": "4770571e-2278-4efa-a152-9e5664eaae0b",
            "operator": "",
            "mrp": 80,
            "product_name": "Brik Oven Pretzel Bagel",
            "image_link": "https://ik.imagekit.io/jupdt2k6txi/cms/product_variant/28ce450c-1fcf-4292-b8d6-9d4b2b61fd51.jpeg",
            "status": "",
            "tiers": [
                "select"
            ]
        }
    ],
    "keyword_config": [
        {
            "campaign_id": 2427461,
            "keyword": "pink toffee",
            "match_type": "EXACT",
            "is_negative": False,
            "status": "",
            "bid_value": 10
        }
    ],
    "campaign_segments": None,
    "city_targeting": [],
    "store_targeting": [],
    "subcategory_targeting": None,
    "campaign_configs": {
        "id": 600732,
        "campaign_id": 2427461,
        "city_targeting": "ALL",
        "store_targeting": "ALL",
        "priority": "NORMAL",
        "product_targeting": "MANUAL",
        "bid_targeting": "KEYWORD",
        "multiplier_config": {
            "pdp": {
                "base": 0,
                "premium": 0,
                "super_saver": 0
            },
            "tos": {
                "base": 0,
                "premium": 0,
                "super_saver": 0
            },
            "zpu": {
                "base": 0,
                "premium": 0,
                "super_saver": 0
            },
            "top_picks": {
                "base": 0,
                "premium": 0,
                "super_saver": 0
            }
        }
    },
    "is_foc": False
}

TARGETING_OPTIONS = {
    "categories": [
        {
            "id": "4b938e02-7bde-4479-bc0a-2b54cb6bd5f5",
            "name": "Dairy, Bread & Eggs",
            "subcategories": [
                {
                    "id": "b26b6bcf-7c81-48e7-a9bc-fec3825bad2a",
                    "name": "Top Picks"
                },
                {
                    "id": "1806412f-190a-46b1-be42-4237a4146eb1",
                    "name": "Paneer & Cream"
                },
                {
                    "id": "30566884-bbd7-49fa-8c3f-43c90a571c9e",
                    "name": "Breads & Buns"
                },
                {
                    "id": "f594b28a-4775-48ac-8840-b9030229ff87",
                    "name": "Cheese"
                }
            ]
        }
    ],
    "cities": [
        {
            "id": "5a17386b-33fb-43d4-bf71-258277768fcc",
            "name": "Kochi"
        },
        {
            "id": "d0c5c4c5-ab54-407d-a6f0-d924610c86a6",
            "name": "Palakkad"
        },
        {
            "id": "8ed26cb7-eb7d-4b7b-8d8c-3e93d5855bdd",
            "name": "Bengaluru"
        },
        {
            "id": "a2b4beb2-7c4d-4749-bc95-5b04d4adf837",
            "name": "Belgavi"
        },
        {
            "id": "8e6bfeb7-25f2-41c2-be52-75fc98c8025c",
            "name": "Tumkuru"
        },
        {
            "id": "c68232c5-7375-43fe-a7ce-510d7530cbf6",
            "name": "Mysuru"
        },
        {
            "id": "ddf073f6-808e-491a-9cd8-6f1763b38aaa",
            "name": "Hubballi"
        },
        {
            "id": "df73cdc7-5840-4f42-bb66-c84a6f52b9c4",
            "name": "Davanagere"
        },
        {
            "id": "a730455f-f1a8-4a3f-83f8-a427d82ffe0b",
            "name": "Hosur"
        }
    ],
    "custom_audiences": []
}

# What the dashboard sent after the human typed 502.
CAPTURED_PUT = {
    "brand_id": "b9cea5fc-da5f-4045-9b67-c07831733746",
    "campaign_type": "PLA",
    "campaign_sub_type": "AUCTION_UP_SELL",
    "campaign_name": "Foresight | Tech Test",
    "ro_id": "",
    "budget_type": "DAILY_BUDGET_WITH_MAX_CAP",
    "bid": 0,
    "daily_budget": 502,
    "lifetime_budget": 0,
    "bidding_strategy_type": "FIXED",
    "start_date": "2026-08-21",
    "end_date": None,
    "bid_multipliers": {
        "tos": {
            "base": 0,
            "premium": 0,
            "super_saver": 0
        },
        "top_picks": {
            "base": 0,
            "premium": 0,
            "super_saver": 0
        },
        "pdp": {
            "base": 0,
            "premium": 0,
            "super_saver": 0
        },
        "zpu": {
            "base": 0,
            "premium": 0,
            "super_saver": 0
        },
        "time": {
            "time": {}
        }
    },
    "geo_targeting": {
        "city": {
            "include": [
                "5a17386b-33fb-43d4-bf71-258277768fcc",
                "d0c5c4c5-ab54-407d-a6f0-d924610c86a6",
                "8ed26cb7-eb7d-4b7b-8d8c-3e93d5855bdd",
                "a2b4beb2-7c4d-4749-bc95-5b04d4adf837",
                "8e6bfeb7-25f2-41c2-be52-75fc98c8025c",
                "c68232c5-7375-43fe-a7ce-510d7530cbf6",
                "ddf073f6-808e-491a-9cd8-6f1763b38aaa",
                "df73cdc7-5840-4f42-bb66-c84a6f52b9c4",
                "a730455f-f1a8-4a3f-83f8-a427d82ffe0b"
            ],
            "exclude": []
        },
        "type": "ALL"
    },
    "product_config": {
        "product_variant_ids": [
            "4770571e-2278-4efa-a152-9e5664eaae0b"
        ],
        "type": "MANUAL"
    },
    "bid_targeting": {
        "targeting_type": "KEYWORD",
        "subcategory_targeting": []
    },
    "keyword_targeting": [
        {
            "text": "pink toffee",
            "match_type": "EXACT",
            "bid_value": 10
        }
    ],
    "campaignId": "2427461"
}


def test_translator_reproduces_the_dashboards_payload():
    """Our payload must equal the dashboard's, except the human's own edit."""
    ours = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    ours["daily_budget"] = CAPTURED_PUT["daily_budget"]      # apply the same edit
    differences = translate.diff(ours, CAPTURED_PUT)
    assert not differences, (
        "translator drifted from the dashboard's real payload:\n  "
        + "\n  ".join(differences)
    )


def test_untouched_translation_differs_only_by_the_edit():
    """Without applying the edit, exactly ONE field should differ."""
    ours = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    assert translate.diff(ours, CAPTURED_PUT) == [".daily_budget: 500 -> 502"]


def test_start_date_is_truncated_to_a_bare_date():
    """The GET returns an ISO timestamp; the PUT takes a date. Echoing the
    timestamp back would shift the campaign's start date."""
    assert "T" in GET_DETAIL["start_date"], "fixture no longer exercises this"
    ours = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    assert ours["start_date"] == "2026-08-21"


def test_keywords_are_keyed_by_text_AND_match_type():
    """Zepto bids one keyword under several match types at different rates, so
    collapsing on text alone would merge distinct bid targets."""
    bids = translate.bids_from_detail(GET_DETAIL)
    assert bids == {("pink toffee", "EXACT"): 10}
    assert translate.keyword_key("x", "BROAD") != translate.keyword_key("x", "EXACT")


def test_negative_keywords_never_become_bid_targets():
    detail = {**GET_DETAIL, "keyword_config": [
        {"keyword": "cheap", "match_type": "EXACT", "is_negative": True, "bid_value": 0},
        {"keyword": "pink toffee", "match_type": "EXACT", "is_negative": False, "bid_value": 10},
    ]}
    assert list(translate.bids_from_detail(detail)) == [("pink toffee", "EXACT")]
    assert [k["text"] for k in translate.to_put(
        detail, TARGETING_OPTIONS, CAMPAIGN_ID)["keyword_targeting"]] == ["pink toffee"]


def test_diff_ignores_list_reordering_but_catches_membership():
    """City order is not meaningful; a changed member is."""
    assert translate.diff({"a": [1, 2, 3]}, {"a": [3, 1, 2]}) == []
    assert translate.diff({"a": [1, 2]}, {"a": [1, 9]}) != []


def test_lifetime_budget_none_sentinel():
    """The GET spells 'no lifetime budget' as -1; the PUT spells it 0."""
    assert translate.to_put({**GET_DETAIL, "budget": -1},
                            TARGETING_OPTIONS, CAMPAIGN_ID)["lifetime_budget"] == 0
    assert translate.to_put({**GET_DETAIL, "budget": 5000},
                            TARGETING_OPTIONS, CAMPAIGN_ID)["lifetime_budget"] == 5000


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto-translate tests passed.")
