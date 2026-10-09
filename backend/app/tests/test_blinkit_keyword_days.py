"""Blinkit keyword performance per day (BLINKIT-NOTES B6) and budget history (B8), 2026-10-08.

The keyword report answers a one-day range (probed read-only on campaign 402379): the scrape
asks each campaign × day it spent on, the readers sum those days over any window, and fall
back to the old 8-day snapshot only while the per-day history does not reach the window's
start. Each scrape also writes every campaign's budget onto yesterday's daily row, kept on
re-scrape, so utilisation for a past day divides by that day's budget — the way Zepto keeps a
day's FIRST budget stamp (ZC-P24).

No database: fake sessions answer canned rows and record the SQL.

    python -m pytest app/tests/test_blinkit_keyword_days.py
"""
import asyncio
import uuid
from datetime import date

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert

from app.schemas.ads import CampaignKeywords, KeywordInsights
from app.services import ads_service, zepto_ads
from scraper.platforms.blinkit.dashboard_data.marketing.parser import (
    parse_campaign_daily,
    parse_campaign_detail_day,
    stamp_budgets,
)
from scraper.platforms.blinkit.dashboard_data.marketing.scraper import keyword_days

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
D1, D7 = date(2026, 10, 1), date(2026, 10, 7)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]

    def scalars(self):
        return self

    def scalar(self):
        return self._rows[0][0] if self._rows else None


class _Session:
    def __init__(self, *results):
        self.results = list(results)
        self.sql: list[str] = []

    async def execute(self, stmt, *_a, **_k):
        self.sql.append(_sql(stmt))
        return _Result(self.results.pop(0) if self.results else ())

    async def scalar(self, stmt, *_a, **_k):
        self.sql.append(_sql(stmt))
        return 0


# ── which days the scrape asks for ───────────────────────────────────────────

def test_keyword_days_are_the_newest_days_before_today():
    today = date(2026, 10, 8)
    assert keyword_days(date(2026, 10, 1), today, 3, today) == [
        date(2026, 10, 7), date(2026, 10, 6), date(2026, 10, 5)]


def test_keyword_days_none_means_every_day_of_a_backfill_window():
    today = date(2026, 10, 8)
    days = keyword_days(date(2026, 9, 8), date(2026, 10, 7), None, today)
    assert len(days) == 30 and days[0] == date(2026, 10, 7) and days[-1] == date(2026, 9, 8)


def test_keyword_days_never_ask_for_today():
    today = date(2026, 10, 8)
    assert today not in keyword_days(today, today, 3, today)


# ── parsers ──────────────────────────────────────────────────────────────────

REPORT = {"reporting": {"keyword": [
    {"keyword": "sourdough", "sub_campaign_id": 11, "match_type": "EXACT", "impressions": 100,
     "budget_consumed": 50, "cpm": 500, "direct_sales": 300, "indirect_sales": 20},
    {"keyword": "sourdough", "sub_campaign_id": 12, "match_type": "BROAD", "impressions": 40,
     "budget_consumed": 10, "cpm": 250, "direct_sales": 0, "indirect_sales": 0},
]}}


def test_day_rows_are_dated_and_keyed_by_the_day_they_cover():
    rows = parse_campaign_detail_day(REPORT, 402379, "PRODUCT_LISTING", "2026-10-07",
                                     str(TENANT), "job")
    assert [r["date"] for r in rows] == ["2026-10-07", "2026-10-07"]
    assert "snapshot_date" not in rows[0]
    assert all(":ad_detail_day:402379:" in r["upsert_key"] and r["upsert_key"].endswith(":2026-10-07")
               for r in rows)
    assert len({r["upsert_key"] for r in rows}) == 2  # one per sub-campaign


