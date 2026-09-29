"""Golden test #2 — a chosen-cities, multi-keyword campaign WITH a negative keyword.

The first golden test (`test_zepto_translate.py`) was captured on an all-cities campaign
with one keyword, so it could not see three bugs that only this shape exposes:

  ZC-A12  `targeting-options` called without the dashboard's params → empty city list.
  ZC-A13  chosen cities PUT as GET-shaped objects instead of the dashboard's id strings.
  ZC-A14  negative keywords dropped from `keyword_targeting` — deleting them on any write.

Fixtures are REAL: Tech Test 2427461, set by hand to 2 cities (Bengaluru, Mysuru), one
keyword under EXACT/PHRASE/BROAD, and a negative keyword; read back and then saved from
the dashboard with the daily budget 550 → 551 (2026-09-21). Full captures live in the
gitignored `zepto-cm-exp/captures/` (body only — no credentials).

    python -m campaign_manager.tests.test_zepto_translate_manual
"""
import asyncio
import copy

from campaign_manager import writes
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.tests.test_zepto_translate import TARGETING_OPTIONS

CAMPAIGN_ID = 2427461
BENGALURU, MYSURU = "8ed26cb7-eb7d-4b7b-8d8c-3e93d5855bdd", "c68232c5-7375-43fe-a7ce-510d7530cbf6"
_MULT = {"base": 0, "premium": 0, "super_saver": 0}

# GET /ads-bff/api/v1/campaigns/pla/2427461, 2026-09-21 (fields the PUT reads).
GET_DETAIL = {
    "brand_id": "b9cea5fc-da5f-4045-9b67-c07831733746",
    "brand_name": "Brik Oven",
    "campaign_id": 0,
    "id": 2427461,
    "campaign_type": "PLA",
    "budget_type": "DAILY_BUDGET_WITH_MAX_CAP",
    "campaign_name": "Foresight | Tech Test",
    "ro_id": "",
    "campaign_sub_type": "AUCTION_UP_SELL",
    "status": "PAUSED",
    "bid": 0,
    "budget": -1,
    "start_date": "2026-08-21T12:20:30.808196+05:30",
    "end_date": None,
    "bidding_strategy_type": "FIXED",
    "daily_budget": 550,
    "ad_assets_pla": [{"product_variant_id": "4770571e-2278-4efa-a152-9e5664eaae0b",
                       "product_name": "Brik Oven Pretzel Bagel"}],
    "keyword_config": [
        {"campaign_id": 2427461, "keyword": "pink toffee", "match_type": "EXACT",
         "is_negative": False, "status": "", "bid_value": 10},
        {"campaign_id": 2427461, "keyword": "pink toffee", "match_type": "PHRASE",
         "is_negative": False, "status": "", "bid_value": 10},
        {"campaign_id": 2427461, "keyword": "pink toffee", "match_type": "BROAD",
         "is_negative": False, "status": "", "bid_value": 10},
        {"campaign_id": 2427461, "keyword": "test", "match_type": "EXACT",
         "is_negative": True, "status": "", "bid_value": 0},
    ],
    "city_targeting": [
        {"campaign_id": 2427461, "city_id": BENGALURU, "is_included": True, "is_active": True},
        {"campaign_id": 2427461, "city_id": MYSURU, "is_included": True, "is_active": True},
    ],
    "store_targeting": [],
    "subcategory_targeting": None,
    "campaign_configs": {
        "city_targeting": "MANUAL", "store_targeting": "ALL", "product_targeting": "MANUAL",
        "bid_targeting": "KEYWORD",
        "multiplier_config": {"pdp": _MULT, "tos": _MULT, "zpu": _MULT, "top_picks": _MULT},
    },
}

# What the dashboard sent when the budget was edited 550 → 551 (request body, verbatim).
CAPTURED_PUT = {
    "brand_id": "b9cea5fc-da5f-4045-9b67-c07831733746",
    "campaign_type": "PLA",
    "campaign_sub_type": "AUCTION_UP_SELL",
    "campaign_name": "Foresight | Tech Test",
    "ro_id": "",
    "budget_type": "DAILY_BUDGET_WITH_MAX_CAP",
    "bid": 0,
    "daily_budget": 551,
    "lifetime_budget": 0,
    "bidding_strategy_type": "FIXED",
    "start_date": "2026-08-21",
    "end_date": None,
    "bid_multipliers": {"pdp": _MULT, "tos": _MULT, "top_picks": _MULT, "zpu": _MULT,
                        "time": {"time": {}}},
    "geo_targeting": {"city": {"include": [BENGALURU, MYSURU], "exclude": []},
                      "type": "MANUAL"},
    "product_config": {"product_variant_ids": ["4770571e-2278-4efa-a152-9e5664eaae0b"],
                       "type": "MANUAL"},
    "bid_targeting": {"targeting_type": "KEYWORD", "subcategory_targeting": []},
    "keyword_targeting": [
        {"text": "test", "match_type": "EXACT", "is_negative": True},
        {"text": "pink toffee", "match_type": "EXACT", "bid_value": 10, "min_bid": 10},
        {"text": "pink toffee", "match_type": "PHRASE", "bid_value": 10, "min_bid": 10},
        {"text": "pink toffee", "match_type": "BROAD", "bid_value": 10, "min_bid": 10},
    ],
    "campaignId": "2427461",
}


