"""Ads Insights reads — Phase 1 of plans/PLAN-ads-insights.md (2026-10-08).

K-B1 a one-marketplace day with zero spend kept RoAS = None and 500'd `/ads/performance`;
K-B2 a campaign's top keywords come from ITS marketplace (Zepto's were read from Blinkit's
table, always empty); K-B3 Blinkit keywords are an 8-day snapshot picked on or before the
picker's end; K-B4 one canonical state per campaign so one status filter covers every
marketplace; K-B10 Zepto's daily utilisation uses that day's budget.

No database: fake sessions record the SQL and answer canned rows.

    python -m pytest app/tests/test_ads_insights.py
"""
import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from app.dependencies import Pagination
from app.schemas.ads import AdPerformancePoint, CampaignKeywords, KeywordRow
from app.schemas.common import Page
from app.services import ads_service, zepto_ads

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
D1, D7 = date(2026, 10, 1), date(2026, 10, 7)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(),
                            compile_kwargs={"literal_binds": True}))


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def mappings(self):
        return self

    def scalar(self):
        return self._rows[0][0] if self._rows else None

    def one(self):
        return self._rows[0]


class _Session:
    """Answers each `execute` with the next canned row list (empty once they run out) and
    every `scalar` with 0, recording the SQL of both."""

    def __init__(self, *results):
        self.results = list(results)
        self.sql: list[str] = []

    async def execute(self, stmt, *_a, **_k):
        self.sql.append(_sql(stmt))
        return _Result(self.results.pop(0) if self.results else ())

    async def scalar(self, stmt, *_a, **_k):
        self.sql.append(_sql(stmt))
        return 0


# ── K-B1 ──────────────────────────────────────────────────────────────────────

def test_zepto_only_zero_spend_day_has_numeric_roas(monkeypatch):
    """Brik Oven 19–28 Sep: every Zepto day zero spend → Zepto's series says roas None."""
    async def zepto_perf(*_a, **_k):
        return [{"date": D1, "budget_consumed": 0.0, "impressions": 0,
                 "ad_sales": 0.0, "roas": None}]
    monkeypatch.setattr(zepto_ads, "performance", zepto_perf)
    rows = asyncio.run(ads_service.get_performance(
        _Session(), tenant_id=TENANT, start=D1, end=D7, marketplaces=["zepto"]))
    assert rows[0]["roas"] == 0.0
    AdPerformancePoint.model_validate(rows[0])


# ── K-B4 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform,status,state", [
    ("blinkit", "ACTIVE", "running"),
    ("blinkit", "STOPPED", "paused"),
    ("blinkit", "ON_HOLD", "held"),
    ("blinkit", "COMPLETED", "ended"),
    ("zepto", "PAUSED", "paused"),
    ("zepto", "ENDED", "ended"),
    ("zepto", "DAILY_BUDGET_EXHAUSTED", "held"),
    # Instamart has no engine vocabulary; its words are pre-mapped to these.
    ("instamart", "ACTIVE", "running"),
    ("instamart", "PAUSED", "paused"),
    ("instamart", "STOPPED", "paused"),
    ("instamart", "ON_HOLD", "held"),
    ("instamart", "COMPLETED", "ended"),
    ("instamart", "UNDER_REVIEW", "UNDER_REVIEW"),
    ("instamart", None, None),
])
def test_one_state_vocabulary_for_every_marketplace(platform, status, state):
    assert ads_service._ui_state(platform, status) == state


# ── K-B2 ──────────────────────────────────────────────────────────────────────

def test_campaign_keywords_needs_a_known_marketplace():
    with pytest.raises(ValueError, match="unknown marketplace"):
        asyncio.run(ads_service.get_campaign_keywords(
            _Session(), tenant_id=TENANT, platform="", campaign_id="1", start=D1, end=D7))


def test_campaign_keywords_refuses_a_non_numeric_zepto_id():
    with pytest.raises(ValueError, match="numbers"):
        asyncio.run(ads_service.get_campaign_keywords(
            _Session(), tenant_id=TENANT, platform="zepto", campaign_id="abc",
            start=D1, end=D7))


