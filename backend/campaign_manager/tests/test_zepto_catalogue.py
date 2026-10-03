"""ZC-B — the Zepto campaign catalogue (`zepto_ad_campaigns` + `zepto_ad_campaign_keywords`).

Filled like Blinkit's: the daily ads scrape reads every campaign (list, all pages) and each
PLA campaign's detail + keyword floors; the campaign manager's Refresh re-reads the LIST
fields only; landed writes patch it in place. No network, no DB — Zepto and the session are
faked; fixtures are real captures:

  * LIST_ROW      — a recorded dashboard `GET /ads-bff/api/v1/campaigns` row (2026-08-21)
  * MANUAL detail — Tech Test 2427461 with 2 cities, 3 match types, a negative (2026-09-21)
  * ALL detail    — Tech Test 2427461 as first captured, all cities (2026-08-21)

    python -m campaign_manager.tests.test_zepto_catalogue
"""
import asyncio
import copy
import uuid

from sqlalchemy.dialects import postgresql

from campaign_manager import repo
from campaign_manager.marketplaces.zepto import adapter as zad
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.tests import test_zepto_translate as ALL_CASE
from campaign_manager.tests import test_zepto_translate_manual as MANUAL_CASE
from scraper.platforms.zepto.dashboard_data.seller import parser as P
from scraper.platforms.zepto.dashboard_data.seller import scraper as S
from scraper.platforms.zepto.dashboard_data.seller import storage as ST

TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"
JOB = str(uuid.uuid4())
BENGALURU, MYSURU = MANUAL_CASE.BENGALURU, MANUAL_CASE.MYSURU
NAMES = {BENGALURU: "Bengaluru", MYSURU: "Mysuru"}

LIST_ROW = {
    "name_with_active_status": {"campaign_name": "Foresight | Tech Test", "is_active": True},
    "brand_id": "b9cea5fc-da5f-4045-9b67-c07831733746", "brand_name": "Brik Oven",
    "campaign_type": "PLA", "campaign_sub_type": "AUCTION_UP_SELL", "daily_budget": "500",
    "bid_targeting_type": "KEYWORD", "status": "ACTIVE", "spend": "0", "lifetime_budget": "",
    "start_date": "2026-08-21 12:20:30", "end_date": "", "base_bid": "0.00",
    "campaign_id": 2427461, "campaign_name": "Foresight | Tech Test",
}
DISPLAY_ROW = {**LIST_ROW, "campaign_id": 1111111, "campaign_name": "A banner",
               "campaign_type": "Display", "campaign_sub_type": "PCA",
               "bid_targeting_type": "NOT_SET", "status": "PAUSED"}


# ── parsing ─────────────────────────────────────────────────────────────────

def test_a_list_row_becomes_the_list_columns():
    row = P.parse_catalog_list_row(LIST_ROW, TENANT, JOB)
    assert row["upsert_key"] == f"{TENANT}:zepto:campaign:2427461"
    assert row["campaign_id"] == 2427461 and row["campaign_name"] == "Foresight | Tech Test"
    assert row["status"] == "ACTIVE" and row["bid_targeting_type"] == "KEYWORD"
    assert row["daily_budget"] == 500 and row["lifetime_budget"] is None     # "" = none
    assert row["campaign_start_date"].isoformat() == "2026-08-21T12:20:30"
    assert row["campaign_end_date"] is None
    assert not set(row) & {"cities", "city_targeting", "product_variant_ids"}, \
        "a list row must not carry detail columns — storage would blank them"


def test_chosen_cities_are_stored_with_names():
    d = P.parse_catalog_detail(copy.deepcopy(MANUAL_CASE.GET_DETAIL), NAMES)
    assert d["city_targeting"] == "MANUAL"
    assert d["cities"] == [{"id": BENGALURU, "name": "Bengaluru", "included": True},
                           {"id": MYSURU, "name": "Mysuru", "included": True}]
    assert d["product_variant_ids"] == ["4770571e-2278-4efa-a152-9e5664eaae0b"]
    assert d["store_targeting"] == "ALL"


