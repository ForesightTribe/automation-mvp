"""§D — what the automations API does differently for Zepto (ZC-D3, D4, D5, D6, D8, D9).

Pure or stubbed — no DB, no queue.

    python -m campaign_manager.tests.test_cm_service_zepto
"""
import asyncio
import inspect
import uuid
from datetime import datetime
from types import SimpleNamespace

from app.services import campaign_manager_service as svc
from campaign_manager import repo
from campaign_manager.marketplaces import match_types, min_daily_budget

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")


def _refused(fn, *args) -> str | None:
    try:
        fn(*args)
    except svc.EditError as e:
        return str(e)
    return None


# ── D8: minimum budget ──────────────────────────────────────────────────────

def test_zepto_publishes_a_500_minimum_blinkit_publishes_none():
    assert min_daily_budget("zepto") == 500
    assert min_daily_budget("blinkit") is None


def test_a_zepto_budget_below_500_is_refused_at_save():
    said = _refused(svc._check_budget, "zepto", 499)
    assert said and "₹500" in said and "Zepto" in said
    assert _refused(svc._check_budget, "zepto", 500) is None


def test_every_amount_is_checked_not_just_the_first():
    assert _refused(svc._check_budget, "zepto", 800, 300) is not None


def test_blinkit_budgets_stay_the_marketplaces_call():
    """Decided 2026-08-27: Blinkit publishes no minimum, so none is invented here."""
    assert _refused(svc._check_budget, "blinkit", 1) is None


def test_an_absent_amount_is_not_checked():
    assert _refused(svc._check_budget, "zepto", None) is None


# ── D8: match types ─────────────────────────────────────────────────────────

def test_phrase_exists_on_zepto_only():
    assert "PHRASE" in match_types("zepto") and "PHRASE" not in match_types("blinkit")
    assert _refused(svc._check_match_type, "zepto", "phrase") is None
    said = _refused(svc._check_match_type, "blinkit", "PHRASE")
    assert said and "EXACT, BROAD" in said


def test_an_unset_match_type_is_not_checked():
    assert _refused(svc._check_match_type, "blinkit", None) is None


# ── D4: the bid-rule form's data for a Zepto campaign ───────────────────────

def _zepto_campaign(**over):
    base = dict(campaign_type="PLA", scraped_at=datetime(2026, 9, 21, 21, 56),
                city_targeting="MANUAL", daily_budget=551,
                cities=[{"id": "8ed2…", "name": "Bengaluru", "included": True},
                        {"id": "c682…", "name": "Mysuru", "included": True},
                        {"id": "dead…", "name": "Hosur", "included": False}])
    base.update(over)
    return SimpleNamespace(**base)


def _kw(keyword, match_type, bid, floor, negative=False):
    return SimpleNamespace(keyword=keyword, match_type=match_type, bid_value=bid,
                           min_bid=floor, is_negative=negative)


def test_the_zepto_form_gets_its_keywords_without_negatives_and_in_cpc():
    kws = [_kw("pink toffee", "EXACT", 10, 10), _kw("pink toffee", "PHRASE", 12, 10),
           _kw("test", "EXACT", None, None, negative=True)]
    out = svc._zepto_bid_context(2427461, _zepto_campaign(), kws, cities=[])
    assert out.unit == "CPC"
    assert [(k.keyword, k.match_type, k.current_cpm, k.min_bid) for k in out.keywords] == [
        ("pink toffee", "EXACT", 10, 10), ("pink toffee", "PHRASE", 12, 10)]
    assert out.region_type == "CITY" and out.campaign_type == "PLA" and out.daily_budget == 551


def test_an_all_cities_zepto_campaign_reads_as_all():
    out = svc._zepto_bid_context(1, _zepto_campaign(city_targeting="ALL"), [], cities=[])
    assert out.region_type == "ALL"


def test_blinkit_bids_are_labelled_cpm():
    assert svc._BID_UNIT == {"blinkit": "CPM", "zepto": "CPC"}


# ── targeted cities, both marketplaces through one reader ───────────────────

