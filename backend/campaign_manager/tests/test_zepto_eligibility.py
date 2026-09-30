"""§C step 1 — which Zepto campaigns and rules the automations may run (ZC-C3, C14), the
IST date fix (C13) and the hold wording (C16).

Pure or fully stubbed — no Zepto, no DB, no browser.

    python -m campaign_manager.tests.test_zepto_eligibility
"""
import asyncio
import copy
import uuid

from campaign_manager import repo, writes
from campaign_manager.marketplaces import automation_refusal, rule_needs_location
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import eligibility, translate
from campaign_manager.tests._zepto_flags import zepto_bidding_on
from campaign_manager.tests.test_zepto_translate import (
    CAMPAIGN_ID, GET_DETAIL, TARGETING_OPTIONS)


def _detail(campaign_type="PLA", bidding="KEYWORD") -> dict:
    d = copy.deepcopy(GET_DETAIL)
    d["campaign_type"] = campaign_type
    d.setdefault("campaign_configs", {})["bid_targeting"] = bidding
    return d


# ── C3: the eligibility rule itself ──────────────────────────────────────────

def test_only_keyword_bid_product_ads_are_automatable():
    assert eligibility.refusal("PLA", "KEYWORD") is None
    assert "Display" in eligibility.refusal("Display", "KEYWORD")
    assert "AUTO" in eligibility.refusal("PLA", "AUTO")


def test_the_vocabulary_is_case_and_space_tolerant():
    assert eligibility.refusal(" pla ", "keyword") is None


def test_a_missing_value_is_no_opinion_not_a_refusal():
    """A renamed field on Zepto's side must not turn into every write failing."""
    assert eligibility.refusal(None, None) is None
    assert eligibility.refusal("PLA", "") is None


def test_the_real_tech_test_read_is_automatable():
    """The golden fixture is 2427461 as Zepto returned it: PLA, bid by KEYWORD — where the
    bidding mode lives in `campaign_configs.bid_targeting`, not at the top level."""
    assert GET_DETAIL["campaign_type"] == "PLA"
    assert GET_DETAIL["campaign_configs"]["bid_targeting"] == "KEYWORD"
    assert eligibility.refusal_from_detail(GET_DETAIL) is None
    assert zad.automation_refusal(GET_DETAIL) is None


def test_an_auto_campaign_read_is_refused():
    assert "AUTO" in zad.automation_refusal(_detail(bidding="AUTO"))


def test_the_api_safe_dispatcher():
    assert automation_refusal("zepto", "PLA", "AUTO") is not None
    assert automation_refusal("zepto", "PLA", "KEYWORD") is None
    # Blinkit puts no limit on which campaigns are automated — and never will by accident.
    assert automation_refusal("blinkit", "Display", "AUTO") is None
    assert automation_refusal(None, "Display", "AUTO") is None


# ── C3: the write-time backstop ─────────────────────────────────────────────

def _put_with(detail) -> list:
    """Drive `apply_budget` against `detail`; return the PUTs that reached Zepto."""
    sent = []

    async def fake_rebased(client, campaign_id):
        return translate.to_put(detail, TARGETING_OPTIONS, campaign_id), detail

    async def fake_update(client, campaign_id, payload):
        sent.append(payload)
        return {"ok": True}

    async def fake_detail(client, campaign_id):
        return detail

    orig = (zad._rebased_payload, zad.zc.update_campaign, zad.zc.get_campaign_detail)
    zad._rebased_payload, zad.zc.update_campaign, zad.zc.get_campaign_detail = (
        fake_rebased, fake_update, fake_detail)
    try:
        asyncio.run(zad.apply_budget(None, CAMPAIGN_ID, 600))
    finally:
        zad._rebased_payload, zad.zc.update_campaign, zad.zc.get_campaign_detail = orig
    return sent


def test_a_write_to_an_ineligible_campaign_is_refused_before_the_PUT():
    try:
        _put_with(_detail(bidding="AUTO"))
    except writes.WriteRefused as e:
        assert "not automatable" in str(e) and "Nothing was sent" in str(e)
    else:
        raise AssertionError("must refuse")


def test_a_write_to_an_eligible_campaign_still_goes_through():
    assert len(_put_with(_detail())) == 1


def test_a_status_write_is_refused_when_the_caller_says_so():
    """Start/stop are dedicated endpoints with no read of their own, so the engines pass
    the verdict of the read they already made."""
    outcome: dict = {}
    ok = asyncio.run(writes.apply_status(
        object(), None, run_id="t", campaign_id=1, target="paused", current="running",
        dry_run=True, outcome=outcome, not_automatable="it uses AUTO bidding"))
    assert ok is False
    assert "not automatable" in outcome["reason"]


def test_the_writes_helper_is_optional_on_the_adapter():
    assert writes.automation_refusal(object(), {"campaign_type": "Display"}) is None
    assert writes.automation_refusal(zad, _detail("Display")) is not None