def test_an_all_cities_campaign_stores_no_city_list():
    d = P.parse_catalog_detail(copy.deepcopy(ALL_CASE.GET_DETAIL), NAMES)
    assert d["city_targeting"] == "ALL" and d["cities"] is None


def test_keywords_one_row_per_match_type_negatives_without_a_bid():
    floors = {("pink toffee", "EXACT"): 10, ("pink toffee", "PHRASE"): 10}
    rows = P.parse_catalog_keywords(copy.deepcopy(MANUAL_CASE.GET_DETAIL), 2427461, floors,
                                    TENANT, JOB)
    by = {(r["keyword"], r["match_type"]): r for r in rows}
    assert set(by) == {("pink toffee", "EXACT"), ("pink toffee", "PHRASE"),
                       ("pink toffee", "BROAD"), ("test", "EXACT")}
    assert by[("pink toffee", "PHRASE")]["bid_value"] == 10
    assert by[("pink toffee", "PHRASE")]["min_bid"] == 10
    assert by[("pink toffee", "BROAD")]["min_bid"] is None, "absent floor = unknown, not 0"
    neg = by[("test", "EXACT")]
    assert neg["is_negative"] is True and neg["bid_value"] is None and neg["min_bid"] is None
    assert by[("pink toffee", "EXACT")]["upsert_key"] == \
        f"{TENANT}:zepto:ad_kw_bid:2427461:pink toffee:EXACT"


def test_display_and_failed_campaigns_become_list_only_rows():
    catalog = {"campaigns": [LIST_ROW, DISPLAY_ROW],
               "details": {2427461: copy.deepcopy(MANUAL_CASE.GET_DETAIL)},
               "floors": {2427461: {}}, "city_names": NAMES}
    full, list_only, keywords = P.parse_campaign_catalog(catalog, TENANT, JOB)
    assert [r["campaign_id"] for r in full] == [2427461]
    assert [r["campaign_id"] for r in list_only] == [1111111]
    assert list(keywords) == [2427461] and len(keywords[2427461]) == 4
    assert full[0]["cities"] and "cities" not in list_only[0]


# ── storage: a list-only row never blanks the detail columns ───────────────

class _Session:
    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))

    async def commit(self):
        pass


def test_a_list_only_upsert_never_touches_detail_columns():
    """The Blinkit V7 trap: a Refresh that carries no targeting must not write NULL over
    the targeting the scrape stored."""
    s = _Session()
    row = P.parse_catalog_list_row(LIST_ROW, TENANT, JOB)
    asyncio.run(ST._upsert_columns(s, ST.ZeptoAdCampaign, [row]))
    set_clause = s.sql[0].split("DO UPDATE SET", 1)[1]
    for col in ("cities", "city_targeting", "product_variant_ids", "detail_scraped_at"):
        assert f"{col} =" not in set_clause, f"list-only upsert would overwrite {col}"
    assert "status =" in set_clause and "daily_budget =" in set_clause


def test_a_campaigns_keywords_are_replaced_whole():
    """A keyword removed in the dashboard must disappear — a stale one would be offered to
    an automation as a bid target the campaign no longer has."""
    s = _Session()
    kws = P.parse_catalog_keywords(copy.deepcopy(MANUAL_CASE.GET_DETAIL), 2427461, {},
                                   TENANT, JOB)
    asyncio.run(ST.save_campaign_catalog(s, [], [], {2427461: kws}))
    delete = next(q for q in s.sql if q.startswith("DELETE"))
    assert "zepto_ad_campaign_keywords" in delete and "NOT IN" in delete


# ── fetching ────────────────────────────────────────────────────────────────

def test_the_campaign_list_follows_every_page():
    """A recorded dashboard call returned 8 of 21 with `has_next: true`; the old single
    `limit=200` call saw page 1 only. Zepto ignores `limit` and honours `page`."""
    allc = [{"campaign_id": i} for i in range(21)]

    class _C:
        brand_id = "b"

        async def get_json(self, path, params=None, **_):
            p = int(params["page"])
            return {"data": {"campaigns": allc[(p - 1) * 8:p * 8], "total_count": 21,
                             "has_next": True}}

    got = asyncio.run(zc.get_campaigns(_C()))
    assert sorted(c["campaign_id"] for c in got) == list(range(21))