def test_zepto_targeting_drops_excluded_cities():
    assert [c["name"] for c in repo.targeted_cities(_zepto_campaign(), "zepto")] == [
        "Bengaluru", "Mysuru"]


def test_a_zepto_all_cities_campaign_targets_everywhere():
    assert repo.targeted_cities(_zepto_campaign(city_targeting="ALL"), "zepto") is None


def test_blinkit_targeting_reads_region_type():
    c = SimpleNamespace(region_type="CITY", cities=[{"id": 1, "name": "Delhi"}])
    assert repo.targeted_cities(c, "blinkit") == [{"id": 1, "name": "Delhi"}]
    assert repo.targeted_cities(SimpleNamespace(region_type="PAN_INDIA", cities=[]),
                                "blinkit") is None


def test_an_unscraped_campaign_targets_everywhere():
    assert repo.targeted_cities(None, "zepto") is None


# ── D5: ad-account ids ──────────────────────────────────────────────────────

def test_a_blinkit_account_must_be_a_number():
    async def _never(*a, **k):
        raise AssertionError("must refuse before storing")

    orig = repo.set_advertiser
    repo.set_advertiser = _never
    try:
        asyncio.run(svc.set_advertiser(TENANT, "blinkit", "b9cea5fc-da5f"))
    except svc.EditError as e:
        assert "number" in str(e)
    else:
        raise AssertionError("must refuse")
    finally:
        repo.set_advertiser = orig


def test_a_zepto_brand_uuid_is_stored_as_is():
    stored = []

    async def _store(tenant_id, account, platform):
        stored.append((account, platform))

    orig = repo.set_advertiser
    repo.set_advertiser = _store
    try:
        asyncio.run(svc.set_advertiser(TENANT, "zepto", "b9cea5fc-da5f-4045-9b67-c07831733746"))
    finally:
        repo.set_advertiser = orig
    assert stored == [("b9cea5fc-da5f-4045-9b67-c07831733746", "zepto")]


def test_the_account_schema_accepts_both_shapes():
    from app.schemas.campaign_manager import AdvertiserIn
    assert AdvertiserIn(advertiser_id=19802).advertiser_id == 19802
    assert AdvertiserIn(advertiser_id="b9cea5fc").advertiser_id == "b9cea5fc"


# ── D6 / D7: every list and every job is per marketplace ────────────────────

def test_recent_actions_are_filtered_to_the_marketplace():
    assert '"marketplace") == marketplace' in inspect.getsource(svc.recent_actions)


def test_every_enqueue_goes_through_the_marketplace_stamp():
    """`_enqueue` adds the marketplace; a bare `enqueue(` call would queue an unnamed job,
    which the runner now refuses."""
    src = inspect.getsource(svc)
    body = src.split("async def _enqueue", 1)[1]
    assert "await enqueue(" not in body.split("\n\n\n", 1)[1], (
        "a job queued without `_enqueue` names no marketplace")


def test_enqueue_stamps_the_marketplace():
    seen = []

    async def _fake(session, **kw):
        seen.append(kw)
        return SimpleNamespace(id=1)

    orig = svc.enqueue
    svc.enqueue = _fake
    try:
        asyncio.run(svc._enqueue(None, "zepto", job_type="cm.set_budget", tenant_id=TENANT,
                                 params={"campaign": "1"}))
    finally:
        svc.enqueue = orig
    assert seen[0]["params"] == {"campaign": "1", "marketplace": "zepto"}


# ── D3: the campaign list says what can be automated ────────────────────────

def test_blinkit_campaigns_are_never_flagged():
    """No catalogue query at all for a marketplace with no limit (none exists here)."""
    assert asyncio.run(repo.automation_refusals(TENANT, "blinkit", [1, 2])) == {}


def test_nothing_to_look_up_means_nothing_flagged():
    assert asyncio.run(repo.automation_refusals(TENANT, "zepto", [])) == {}


# ── E3: the keyword picker's list, from the catalogue ───────────────────────