def _dashboard_without_min_bid():
    """The dashboard adds each bidding keyword's `min_bid`; we deliberately do not (an
    August save without it was accepted). Everything else must match exactly."""
    put = copy.deepcopy(CAPTURED_PUT)
    for k in put["keyword_targeting"]:
        k.pop("min_bid", None)
    return put


def test_translator_reproduces_the_dashboards_manual_city_payload():
    ours = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    ours["daily_budget"] = 551                                  # the human's own edit
    differences = translate.diff(ours, _dashboard_without_min_bid())
    assert not differences, "drifted from the dashboard:\n  " + "\n  ".join(differences)


def test_untouched_translation_differs_only_by_the_edit():
    ours = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    assert translate.diff(ours, _dashboard_without_min_bid()) == [".daily_budget: 550 -> 551"]


def test_chosen_cities_are_sent_as_id_strings():
    """ZC-A13: the GET's objects must not reach the PUT."""
    geo = translate.geo_targeting(GET_DETAIL, TARGETING_OPTIONS)
    assert geo == {"city": {"include": [BENGALURU, MYSURU], "exclude": []}, "type": "MANUAL"}


def test_excluded_and_inactive_cities_are_handled():
    detail = {**GET_DETAIL, "city_targeting": [
        {"city_id": BENGALURU, "is_included": True, "is_active": True},
        {"city_id": MYSURU, "is_included": False, "is_active": True},
        {"city_id": "gone", "is_included": True, "is_active": False},
    ]}
    assert translate.geo_targeting(detail, TARGETING_OPTIONS)["city"] == {
        "include": [BENGALURU], "exclude": [MYSURU]}


def test_negative_keywords_travel_first_and_without_a_bid():
    """ZC-A14: the PUT's keyword list replaces the campaign's, so a negative left out is a
    negative deleted."""
    kws = translate.keyword_targeting(GET_DETAIL)
    assert kws[0] == {"text": "test", "match_type": "EXACT", "is_negative": True}
    assert [(k["text"], k["match_type"]) for k in kws[1:]] == [
        ("pink toffee", "EXACT"), ("pink toffee", "PHRASE"), ("pink toffee", "BROAD")]


def test_an_empty_city_list_is_refused():
    """ZC-A12's safety net: an all-cities campaign with no city list means targeting-options
    failed us; a chosen-cities one with none would target nowhere."""
    empty_all = translate.to_put({**GET_DETAIL, "campaign_configs": {
        **GET_DETAIL["campaign_configs"], "city_targeting": "ALL"}}, {"cities": []}, CAMPAIGN_ID)
    assert translate.write_refusal(empty_all)
    empty_manual = translate.to_put({**GET_DETAIL, "city_targeting": []},
                                    TARGETING_OPTIONS, CAMPAIGN_ID)
    assert translate.write_refusal(empty_manual)
    assert translate.write_refusal(translate.to_put(
        GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)) is None


def test_a_bid_rule_never_lands_on_a_negative_keyword():
    """A rule for `test`/EXACT must not find the negative `test`/EXACT and give it a bid."""
    payload = translate.to_put(GET_DETAIL, TARGETING_OPTIONS, CAMPAIGN_ID)
    try:
        zad._keyword_index(payload, CAMPAIGN_ID, "test", "EXACT")
    except writes.WriteRefused:
        pass
    else:
        raise AssertionError("a negative keyword must not be a bid target")
    assert zad._keyword_index(payload, CAMPAIGN_ID, "pink toffee", "PHRASE") == 2


def test_targeting_options_is_asked_the_dashboards_way():
    """ZC-A12: with only `brand_id` Zepto answers an EMPTY city list (verified live)."""
    seen = {}

    class _Client:
        brand_id = "b9cea5fc-da5f-4045-9b67-c07831733746"

        async def get_json(self, path, **kw):
            seen.update(kw.get("params") or {})
            return {"cities": []}

    asyncio.run(zc.get_targeting_options(_Client(), campaign_type="PLA",
                                         campaign_sub_type="AUCTION_UP_SELL"))
    assert seen["include"] == "category,geo"
    assert seen["campaign_type"] == "PLA" and seen["campaign_sub_type"] == "AUCTION_UP_SELL"


def test_a_budget_write_on_this_campaign_sends_the_dashboards_body():
    """End to end through the adapter: the PUT we would send for 550 → 551 is the
    dashboard's own save, minus `min_bid`."""
    sent = {}
    orig = (zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign)

    async def detail(client, campaign_id):
        return copy.deepcopy(GET_DETAIL)

    async def options(client, **_):
        return TARGETING_OPTIONS

    async def update(client, campaign_id, payload):
        sent.update(payload)
        return {"message": "Campaign updated successfully"}

    zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign = detail, options, update

    class _C:
        brand_ids = ["b9cea5fc-da5f-4045-9b67-c07831733746"]

    try:
        asyncio.run(zad.apply_budget(_C(), CAMPAIGN_ID, 551))
    finally:
        zc.get_campaign_detail, zc.get_targeting_options, zc.update_campaign = orig
    assert translate.diff(sent, _dashboard_without_min_bid()) == []


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
    print(f"\n{len(tests) - failed}/{len(tests)} manual-city golden tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