def test_the_campaign_list_stops_when_paging_is_ignored():
    """`has_next` has been seen staying true forever; a page with no new ids ends it."""
    calls = {"n": 0}

    class _C:
        brand_id = "b"

        async def get_json(self, path, params=None, **_):
            calls["n"] += 1
            return {"data": {"campaigns": [{"campaign_id": 1}], "total_count": 50,
                             "has_next": True}}

    asyncio.run(zc.get_campaigns(_C()))
    assert calls["n"] == 2


def test_keyword_floors_parse():
    class _R:
        status_code = 200

        def json(self):
            return {"keywords": [{"keyword": "bread", "match_type": "EXACT", "min_bid": 9},
                                 {"keyword": "bread", "match_type": "BROAD", "min_bid": "10"}]}

    class _C:
        async def request(self, method, path, json=None, **_):
            assert json == {"keywords": [{"keyword": "bread", "match_type": "EXACT"},
                                         {"keyword": "bread", "match_type": "BROAD"}]}
            return _R()

    got = asyncio.run(zc.get_keyword_floors(_C(), [("bread", "EXACT"), ("bread", "BROAD")]))
    assert got == {("bread", "EXACT"): 9, ("bread", "BROAD"): 10}


def test_keyword_floors_batch_at_zeptos_cap():
    # Zepto answers 400 "max 500 keywords allowed per request" above the cap — that
    # failed Sereko's catalogue (campaign 2428159) every day from 2026-09-29.
    sizes = []

    class _C:
        async def request(self, method, path, json=None, **_):
            kws = json["keywords"]
            sizes.append(len(kws))

            class _R:
                status_code = 400 if len(kws) > 500 else 200
                text = '{"message":"max 500 keywords allowed per request"}'

                def json(self):
                    return {"keywords": [{**k, "min_bid": 5} for k in kws]}
            return _R()

    pairs = [(f"kw{i}", "EXACT") for i in range(1203)]
    got = asyncio.run(zc.get_keyword_floors(_C(), pairs))
    assert sizes == [500, 500, 203]
    assert len(got) == 1203 and got[("kw1202", "EXACT")] == 5
    assert asyncio.run(zc.get_keyword_floors(_C(), [])) == {} and sizes == [500, 500, 203]


def _fake_zc(details: dict, *, fail_once=(), fail_always=()):
    seen = {"detail": [], "floors": 0, "options": 0}
    failed_once: set = set()

    async def get_campaigns(client, days=90):
        return [LIST_ROW, DISPLAY_ROW, {**LIST_ROW, "campaign_id": 2222222}]

    async def get_campaign_detail(client, cid):
        seen["detail"].append(cid)
        if cid in fail_always or (cid in fail_once and cid not in failed_once):
            failed_once.add(cid)
            raise RuntimeError("Zepto GET -> 500")
        return copy.deepcopy(details.get(cid, MANUAL_CASE.GET_DETAIL))

    async def get_keyword_floors(client, pairs):
        seen["floors"] += 1
        return {p: 10 for p in pairs}

    async def get_targeting_options(client, **_):
        seen["options"] += 1
        return {"cities": [{"id": k, "name": v} for k, v in NAMES.items()]}

    orig = (zc.get_campaigns, zc.get_campaign_detail, zc.get_keyword_floors,
            zc.get_targeting_options, S._CATALOG_GAP_S, S.asyncio.sleep)

    async def no_sleep(_s):
        return None

    (zc.get_campaigns, zc.get_campaign_detail, zc.get_keyword_floors,
     zc.get_targeting_options) = (get_campaigns, get_campaign_detail, get_keyword_floors,
                                  get_targeting_options)
    S.asyncio.sleep = no_sleep
    return seen, orig


def _unfake(orig):
    (zc.get_campaigns, zc.get_campaign_detail, zc.get_keyword_floors,
     zc.get_targeting_options, S._CATALOG_GAP_S, S.asyncio.sleep) = orig