def test_budgets_go_on_yesterdays_row_only():
    daily = [parse_campaign_daily({"date_ist": f"2026-10-0{d} 00:00:00+05:30"}, cid, None,
                                  str(TENANT), "job")
             for cid in (402379, 402380, 402381) for d in (6, 7)]
    assert all(r["daily_budget"] is None for r in daily)  # every row carries the key
    detail = {402379: {"campaign_budget": 3001.6}, 402380: {}, 402381: None}
    assert stamp_budgets(daily, detail, "2026-10-07") == 1
    got = {(r["campaign_id"], r["date"]): r["daily_budget"] for r in daily}
    assert got[(402379, "2026-10-07")] == 3002 and got[(402379, "2026-10-06")] is None
    assert got[(402380, "2026-10-07")] is None and got[(402381, "2026-10-07")] is None


def test_rescrape_keeps_a_days_first_budget_and_updates_the_rest(monkeypatch):
    from app.models.blinkit_marketing import BlinkitAdCampaignDaily, BlinkitAdCampaignDetailDaily
    from scraper.platforms.blinkit.dashboard_data.marketing import storage

    class _Rec:
        sql: list[str] = []

        async def execute(self, stmt, *_a, **_k):
            self.sql.append(_sql(stmt))

    rec = _Rec()
    row = parse_campaign_daily({"date_ist": "2026-10-07"}, 402379, None, str(TENANT), str(uuid.uuid4()))
    asyncio.run(storage._upsert(rec, BlinkitAdCampaignDaily, [row]))
    assert ("daily_budget = coalesce(blinkit_ad_campaign_daily.daily_budget, "
            "excluded.daily_budget)") in rec.sql[0]
    assert "budget_consumed = excluded.budget_consumed" in rec.sql[0]
    rows = parse_campaign_detail_day(REPORT, 402379, None, "2026-10-07", str(TENANT), str(uuid.uuid4()))
    asyncio.run(storage._upsert(rec, BlinkitAdCampaignDetailDaily, rows))
    assert "coalesce" not in rec.sql[1]  # only the daily budget is keep-first


# ── readers ──────────────────────────────────────────────────────────────────

def test_keyword_insights_read_blinkit_days_once_history_covers_the_window(monkeypatch):
    async def none(*_a, **_k):
        return []

    monkeypatch.setattr(zepto_ads, "keyword_rows", none)
    s = _Session(
        [(date(2026, 9, 1), date(2026, 6, 1))],               # history first day, first ad day
        [(402379, "keyword", "sourdough", "EXACT", 140, 60.0, 60000.0, 4, 300.0, 20.0, 2)],
    )
    out = asyncio.run(ads_service.get_keyword_insights(
        s, tenant_id=TENANT, start=D1, end=D7, marketplaces=["blinkit", "zepto"]))
    KeywordInsights.model_validate(out)
    assert out["periods"][0] == {"platform": "blinkit", "snapshot": False, "start": D1, "end": D7}
    r = out["items"][0]
    assert (r["keyword"], r["spend"], r["sales"], r["cpm"], r["position"]) == (
        "sourdough", 60.0, 320.0, round(60000 / 140, 2), 2)
    assert "FROM blinkit_ad_campaign_detail_daily" in s.sql[1]
    assert "'2026-10-01'" in s.sql[1] and "'2026-10-07'" in s.sql[1]


def test_keyword_insights_fall_back_to_the_snapshot_before_history_starts(monkeypatch):
    called = {}

    async def snapshot(_s, **kw):
        called["as_of"] = kw["as_of"]
        from app.schemas.common import Page
        return Page.build([], 0, kw["pagination"])

    async def none(*_a, **_k):
        return []

    monkeypatch.setattr(ads_service, "get_keywords", snapshot)
    monkeypatch.setattr(zepto_ads, "keyword_rows", none)
    # per-day history starts 5 Oct, the window starts 1 Oct, ads exist since June
    s = _Session([(date(2026, 10, 5), date(2026, 6, 1))])
    out = asyncio.run(ads_service.get_keyword_insights(
        s, tenant_id=TENANT, start=D1, end=D7, marketplaces=["blinkit"]))
    assert called["as_of"] == D7 and out["periods"][0]["snapshot"] is True