def _catalog_rows(rows, refused=None):
    """Run `list_catalog_keywords` over stubbed repo reads."""
    orig = (repo.list_catalog_keywords, repo.automation_refusals)

    async def _rows(tenant_id, platform, **_kw):
        return rows

    async def _refused(tenant_id, platform, ids, **_kw):
        return {c: why for c, why in (refused or {}).items() if c in set(ids)}

    repo.list_catalog_keywords, repo.automation_refusals = _rows, _refused
    try:
        return asyncio.run(svc.list_catalog_keywords(TENANT, "zepto"))
    finally:
        repo.list_catalog_keywords, repo.automation_refusals = orig


def test_the_picker_gets_every_bid_keyword_with_bid_floor_and_cpc():
    camp = SimpleNamespace(campaign_name="Tech Test", status="PAUSED")
    kws = [_kw("pink toffee", "EXACT", 10, 10), _kw("pink toffee", "PHRASE", 12, 10)]
    for k in kws:
        k.campaign_id, k.scraped_at = 2427461, datetime(2026, 9, 21)
    out = _catalog_rows([(k, camp) for k in kws])
    assert [(r.keyword, r.match_type, r.bid, r.min_bid, r.unit) for r in out] == [
        ("pink toffee", "EXACT", 10, 10, "CPC"), ("pink toffee", "PHRASE", 12, 10, "CPC")]
    assert out[0].campaign_name == "Tech Test"
    # The raw word AND what it means — the picker sorts and badges by the meaning.
    assert (out[0].status, out[0].state) == ("PAUSED", "paused")
    assert all(r.automatable for r in out)


def test_the_picker_never_offers_a_negative_keyword():
    neg = _kw("test", "EXACT", None, None, negative=True)
    neg.campaign_id, neg.scraped_at = 2427461, None
    assert _catalog_rows([(neg, None)]) == []


def test_a_campaign_automations_may_not_touch_is_flagged_not_hidden():
    k = _kw("bread", "EXACT", 8, 5)
    k.campaign_id, k.scraped_at = 77, None
    out = _catalog_rows([(k, SimpleNamespace(campaign_name="Auto", status="ACTIVE"))],
                        refused={77: "automatic bidding"})
    assert len(out) == 1
    assert (out[0].automatable, out[0].not_automatable_reason) == (False, "automatic bidding")


def test_a_keyword_whose_campaign_row_is_missing_still_comes_back():
    k = _kw("bagel", "BROAD", 9, 5)
    k.campaign_id, k.scraped_at = 99, None
    out = _catalog_rows([(k, None)])
    assert (out[0].campaign_id, out[0].campaign_name, out[0].state) == (99, None, None)


# ── E1: the marketplace list says which ones automations can drive ──────────

def test_the_marketplace_list_flags_automation_support_and_the_minimum():
    from app.services import reference_service

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    mps = [SimpleNamespace(slug=s, name=s.title(), color=None)
           for s in ("blinkit", "instamart", "zepto")]
    # rows · public snapshots · successful scrapes (either plane) · private scrapes
    answers = iter([mps, ["blinkit", "zepto"], ["blinkit", "instamart", "zepto"],
                    ["blinkit", "zepto"]])

    class _Session:
        async def execute(self, _stmt):
            return _Result(next(answers))

    out = {m["slug"]: m for m in asyncio.run(reference_service.list_marketplaces(_Session()))}
    assert out["blinkit"]["automations"] and out["zepto"]["automations"]
    assert out["instamart"]["automations"] is False
    assert out["zepto"]["min_daily_budget"] == 500
    assert out["blinkit"]["min_daily_budget"] is None
    # Zepto keyword bidding is switched off for now (2026-09-29); Blinkit's is on. A
    # marketplace without automations at all carries no reason.
    assert "Zepto" in (out["zepto"]["keyword_bidding_off"] or "")
    assert out["blinkit"]["keyword_bidding_off"] is None
    assert out["instamart"]["keyword_bidding_off"] is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} campaign-manager Zepto service tests passed.")
