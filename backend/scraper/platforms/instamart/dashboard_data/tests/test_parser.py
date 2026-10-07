"""Instamart parsers, request bodies and upsert keys — pure, no network or DB.

The upsert keys are pinned exactly: a changed key would duplicate every row
already stored instead of overwriting it.

Run:  python -m pytest scraper/platforms/instamart/dashboard_data/tests
"""
import asyncio
import datetime as dt
import uuid

from scraper.platforms.instamart.dashboard_data import common
from scraper.platforms.instamart.dashboard_data.seller import endpoints as ep
from scraper.platforms.instamart.dashboard_data.seller import parser as sp
from scraper.platforms.instamart.dashboard_data.seller import scraper as ss
from scraper.platforms.instamart.dashboard_data.seller import storage as sst
from scraper.platforms.instamart.dashboard_data.supply import parser as pp
from scraper.platforms.instamart.dashboard_data.supply import storage as pst

TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"
JOB = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _metrics(**kv) -> list[dict]:
    return [{"name": f"METRIC_TYPE_{k}", "value": v} for k, v in kv.items()]


# ── shared helpers ───────────────────────────────────────────────────────────

def test_epoch_matches_the_portals_own_ist_window():
    # A captured portal request: 16–23 Sept IST == 1789497000..1790188199.
    assert common.epoch_s(dt.date(2026, 9, 16)) == 1789497000
    assert common.epoch_s(dt.date(2026, 9, 23), end_of_day=True) == 1790188199


def test_asset_chunks_cover_the_range_without_gaps():
    chunks = ss.chunk_bounds(dt.date(2026, 9, 1), dt.date(2026, 9, 10))
    assert chunks == [(dt.date(2026, 9, 1), dt.date(2026, 9, 4)),
                      (dt.date(2026, 9, 5), dt.date(2026, 9, 8)),
                      (dt.date(2026, 9, 9), dt.date(2026, 9, 10))]
    assert all((b - a).days + 1 <= ss.ASSET_CHUNK_DAYS for a, b in chunks)


def test_campaigns_page_by_page_number_not_row_offset():
    assert ss._campaigns_body("acc", 0)["pagination_context"] == {"offset": "0", "size": 50}
    assert ss._campaigns_body("acc", 2)["pagination_context"]["offset"] == "2"


# ── ads parsers ──────────────────────────────────────────────────────────────

def test_campaign_takes_the_lifetime_rollup_and_daily_budget_only_when_daily():
    raw = [{
        "campaign": {"id": "c1", "name": "Bread", "status": "ACTIVE",
                     "startTime": "2026-09-01T00:00:00Z",
                     "budget": {"budgetType": "BUDGET_TYPE_DAILY",
                                "totalBudget": {"units": "500", "nanos": 500000000}}},
        "adType": {"type": "ITEM", "placements": ["SEARCH", "BROWSE"]},
        "advertiserMetrics": {"metricsOnDimensionsList": [
            {"dimensions": [{"name": "DIMENSION_TYPE_CAMPAIGN"}, {"name": "DIMENSION_TYPE_DAY"}],
             "metrics": _metrics(GMV=1.0)},
            {"dimensions": [{"name": "DIMENSION_TYPE_CAMPAIGN"}],
             "metrics": _metrics(GMV=900.0, BUDGET_BURNT=120.5, IMPRESSIONS=4000, CLICKS=80)},
        ]},
    }, {
        "campaign": {"id": "c2", "budget": {"budgetType": "INVALID", "totalBudget": {"units": "220000"}}},
    }, {"campaign": {}}]
    rows = sp.parse_campaigns(raw)
    assert [r["campaign_id"] for r in rows] == ["c1", "c2"]
    c1, c2 = rows
    assert (c1["gmv"], c1["spend"], c1["impressions"], c1["clicks"]) == (900.0, 120.5, 4000, 80)
    assert c1["daily_budget"] == 500.5 and c1["placements"] == "SEARCH,BROWSE"
    assert c1["start_time"] == dt.datetime(2026, 9, 1)
    assert c2["daily_budget"] is None          # a lifetime cap, not per day
    assert c2["spend"] == 0.0


def test_account_daily_keeps_only_day_rows():
    raw = [{"dimensions": [{"name": "DIMENSION_TYPE_DAY", "value": "2026-09-30"}],
            "metrics": _metrics(BUDGET_BURNT=50.0, GMV=400.0, IMPRESSIONS="1200", CLICKS=30)},
           {"dimensions": [{"name": "DIMENSION_TYPE_CAMPAIGN", "value": "x"}], "metrics": []}]
    rows = sp.parse_account_daily(raw)
    assert len(rows) == 1
    assert rows[0]["date"] == dt.date(2026, 9, 30)
    assert (rows[0]["spend"], rows[0]["impressions"]) == (50.0, 1200)