def test_daily_history_covers_a_window_older_than_the_first_ad_day():
    # Ads began 3 Oct and so did the per-day history: a window from 1 Oct is fully covered.
    s = _Session([(date(2026, 10, 3), date(2026, 10, 3))])
    assert asyncio.run(ads_service._blinkit_daily_covers(s, TENANT, D1)) is True
    assert asyncio.run(ads_service._blinkit_daily_covers(_Session([(None, None)]), TENANT, D1)) is False


def test_campaign_keywords_from_blinkit_days(monkeypatch):
    s = _Session(
        [(date(2026, 9, 1), date(2026, 6, 1))],
        [(402379, "keyword", "sourdough", "EXACT", 140, 60.0, 60000.0, 4, 300.0, 20.0, 2),
         (402379, "keyword", "bread", "BROAD", 40, 10.0, 10000.0, 0, 0.0, 0.0, None)],
    )
    out = asyncio.run(ads_service.get_campaign_keywords(
        s, tenant_id=TENANT, platform="blinkit", campaign_id="402379", start=D1, end=D7))
    CampaignKeywords.model_validate(out)
    assert out["snapshot"] is False and (out["period_start"], out["period_end"]) == (D1, D7)
    assert [i["keyword"] for i in out["items"]] == ["sourdough", "bread"]
    assert out["items"][0]["roas"] == round(320 / 60, 4)
    assert "campaign_id = 402379" in s.sql[1]
    assert "target_type = 'keyword'" not in s.sql[1]  # placements included for a campaign


class _Camp:
    def __init__(self, cid, budget):
        self.campaign_id, self.platform, self.name, self.type, self.daily_budget = (
            cid, "blinkit", f"c{cid}", "PRODUCT_LISTING", budget)


def test_utilisation_uses_each_days_recorded_budget(monkeypatch):
    async def none(*_a, **_k):
        return []

    from app.services import instamart_ads
    monkeypatch.setattr(zepto_ads, "campaigns_daily", none)
    monkeypatch.setattr(instamart_ads, "campaigns_daily", none)
    s = _Session(
        # only the 5th has a recorded budget; the 6th falls back to the current one
        [(date(2026, 10, 5), 1, 900.0, 2000.0, 1000), (date(2026, 10, 6), 1, 950.0, 2100.0, None)],
        [_Camp(1, 3000)],
    )
    out = asyncio.run(ads_service.get_campaigns_daily(s, tenant_id=TENANT, start=D1, end=D7))
    by_day = {r["date"]: r["daily_budget"] for r in out}
    assert by_day == {date(2026, 10, 5): 1000, date(2026, 10, 6): 3000}
    assert "max(blinkit_ad_campaign_daily.daily_budget)" in s.sql[0]
    assert len(s.sql) == 2  # no separate budget query


# ── Zepto keeps a day's first budget stamp ───────────────────────────────────

def test_zepto_rescrape_keeps_the_first_budget_and_updates_the_rest():
    from app.models.zepto_seller import ZeptoAdCampaignDaily
    from scraper.platforms.zepto.dashboard_data.seller import storage as zs

    budget = _sql(insert(ZeptoAdCampaignDaily).values(upsert_key="k").on_conflict_do_update(
        index_elements=["upsert_key"], set_={"daily_budget": zs._on_conflict(ZeptoAdCampaignDaily, "daily_budget")}))
    spend = _sql(insert(ZeptoAdCampaignDaily).values(upsert_key="k").on_conflict_do_update(
        index_elements=["upsert_key"], set_={"spend": zs._on_conflict(ZeptoAdCampaignDaily, "spend")}))
    assert "coalesce(zepto_ad_campaign_daily.daily_budget, excluded.daily_budget)" in budget
    assert "spend = excluded.spend" in spend