def test_zepto_campaign_keywords_read_the_per_campaign_table_over_the_window():
    s = _Session([("bread", "EXACT", 120.0, 600.0, 900)])
    out = asyncio.run(ads_service.get_campaign_keywords(
        s, tenant_id=TENANT, platform="zepto", campaign_id="2410491", start=D1, end=D7))
    CampaignKeywords.model_validate(out)
    assert (out["period_start"], out["period_end"]) == (D1, D7)
    assert out["items"][0] == {"keyword": "bread", "match_type": "EXACT", "spend": 120.0,
                               "sales": 600.0, "impressions": 900, "roas": 5.0,
                               "position": None}
    sql = s.sql[-1]
    assert "FROM zepto_ad_campaign_detail" in sql and "campaign_id = 2410491" in sql
    assert "'2026-10-01'" in sql and "'2026-10-07'" in sql


def test_blinkit_campaign_keywords_label_the_snapshot_not_the_window(monkeypatch):
    seen = {}

    async def get_keywords(_s, **kw):
        seen.update(kw)
        row = KeywordRow(
            campaign_id=613816, platform="blinkit", campaign_type="PRODUCT_LISTING",
            target_type="keyword", target="lip balm", match_type="EXACT", impressions=10,
            budget_consumed=100.0, cpm=1.0, direct_atc=1, indirect_atc=0,
            direct_sales=300.0, indirect_sales=100.0, new_users_acquired=0,
            most_viewed_position=2, direct_roas=3.0, total_roas=4.0, snapshot_date=D7)
        return Page.build([row], 1, kw["pagination"])

    monkeypatch.setattr(ads_service, "get_keywords", get_keywords)
    out = asyncio.run(ads_service.get_campaign_keywords(
        _Session(), tenant_id=TENANT, platform="blinkit", campaign_id="613816",
        start=D1, end=D7))
    assert seen["as_of"] == D7 and seen["campaign_id"] == 613816
    assert (out["period_start"], out["period_end"]) == (date(2026, 9, 30), D7)
    assert out["items"][0]["sales"] == 400.0 and out["items"][0]["position"] == 2


# ── K-B3 ──────────────────────────────────────────────────────────────────────

def test_keywords_as_of_picks_the_snapshot_on_or_before_it():
    s = _Session()
    asyncio.run(ads_service.get_keywords(
        s, tenant_id=TENANT, pagination=Pagination(page=1, limit=20),
        as_of=date(2026, 9, 30)))
    assert all("snapshot_date <= '2026-09-30'" in q for q in s.sql), s.sql


def test_keywords_without_as_of_take_the_latest():
    s = _Session()
    asyncio.run(ads_service.get_keywords(
        s, tenant_id=TENANT, pagination=Pagination(page=1, limit=20)))
    assert not any("snapshot_date <=" in q for q in s.sql)


# ── K-B10 ─────────────────────────────────────────────────────────────────────

class _Cat:
    campaign_id = 7
    campaign_name = "Bread PLA"
    daily_budget = 9000


def test_zepto_daily_utilisation_uses_that_days_budget():
    day_rows = [(D1, 7, "x", "PLA", 500.0, 900.0, 3000.0),
                (D7, 7, "x", "PLA", 400.0, 800.0, None)]
    out = asyncio.run(zepto_ads.campaigns_daily(
        _Session(day_rows, [_Cat()]), tenant_id=TENANT, start=D1, end=D7))
    assert [r["daily_budget"] for r in out] == [3000, 9000]  # the day's, else the catalogue
    assert all(r["name"] == "Bread PLA" for r in out)


# ── Phases 2–4 ────────────────────────────────────────────────────────────────