def test_only_pla_campaigns_get_a_detail_read():
    seen, orig = _fake_zc({})
    try:
        cat = asyncio.run(S.fetch_campaign_catalog(object()))
    finally:
        _unfake(orig)
    assert sorted(seen["detail"]) == [2222222, 2427461], "Display must not hit /pla/{id}"
    assert seen["options"] == 1, "targeting-options once per campaign type"
    assert cat["failed"] == [] and cat["city_names"] == NAMES
    assert cat["floors"][2427461][("pink toffee", "EXACT")] == 10


def test_a_failed_detail_is_retried_then_reported():
    seen, orig = _fake_zc({}, fail_once={2427461}, fail_always={2222222})
    try:
        cat = asyncio.run(S.fetch_campaign_catalog(object()))
    finally:
        _unfake(orig)
    assert 2427461 in cat["details"], "a transient failure must be recovered"
    assert cat["failed"] == [2222222]
    assert 2222222 not in cat["details"]


# ── the campaign manager side ───────────────────────────────────────────────

def test_repo_picks_each_marketplaces_own_tables():
    assert repo._catalog("zepto").campaigns.__tablename__ == "zepto_ad_campaigns"
    assert repo._catalog("zepto").keywords.__tablename__ == "zepto_ad_campaign_keywords"
    assert repo._catalog("blinkit").campaigns.__tablename__ == "blinkit_ad_campaigns"
    assert repo._catalog_model("zepto.campaigns").__tablename__ == "zepto_ad_campaigns"
    assert repo._catalog_model("zepto.keywords").__tablename__ == "zepto_ad_campaign_keywords"


def test_zepto_write_back_lands_on_the_right_rows():
    assert zad.catalog_patch("budget", campaign_id=7, value=551.4) == [
        {"table": "zepto.campaigns", "key": {"campaign_id": 7}, "set": {"daily_budget": 551}}]
    assert zad.catalog_patch("status", campaign_id=7, value="paused", budget=900) == [
        {"table": "zepto.campaigns", "key": {"campaign_id": 7}, "set": {"status": "PAUSED"}}]
    assert zad.catalog_patch("bid", campaign_id=7, value=14, keyword="pink toffee",
                             match_type="phrase") == [
        {"table": "zepto.keywords",
         "key": {"campaign_id": 7, "keyword": "pink toffee", "match_type": "PHRASE"},
         "set": {"bid_value": 14}}]
    assert zad.catalog_patch("status", campaign_id=7, value="held") == []
    assert zad.catalog_patch("nonsense", campaign_id=7, value=1) == []


def test_the_refresh_writes_list_fields_only_through_the_scrapers_writer():
    """`cm.sync_campaigns -m zepto` (ZC-A4/B5): Zepto rows used to go through Blinkit's
    parser, which skipped every one."""
    captured = {}

    async def fake_save(session, full, list_only, keywords):
        captured.update(full=full, list_only=list_only, keywords=keywords)
        return {"campaigns": len(list_only)}

    class _DB:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    orig = (ST.save_campaign_catalog, repo.AsyncSessionLocal)
    ST.save_campaign_catalog, repo.AsyncSessionLocal = fake_save, _DB
    try:
        n = asyncio.run(repo.upsert_campaign_catalog(
            uuid.UUID(TENANT), [LIST_ROW, DISPLAY_ROW], "zepto"))
    finally:
        ST.save_campaign_catalog, repo.AsyncSessionLocal = orig
    assert n == 2 and captured["full"] == [] and captured["keywords"] == {}
    assert all("scrape_job_id" not in r for r in captured["list_only"]), \
        "a Refresh must not blank the scraper's lineage"


def test_read_bid_floors_is_wired():
    """ZC-C1: the engine's per-keyword floor lookup was a stub returning {}."""
    async def floors(client, pairs):
        return {p: 9 for p in pairs}

    orig = zc.get_keyword_floors
    zc.get_keyword_floors = floors
    try:
        got = asyncio.run(zad.read_bid_floors(None, 2427461,
                                              copy.deepcopy(MANUAL_CASE.GET_DETAIL)))
    finally:
        zc.get_keyword_floors = orig
    assert got == {("pink toffee", "EXACT"): 9, ("pink toffee", "PHRASE"): 9,
                   ("pink toffee", "BROAD"): 9}, "negatives are not bid targets"


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
    print(f"\n{len(tests) - failed}/{len(tests)} zepto catalogue tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
