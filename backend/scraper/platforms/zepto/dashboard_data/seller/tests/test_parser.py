"""Zepto seller parser — raw responses -> DB rows (Phase 1 / P6, 2026-10-05).

Pins what parser.py does today, so the Phase 1 restructure can move code around and
prove it changed nothing. The inputs are hand-built in the exact shapes the parsers
read (field names, string numbers, "-" for none, boxed values) rather than captured
responses: the only capture on disk holds a client's real campaigns, and these tests
live in the repo. The campaign CATALOGUE parsers are covered in
campaign_manager/tests/test_zepto_catalogue.py.

Run:  python -m scraper.platforms.zepto.dashboard_data.seller.tests.test_parser
"""
import asyncio
import uuid
from datetime import date

from scraper.platforms.zepto.dashboard_data.seller import parser as p
from scraper.platforms.zepto.dashboard_data.seller import storage

T = "fa53082e-7e83-424d-aab9-086fe1b4c680"
JOB = "11111111-2222-3333-4444-555555555555"


def _raises(fn, exc=ValueError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


# ── sales ────────────────────────────────────────────────────────────────────

def _overview(labels, gmv, units):
    # Zepto keys each point's value by the URL-encoded brand name, next to "key".
    return {"metrics": {
        "gmv": {"data": [{"key": k, "Brik%20Oven": v} for k, v in zip(labels, gmv)]},
        "units": {"data": [{"key": k, "Brik%20Oven": v} for k, v in zip(labels, units)]},
    }}


IDS = {"brand_id": "brand-1", "brand_name": "Brik Oven"}


def test_sales_daily_maps_each_point_to_its_day():
    rows = p.parse_sales_daily(_overview(["29 Sep", "30 Sep"], [100, None], [3, 0]),
                               IDS, T, JOB, "2026-09-29", "2026-09-30")
    assert [(r["date"], r["gmv"], r["units"]) for r in rows] == [
        (date(2026, 9, 29), 100.0, 3), (date(2026, 9, 30), 0.0, 0)]
    assert rows[0]["brand_id"] == "brand-1" and rows[0]["scrape_job_id"] == uuid.UUID(JOB)


def test_sales_daily_refuses_a_series_that_does_not_match_the_window():
    short = _overview(["29 Sep"], [100], [3])
    shifted = _overview(["28 Sep", "29 Sep"], [1, 2], [1, 1])
    assert _raises(lambda: p.parse_sales_daily(short, IDS, T, JOB, "2026-09-29", "2026-09-30"))
    assert _raises(lambda: p.parse_sales_daily(shifted, IDS, T, JOB, "2026-09-29", "2026-09-30"))


def _sku(pv, gmv, **kw):
    return {"productVariantId": pv, "productName": f"P {pv}", "skuName": "s", "packSize": 400,
            "unitOfMeasure": "GRAM", "categoryName": "Bakery", "subcategoryName": "Bread",
            "gmv": gmv, "qtySold": 2, "salesContribution": 50, "availableStores": 80,
            "weekOnWeekGrowth": 5, "monthOnMonthGrowth": -2, "stockOnHand": 9, **kw}


def test_product_perf_rows_key_on_product_and_window():
    rows = p.parse_product_perf([_sku("pv1", 500)], T, JOB, "2026-10-01", "2026-10-01")
    r = rows[0]
    assert r["period_start"] == r["period_end"] == date(2026, 10, 1)
    assert (r["gmv"], r["qty_sold"], r["pack_size"], r["stock_on_hand"]) == (500.0, 2, "400", 9)
    other_day = p.parse_product_perf([_sku("pv1", 500)], T, JOB, "2026-10-02", "2026-10-02")
    assert r["upsert_key"] != other_day[0]["upsert_key"]


def test_product_city_rows_carry_city_and_key_on_it():
    rows = p.parse_product_city({"c1": [_sku("pv1", 300)], "c2": [_sku("pv1", 200)]},
                                {"c1": "BLR - Bengaluru"}, T, JOB, "2026-10-01")
    assert [(r["city_id"], r["city_name"], r["gmv"]) for r in rows] == [
        ("c1", "BLR - Bengaluru", 300.0), ("c2", None, 200.0)]
    assert rows[0]["upsert_key"] != rows[1]["upsert_key"]


# ── ads: daily campaign list + the analytics tables ──────────────────────────

def _campaign(cid, **kw):
    return {"campaign_id": cid, "brand_id": "brand-1", "brand_name": "Brik Oven",
            "campaign_name": f"C{cid}", "campaign_type": "PLA", "status": "ACTIVE",
            "name_with_active_status": {"is_active": True}, "daily_budget": "1000",
            "lifetime_budget": "", "base_bid": "12", "spend": "250.5", "impressions": "900",
            "clicks": "30", "orders": {"value": "158", "label": "lifetime"},
            "sov": {"value": "12.5", "label": "x"}, "ad_position": {"value": "3"},
            "start_date": "2026-05-04 17:17:59", "end_date": "", **kw}


def test_ad_campaign_rows_parse_strings_boxes_and_blanks():
    r = p.parse_ad_campaigns([_campaign(7)], T, JOB, "2026-10-01", "sponsored_products")[0]
    assert (r["spend"], r["impressions"], r["clicks"], r["orders"]) == (250.5, 900, 30, 158)
    assert (r["sov"], r["ad_position"], r["daily_budget"], r["lifetime_budget"]) == (12.5, 3.0, 1000.0, None)
    assert r["campaign_end_date"] is None and r["campaign_start_date"].year == 2026
    # the analytics-only columns are present as placeholders, so a batch is never ragged
    assert all(k in r and r[k] is None for k in p.TABULAR_CAMPAIGN_FIELDS)
    # keyed on campaign + day, NOT the category tab (a campaign can appear under two)
    other_tab = p.parse_ad_campaigns([_campaign(7)], T, JOB, "2026-10-01", "sponsored_display")[0]
    assert r["upsert_key"] == other_tab["upsert_key"]


def test_ad_campaign_blank_metrics_read_as_zero():
    r = p.parse_ad_campaigns([_campaign(7, spend="-", impressions="-", clicks="-")],
                             T, JOB, "2026-10-01", "sponsored_products")[0]
    assert (r["spend"], r["impressions"], r["clicks"]) == (0.0, 0, 0)


def test_tabular_campaign_patch_covers_exactly_the_placeholders():
    row = {"campaign_name": {"id": "7", "name": "C7"}, "campaign_revenue": "900",
           "campaign_orders": "4", "campaign_atc": "6", "campaign_robas": "3.1",
           "campaign_new_to_brand_user_percentage": "40"}
    patch = p.parse_ad_tabular_campaigns([row, {"campaign_name": {}}])
    assert list(patch) == [7]
    assert set(patch[7]) == set(p.TABULAR_CAMPAIGN_FIELDS)
    assert (patch[7]["revenue"], patch[7]["windowed_orders"], patch[7]["new_to_brand_pct"]) == (900.0, 4, 40.0)


def _kw(name, match, spend, impr, clicks, robas, revenue=0):
    return {"keyword_name": name, "keyword_match_type": match, "keyword_spend": spend,
            "keyword_impressions": impr, "keyword_clicks": clicks, "keyword_robas": robas,
            "keyword_revenue": revenue, "keyword_orders": "1", "keyword_atc": "1",
            "keyword_same_skus": "1", "keyword_other_skus": "0"}


def test_keyword_rows_sum_duplicates_and_rebuild_ratios():
    # The same keyword + match type twice (two campaigns bid it) is SUMMED, not deduped;
    # a different match type is its own row.
    rows = p.parse_ad_keywords(
        [_kw("sado bread", "BROAD", "100", "1000", "10", "2", "300"),
         _kw("sado bread", "BROAD", "300", "3000", "30", "4", "900"),
         _kw("sado bread", "EXACT", "60", "100", "2", "1"),
         {"keyword_name": ""}],
        T, JOB, "2026-10-01", "sponsored_products", "brand-1")
    by = {(r["keyword"], r["match_type"]): r for r in rows}
    assert set(by) == {("sado bread", "BROAD"), ("sado bread", "EXACT")}
    b = by[("sado bread", "BROAD")]
    assert (b["spend"], b["impressions"], b["clicks"], b["orders"]) == (400.0, 4000, 40, 2)
    assert (b["cpc"], b["ctr"], b["cpm"], b["roas"]) == (10.0, 1.0, 100.0, 3.0)
    assert b["robas"] == 3.5                      # spend-weighted: (2*100 + 4*300) / 400


def test_keyword_rows_key_on_category():
    a = p.parse_ad_keywords([_kw("k", "EXACT", "1", "1", "1", "1")], T, JOB, "2026-10-01", "sponsored_products", "b")
    b = p.parse_ad_keywords([_kw("k", "EXACT", "1", "1", "1", "1")], T, JOB, "2026-10-01", "sponsored_brands", "b")
    assert a[0]["upsert_key"] != b[0]["upsert_key"]


def test_product_and_breakdown_rows():
    prod = p.parse_ad_products(
        [{"product_details": {"id": "pv1", "name": "Bread", "image_link": "x"},
          "product_category": "Breads", "product_spend": "50", "product_ctr": "2.5"},
         {"product_details": {}}],
        T, JOB, "2026-10-01", "sponsored_products", "b")
    assert len(prod) == 1 and (prod[0]["spend"], prod[0]["ctr"], prod[0]["product_category"]) == (50.0, 2.5, "Breads")

    city = p.parse_ad_breakdown([{"city_name": "Bengaluru", "city_spend": "80"}],
                                T, JOB, "2026-10-01", "sponsored_products", "b", "city")
    cat = p.parse_ad_breakdown([{"category_name": "Bengaluru", "category_spend": "80"}],
                               T, JOB, "2026-10-01", "sponsored_products", "b", "category")
    assert city[0]["dimension"] == "city" and "ctr" not in city[0]
    assert city[0]["upsert_key"] != cat[0]["upsert_key"]   # same name, different dimension


# ── purchase orders ──────────────────────────────────────────────────────────

def test_po_rows_parse_dates_and_take_the_planned_scheduled_date():
    rows = p.parse_pos([
        {"id": "P1", "poDate": "2026-08-26T01:06:33.4Z", "scheduledDate": None,
         "planningDetails": {"poScheduledDate": "2026-09-04T00:00:00Z"},
         "totalQty": "40", "totalValue": "1234.5", "itemsCount": 3},
        {"id": None},
    ], T, JOB)
    assert len(rows) == 1
    r = rows[0]
    assert (r["po_date"], r["scheduled_date"]) == (date(2026, 8, 26), date(2026, 9, 4))
    assert (r["total_qty"], r["total_value"], r["items_count"]) == (40, 1234.5, 3)
    # keyed on the PO alone, so a re-scrape updates it in place
    assert r["upsert_key"] == p.parse_pos([{"id": "P1"}], T, None)[0]["upsert_key"]


def test_grn_asn_and_item_rows():
    grn = p.parse_grns([{"grnNo": "G1", "poQty": "10", "grnQty": "8", "asnNo": ""}, {}], T, JOB)
    asn = p.parse_asns([{"asnNo": "A1", "asnDate": "2026-09-01T10:00:00Z"}, {}], T, JOB)
    items = p.parse_po_items({"P1": [{"pvId": "pv1", "unitPrice": "40", "mrp": "60", "poQty": "5"},
                                     {"skuCode": "SKU2"}]}, T, JOB)
    assert len(grn) == 1 and (grn[0]["po_qty"], grn[0]["grn_qty"], grn[0]["asn_no"]) == (10, 8, None)
    assert len(asn) == 1 and asn[0]["asn_date"] == date(2026, 9, 1)
    assert [(i["product_variant_id"], i["unit_price"], i["mrp"]) for i in items] == [
        ("pv1", 40.0, 60.0), (None, None, None)]
    assert items[0]["upsert_key"] != items[1]["upsert_key"]


# ── storage guard ────────────────────────────────────────────────────────────

def test_storage_refuses_a_batch_whose_rows_disagree_on_columns():
    from app.models.zepto_seller import ZeptoAdCampaignDaily
    rows = p.parse_ad_campaigns([_campaign(1), _campaign(2)], T, JOB, "2026-10-01", "sponsored_products")
    del rows[1]["revenue"]
    try:
        asyncio.run(storage._upsert(None, ZeptoAdCampaignDaily, rows))
    except ValueError as e:
        assert "revenue" in str(e)
        return
    raise AssertionError("a ragged batch was not refused")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} passed")