def test_budget_split_merges_every_marketplace_and_tags_each_row(monkeypatch):
    """K-U1: one donut — Blinkit from its daily table, Zepto and Instamart from theirs."""
    from app.services import instamart_ads

    async def z(*_a, **_k):
        return [{"campaign_type": "PLA", "budget_consumed": 500.0, "ad_sales": 1500.0, "roas": 3.0},
                {"campaign_type": "Display", "budget_consumed": 0.0, "ad_sales": 0.0, "roas": 0.0}]

    async def i(*_a, **_k):
        return [{"campaign_type": "ITEM", "budget_consumed": 50.0, "ad_sales": 100.0, "roas": 2.0}]

    monkeypatch.setattr(zepto_ads, "budget_split", z)
    monkeypatch.setattr(instamart_ads, "budget_split", i)
    s = _Session([("blinkit", "PRODUCT_LISTING", 200.0, 400.0)])
    rows = asyncio.run(ads_service.get_budget_split(s, tenant_id=TENANT, start=D1, end=D7))
    assert [(r["platform"], r["campaign_type"]) for r in rows] == [
        ("zepto", "PLA"), ("blinkit", "PRODUCT_LISTING"), ("instamart", "ITEM")]  # 0-spend dropped
    assert "GROUP BY blinkit_ad_campaign_daily.platform" in s.sql[0]