def test_the_budget_engine_leaves_an_ineligible_campaign_alone():
    """Neither a budget write nor a start: a stopped AUTO campaign in its window would
    otherwise be RESTARTED, and a start/stop has no adapter-side backstop."""
    from campaign_manager.tests import test_budget_apply as tba

    tba.FakeAdapter.automation_refusal = staticmethod(lambda detail: "it uses AUTO bidding")
    try:
        assert tba._run(status="paused", toggle=True, now=tba.NOW_IN_WINDOW) == []
        assert tba._run(status="running", toggle=True, now=tba.NOW_IN_WINDOW) == []
    finally:
        del tba.FakeAdapter.automation_refusal
    # …and without the refusal, the same campaign is acted on as before.
    assert tba._run(status="running", toggle=True, now=tba.NOW_IN_WINDOW) == [("budget", 1500.0)]


# ── C3: at save ─────────────────────────────────────────────────────────────

def test_a_marketplace_without_a_limit_never_queries_the_catalogue():
    """Blinkit: `require_automatable` returns before touching the DB (none exists here)."""
    asyncio.run(repo.require_automatable(uuid.uuid4(), "blinkit", 1))


# ── C14: a Zepto bid rule must name a city or a store ───────────────────────

def test_zepto_needs_a_location_blinkit_does_not():
    assert rule_needs_location("zepto") is True
    assert rule_needs_location("blinkit") is False
    assert zad.REQUIRES_RULE_LOCATION is True


@zepto_bidding_on
def test_a_zepto_rule_with_no_city_is_placed_from_the_campaigns_targeting():
    """C14's answer is not a refusal: `create_bid_rule` asks `pick_rule_location` for a city
    the campaign actually runs in, and refuses only if there is none.
    The placing itself is covered by `test_zepto_rule_location.py`."""
    assert repo.NotAutomatable is not None
    asked = []

    async def _pick(tenant_id, platform, campaign_id):
        asked.append((platform, campaign_id))
        return None, ["Belgavi"]

    async def _automatable(tenant_id, platform, campaign_id):
        return None

    orig = (repo.pick_rule_location, repo.require_automatable)
    repo.pick_rule_location, repo.require_automatable = _pick, _automatable
    try:
        asyncio.run(repo.create_bid_rule(uuid.uuid4(), "zepto", CAMPAIGN_ID, "Tech Test",
                                         "pink toffee", 3, 10))
    except repo.NotAutomatable as e:
        assert "Belgavi" in str(e) and "Nothing was created" in str(e)
    else:
        raise AssertionError("must refuse when nowhere can be resolved")
    finally:
        repo.pick_rule_location, repo.require_automatable = orig
    assert asked == [("zepto", CAMPAIGN_ID)]


def test_the_engine_skips_a_zepto_rule_that_would_fall_back_to_bengaluru():
    """What `bid.run` checks: the anchor store's source is `default` only when the rule has
    no city and no coordinates."""
    from types import SimpleNamespace

    from campaign_manager import bid

    bare = SimpleNamespace(city_id=None, lat=None, lon=None, location_name=None)
    assert bid.measurement_stores(bare, {})[0].source == "default"
    pinned = SimpleNamespace(city_id=None, lat=12.9, lon=77.6, location_name="HSR")
    assert bid.measurement_stores(pinned, {})[0].source == "rule"


# ── C13: dates on an Indian calendar ────────────────────────────────────────

def test_an_ist_timestamp_keeps_its_date():
    assert translate._date_only("2026-08-21T12:20:30.808196+05:30") == "2026-08-21"


def test_a_utc_timestamp_late_in_the_day_is_the_next_indian_date():
    """20:00 UTC is 01:30 IST the next day — slicing at 'T' would say the 20th."""
    assert translate._date_only("2026-08-20T20:00:00Z") == "2026-08-21"
    assert translate._date_only("2026-08-20T20:00:00+00:00") == "2026-08-21"


def test_a_value_without_an_offset_is_taken_as_ist():
    assert translate._date_only("2026-08-21 23:30:00") == "2026-08-21"
    assert translate._date_only("2026-08-21") == "2026-08-21"


def test_none_and_junk_behave_as_before():
    assert translate._date_only(None) is None
    assert translate._date_only("not a dateTjunk") == "not a date"


# ── C16: hold wording ───────────────────────────────────────────────────────

def test_an_explained_hold_does_not_claim_the_wrong_cause():
    """Blinkit's only hold is a spent budget; Zepto's can be an empty wallet, where "out of
    budget" would send a person to the wrong fix."""
    assert writes.state_words("held") == "on hold (out of budget)"
    assert writes.state_words("held", "campaign is on hold — the ad wallet is empty") == "on hold"
    assert writes.state_words("paused", "anything") == "stopped"
    assert writes.state_words(None) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} zepto eligibility tests passed.")