def test_asset_rows_carry_the_campaign():
    entry = lambda dim, val: {"dimensions": [
        {"name": dim, "value": val}, {"name": "DIMENSION_TYPE_CAMPAIGN", "value": "c9"},
        {"name": "DIMENSION_TYPE_DAY", "value": "2026-10-01"}], "metrics": _metrics(BUDGET_BURNT=7.0)}
    prod = sp.parse_products_daily([entry("DIMENSION_TYPE_AD_CANDIDATE", "AEYU74I37R"), {"dimensions": []}])
    kw = sp.parse_keywords_daily([entry("DIMENSION_TYPE_KEYWORD", "sourdough")])
    assert prod == [{"date": dt.date(2026, 10, 1), "candidate_id": "AEYU74I37R", "campaign_id": "c9",
                     "spend": 7.0, "gmv": 0.0, "impressions": 0, "clicks": 0, "add_to_cart_count": 0}]
    assert kw[0]["keyword"] == "sourdough" and "candidate_id" not in kw[0]


def test_catalogue_takes_the_first_image():
    rows = sp.parse_product_catalog([
        {"id": "A1", "parentProductName": "Bread", "variations": [{"images": []}, {"images": ["x.png", "y.png"]}]},
        {"id": "A2", "parentProductName": "Bun"},
        {"parentProductName": "no id"},
    ])
    assert rows == [{"candidate_id": "A1", "product_name": "Bread", "image_url": ep.IMAGE_CDN_PREFIX + "x.png"},
                    {"candidate_id": "A2", "product_name": "Bun", "image_url": None}]


# ── supply parsers ───────────────────────────────────────────────────────────

def test_po_dates_convert_via_ist():
    # 2026-09-28 20:00 UTC is 29 Sept in IST — the day Instamart's own UI shows.
    ms = int(dt.datetime(2026, 9, 28, 20, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    row = pp.parse_purchase_orders({"data": {"purchase_orders": [
        {"purchase_order_id": "P1", "expiry_date": ms, "completed_date": 0, "value": {"units": "100"}}]}})[0]
    assert row["expiry_date"] == dt.date(2026, 9, 29)
    assert row["completed_date"] is None and row["value"] == 100.0


def test_export_csv_skips_rows_without_po_or_sku():
    rows = pp.parse_po_export_csv("PoNumber,SkuCode,ReceivedQty,BalancedQty\nP1,S1,5.0,\n,S2,1,1\n")
    assert rows == [{"purchase_order_id": "P1", "external_item_code": "S1",
                     "received_qty": 5, "balanced_qty": None}]


# ── upsert keys (unchanged from before the refactor) ─────────────────────────

class _Capture:
    """Stands in for common.upsert: records (table, rows) instead of writing."""

    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []

    async def __call__(self, _session, model, rows):
        self.calls.append((model.__tablename__, rows))
        return len(rows)


def _keys(save, *args) -> dict[str, list[str]]:
    cap = _Capture()
    saved = {mod: mod.upsert for mod in (sst, pst)}
    for mod in saved:
        mod.upsert = cap
    try:
        asyncio.run(save(None, TENANT, *args))
    finally:
        for mod, fn in saved.items():
            mod.upsert = fn
    return {table: [r["upsert_key"] for r in rows] for table, rows in cap.calls}


def test_upsert_keys_are_unchanged():
    t = f"instamart|{TENANT}"
    d = dt.date(2026, 10, 1)
    assert _keys(sst.save_sales, [{"date": d, "store_id": "1403", "item_code": "I9"}],
                 [{"date": d, "city": "Bangalore"}], JOB) == {
        "instamart_seller_store_daily": [f"{t}|2026-10-01|1403|I9"],
        "instamart_brand_city_daily": [f"{t}|2026-10-01|Bangalore"]}
    assert list(_keys(sst.save_campaigns, [{"campaign_id": "c1"}], JOB).values()) == [[f"{t}|c1"]]
    assert list(_keys(sst.save_account_daily, [{"date": d}], JOB).values()) == [[f"{t}|2026-10-01"]]
    assert list(_keys(sst.save_products_daily, [{"date": d, "candidate_id": "A1", "campaign_id": "c9"},
                                                {"date": d, "candidate_id": "A2", "campaign_id": None}],
                      JOB).values()) == [[f"{t}|2026-10-01|A1|c9", f"{t}|2026-10-01|A2"]]
    assert list(_keys(sst.save_keywords_daily, [{"date": d, "keyword": "bread"}], JOB).values()) == [
        [f"{t}|2026-10-01|bread"]]
    assert _keys(pst.save_purchase_orders, [{"purchase_order_id": "P1"}],
                 [{"purchase_order_id": "P1", "external_item_code": "S1"}], JOB) == {
        "instamart_po": [f"{t}|P1"], "instamart_po_item": [f"{t}|P1|S1"]}


# ── PO export date ───────────────────────────────────────────────────────────

def test_export_date_is_the_portals_own_last_30_days():
    from scraper.platforms.instamart.dashboard_data.supply import scraper as ps
    # Captured from the portal's own button on 2026-09-25.
    assert ps.export_release_date_ms(dt.date(2026, 9, 25)) == 1787682600000
    assert ps.export_release_date_ms(dt.date(2026, 10, 6)) == common.epoch_s(dt.date(2026, 9, 6)) * 1000


def test_po_fingerprint_follows_the_stored_columns():
    from app.models import InstamartPO
    assert all(hasattr(InstamartPO, k) for k in pst.PO_FINGERPRINT)
    row = {"status": "S", "grn_quantity": 3, "purchase_order_id": "P1"}
    assert pst.po_fingerprint(row)[pst.PO_FINGERPRINT.index("grn_quantity")] == 3