def test_budget_split_scoped_to_one_marketplace_reads_only_it(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("Zepto read while out of scope")
    monkeypatch.setattr(zepto_ads, "budget_split", boom)
    asyncio.run(ads_service.get_budget_split(
        _Session(), tenant_id=TENANT, start=D1, end=D7, marketplaces=["blinkit"]))


def test_keyword_insights_label_blinkit_as_a_snapshot_and_zepto_as_the_window(monkeypatch):
    """K-U3: one table; Blinkit's period is its snapshot's 8 days, Zepto's the window."""
    async def get_keywords(_s, **kw):
        assert kw["as_of"] == D7 and kw["target_type"] == "keyword" and kw["recent_only"]
        row = KeywordRow(
            campaign_id=1, platform="blinkit", campaign_type="PRODUCT_LISTING",
            target_type="keyword", target="soda", match_type="EXACT", impressions=10,
            budget_consumed=100.0, cpm=1.5, direct_atc=2, indirect_atc=1,
            direct_sales=300.0, indirect_sales=100.0, new_users_acquired=0,
            most_viewed_position=3, direct_roas=3.0, total_roas=4.0,
            snapshot_date=date(2026, 10, 6))
        return Page.build([row], 1, kw["pagination"])

    async def zepto_rows(*_a, **_k):
        return [{"platform": "zepto", "campaign_id": 9, "keyword": "soda", "match_type": "BROAD",
                 "spend": 50.0, "sales": 200.0, "impressions": 40, "clicks": 4, "atc": 3,
                 "orders": 2, "direct_orders": 1, "halo_orders": 1}]

    monkeypatch.setattr(ads_service, "get_keywords", get_keywords)
    monkeypatch.setattr(zepto_ads, "keyword_rows", zepto_rows)
    out = asyncio.run(ads_service.get_keyword_insights(
        _Session(), tenant_id=TENANT, start=D1, end=D7, marketplaces=["blinkit", "zepto"]))
    from app.schemas.ads import KeywordInsights
    KeywordInsights.model_validate(out)
    assert out["periods"] == [
        {"platform": "blinkit", "snapshot": True, "start": date(2026, 9, 29),
         "end": date(2026, 10, 6)},
        {"platform": "zepto", "snapshot": False, "start": D1, "end": D7},
    ]
    b, z = out["items"]
    assert (b["sales"], b["atc"], b["position"], b.get("clicks")) == (400.0, 3, 3, None)
    assert (z["clicks"], z["direct_orders"], z.get("position")) == (4, 1, None)


def test_keyword_insights_with_no_blinkit_report_say_so(monkeypatch):
    async def none(_s, **kw):
        return Page.build([], 0, kw["pagination"])
    monkeypatch.setattr(ads_service, "get_keywords", none)
    out = asyncio.run(ads_service.get_keyword_insights(
        _Session(), tenant_id=TENANT, start=D1, end=D7, marketplaces=["blinkit"]))
    assert out["periods"] == [{"platform": "blinkit", "snapshot": True, "start": None, "end": None}]


def test_zepto_keyword_rows_read_the_per_campaign_table():
    s = _Session([(9, "soda", "BROAD", 50.0, 200.0, 40, 4, 3, 2, 1, 1)])
    rows = asyncio.run(zepto_ads.keyword_rows(s, tenant_id=TENANT, start=D1, end=D7))
    assert rows[0]["campaign_id"] == 9 and rows[0]["halo_orders"] == 1
    assert "FROM zepto_ad_campaign_detail" in s.sql[0]
    assert "zepto_ad_keyword_daily" not in s.sql[0]


def test_breakdowns_are_zepto_only_and_never_mix_dimensions(monkeypatch):
    """K-U4: product / category / city each a separate slicing; Blinkit reports none."""
    seen = {}

    async def breakdown(*_a, **kw):
        seen.update(kw)
        return [{"name": "Bengaluru", "ad_types": [], "spend": 10.0, "sales": 30.0,
                 "impressions": 5, "clicks": 1, "units_sold": 1, "atc": 1,
                 "ctr": 20.0, "cpc": 10.0, "cpm": 2000.0, "roas": 3.0}]

    monkeypatch.setattr(zepto_ads, "breakdown", breakdown)
    rows = asyncio.run(ads_service.get_breakdowns(
        _Session(), tenant_id=TENANT, start=D1, end=D7, dimension="city",
        ad_type="sponsored_products"))
    assert seen["dimension"] == "city" and seen["campaign_category"] == "sponsored_products"
    assert rows[0]["platform"] == "zepto" and rows[0]["key"] == "Bengaluru"
    assert asyncio.run(ads_service.get_breakdowns(
        _Session(), tenant_id=TENANT, start=D1, end=D7, dimension="city",
        marketplaces=["blinkit"])) == []
    with pytest.raises(ValueError):
        asyncio.run(ads_service.get_breakdowns(
            _Session(), tenant_id=TENANT, start=D1, end=D7, dimension="page"))


# ── real-page build (2026-10-08) ─────────────────────────────────────────────

def test_summary_splits_each_marketplace(monkeypatch):
    """The KPI split: one entry per marketplace, Instamart's units withheld."""
    calls = []

    async def agg(_s, *, tenant_id, start, end, marketplaces):
        calls.append(tuple(marketplaces or ()))
        n = {("blinkit",): 1, ("zepto",): 2, ("instamart",): 3}.get(tuple(marketplaces or ()), 6)
        return (100.0 * n, 10 * n, 300.0 * n, n, 5 * n, n)

    monkeypatch.setattr(ads_service, "_summary_agg", agg)
    out = asyncio.run(ads_service.get_summary(
        _Session(), tenant_id=TENANT, start=D1, end=D7, prev_start=D1, prev_end=D7))
    from app.schemas.ads import AdsSummary
    AdsSummary.model_validate(out)
    split = {m["platform"]: m for m in out["by_marketplace"]}
    assert set(split) == {"blinkit", "zepto", "instamart"}
    assert split["zepto"]["ad_spend"] == 200.0 and split["zepto"]["units_sold"] == 10
    assert split["instamart"]["units_sold"] is None


def test_summary_split_follows_the_marketplace_filter(monkeypatch):
    async def agg(_s, **kw):
        return (1.0, 1, 1.0, 1, 1, 1)
    monkeypatch.setattr(ads_service, "_summary_agg", agg)
    out = asyncio.run(ads_service.get_summary(
        _Session(), tenant_id=TENANT, start=D1, end=D7, prev_start=D1, prev_end=D7,
        marketplaces=["zepto"]))
    assert [m["platform"] for m in out["by_marketplace"]] == ["zepto"]


def test_performance_days_carry_each_marketplace(monkeypatch):
    from app.services import instamart_ads

    async def z(*_a, **_k):
        return [{"date": D1, "budget_consumed": 50.0, "impressions": 5, "ad_sales": 150.0, "roas": 3.0}]

    async def i(*_a, **_k):
        return [{"date": D7, "budget_consumed": 20.0, "impressions": 2, "ad_sales": 0.0, "roas": None}]

    monkeypatch.setattr(zepto_ads, "performance", z)
    monkeypatch.setattr(instamart_ads, "performance", i)
    s = _Session([(D1, 100.0, 10, 200.0)])
    rows = asyncio.run(ads_service.get_performance(s, tenant_id=TENANT, start=D1, end=D7))
    [AdPerformancePoint.model_validate(r) for r in rows]
    d1, d7 = rows
    assert d1["budget_consumed"] == 150.0 and d1["roas"] == round(350 / 150, 4)
    assert set(d1["by_marketplace"]) == {"blinkit", "zepto"}
    assert d1["by_marketplace"]["zepto"]["ad_sales"] == 150.0
    assert d7["roas"] == 0.0 and set(d7["by_marketplace"]) == {"instamart"}


def test_keyword_insights_include_instamart(monkeypatch):
    from app.services import instamart_ads

    async def none(_s, **kw):
        return Page.build([], 0, kw["pagination"])

    async def zr(*_a, **_k):
        return []

    async def ir(*_a, **_k):
        return [{"platform": "instamart", "campaign_id": "abc-1", "keyword": "bread", "spend": 10.0,
                 "sales": 30.0, "impressions": 100, "clicks": 4, "atc": 2}]

    monkeypatch.setattr(ads_service, "get_keywords", none)
    monkeypatch.setattr(zepto_ads, "keyword_rows", zr)
    monkeypatch.setattr(instamart_ads, "keyword_rows", ir)
    out = asyncio.run(ads_service.get_keyword_insights(_Session(), tenant_id=TENANT, start=D1, end=D7))
    from app.schemas.ads import KeywordInsights
    KeywordInsights.model_validate(out)
    assert [p["platform"] for p in out["periods"]] == ["blinkit", "zepto", "instamart"]
    assert out["items"][0]["campaign_id"] == "abc-1" and out["items"][0].get("orders") is None


def test_instamart_keyword_rows_group_by_campaign_and_keyword():
    from app.services import instamart_ads
    s = _Session([("abc-1", "bread", 10.0, 30.0, 100, 4, 2)])
    rows = asyncio.run(instamart_ads.keyword_rows(s, tenant_id=TENANT, start=D1, end=D7))
    assert rows[0] == {"platform": "instamart", "campaign_id": "abc-1", "keyword": "bread",
                       "spend": 10.0, "sales": 30.0, "impressions": 100, "clicks": 4, "atc": 2}
    assert "GROUP BY instamart_ad_keyword_daily.campaign_id, instamart_ad_keyword_daily.keyword" in s.sql[0]


def test_product_breakdown_includes_instamart_without_units(monkeypatch):
    from app.services import instamart_ads

    async def zp(*_a, **_k):
        return []

    async def ip(*_a, **_k):
        return [{"product_variant_id": "p1", "product_name": "Sourdough", "image_link": None,
                 "spend": 40.0, "sales": 90.0, "impressions": 400, "clicks": 9, "atc": 3,
                 "units_sold": 0, "ctr": 2.25, "cpc": 4.44, "cpm": 100.0, "roas": 2.25,
                 "campaigns": [{"campaign_id": "abc-1", "campaign_name": "Item", "spend": 40.0,
                                "sales": 90.0, "impressions": 400}]}]

    monkeypatch.setattr(zepto_ads, "products", zp)
    monkeypatch.setattr(instamart_ads, "products", ip)
    rows = asyncio.run(ads_service.get_breakdowns(
        _Session(), tenant_id=TENANT, start=D1, end=D7, dimension="product"))
    from app.schemas.ads import AdBreakdownRow
    r = AdBreakdownRow.model_validate(rows[0])
    assert (r.platform, r.key, r.name, r.units_sold) == ("instamart", "p1", "Sourdough", None)
    assert r.campaigns[0]["campaign_id"] == "abc-1"
    # A Zepto ad type has no Instamart counterpart: filtering by one leaves Instamart out.
    assert asyncio.run(ads_service.get_breakdowns(
        _Session(), tenant_id=TENANT, start=D1, end=D7, dimension="product",
        ad_type="sponsored_products")) == []


def test_summary_stops_at_the_newest_day_with_data(monkeypatch):
    """N1: a window ending today (no ad data yet) is compared over the days that HAVE data,
    against the same number of days before it."""
    seen = []

    async def latest(_s, **kw):
        return date(2026, 10, 7)

    async def agg(_s, *, tenant_id, start, end, marketplaces):
        seen.append((start, end, tuple(marketplaces)))
        return (10.0, 1, 30.0, 1, 1, 1)

    monkeypatch.setattr(ads_service, "latest_ad_day", latest)
    monkeypatch.setattr(ads_service, "_summary_agg", agg)
    out = asyncio.run(ads_service.get_summary(
        _Session(), tenant_id=TENANT, start=date(2026, 10, 2), end=date(2026, 10, 8),
        prev_start=date(2026, 9, 25), prev_end=date(2026, 10, 1)))
    assert out["period"] == {"start": date(2026, 10, 2), "end": date(2026, 10, 7),
                             "prev_start": date(2026, 9, 26), "prev_end": date(2026, 10, 1),
                             "picked_end": date(2026, 10, 8)}
    # current window per marketplace up to the 7th; the previous window once, 6 days long
    assert all(e == date(2026, 10, 7) for s_, e, m in seen if len(m) == 1)
    assert (date(2026, 9, 26), date(2026, 10, 1), ("blinkit", "zepto", "instamart")) in seen
    assert out["ad_spend"]["value"] == 30.0  # three marketplaces' 10 each, summed once


def test_summary_keeps_a_window_that_has_data_to_its_end(monkeypatch):
    async def latest(_s, **kw):
        return date(2026, 9, 30)

    async def agg(_s, **kw):
        return (1.0, 1, 1.0, 1, 1, 1)

    monkeypatch.setattr(ads_service, "latest_ad_day", latest)
    monkeypatch.setattr(ads_service, "_summary_agg", agg)
    out = asyncio.run(ads_service.get_summary(
        _Session(), tenant_id=TENANT, start=date(2026, 9, 1), end=date(2026, 9, 30),
        prev_start=date(2026, 8, 2), prev_end=date(2026, 8, 31)))
    assert (out["period"]["end"], out["period"]["prev_start"]) == (date(2026, 9, 30), date(2026, 8, 2))


def test_zepto_summary_is_one_query():
    s = _Session([(100.0, 10, 300.0, 2, 3, 4)])
    out = asyncio.run(zepto_ads.summary_agg(s, tenant_id=TENANT, start=D1, end=D7))
    assert out == (100.0, 10, 300.0, 2, 3, 4) and len(s.sql) == 1
    assert "count(DISTINCT zepto_ad_campaign_daily.campaign_id) FILTER" in s.sql[0]


def test_campaigns_skip_automation_lookups_when_asked(monkeypatch):
    called = []

    async def refusals(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(ads_service.cm_repo, "automation_refusals", refusals)

    async def none(*a, **k):
        return []

    from app.services import instamart_ads
    monkeypatch.setattr(zepto_ads, "campaigns", none)
    monkeypatch.setattr(instamart_ads, "campaigns", none)

    class _C:
        campaign_id, platform, name, type, status, daily_budget = 5, "blinkit", "x", "PRODUCT_LISTING", "ACTIVE", 100

    for automation, expect in ((False, 0), (True, 1)):
        called.clear()
        asyncio.run(ads_service._campaigns(
            _Session([], [_C()]), tenant_id=TENANT, pagination=Pagination(page=1, limit=50),
            start=D1, end=D7, automation=automation))
        assert len(called) == expect

