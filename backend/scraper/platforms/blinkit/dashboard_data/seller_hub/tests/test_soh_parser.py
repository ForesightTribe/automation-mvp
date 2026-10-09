"""Seller-hub stock on hand -> blinkit_soh rows (parser.parse_soh)."""
from scraper.platforms.blinkit.dashboard_data.seller_hub.parser import parse_soh, soh_mismatches

TENANT = "293b8fa2-9008-4194-9a3a-28df52184d98"
JOB = "00000000-0000-0000-0000-000000000000"


def _item(item_id, name, warehouse, darkstore, in_between=0):
    """One inventories/v1/view row, cut to the fields the parser reads."""
    return {
        "item_details": {"item_id": item_id, "product_name": name},
        "stock_on_hand": {"sellable": {
            "warehouse": warehouse, "darkstore": darkstore, "in_between": in_between,
            "total": warehouse + darkstore + in_between,
        }},
    }


RAW = {
    "date": "2026-10-09",
    "rows": [
        {"warehouse": {"id": "7887", "name": "Bengaluru B5 - Feeder"},
         "item": _item(10191468, "Lip Balm (Affogato)", 269, 185, 21)},
        {"warehouse": {"id": "4330", "name": "Kundli Feeder"},
         "item": _item(10191468, "Lip Balm (Affogato)", 113, 117, 9)},
    ],
    "totals": {"10191468": 714},
}


def test_warehouse_is_backend_and_darkstore_is_frontend():
    rows = parse_soh(RAW, TENANT, JOB)
    assert [(r["backend_facility_name"], r["backend_inv_qty"], r["frontend_inv_qty"]) for r in rows] == [
        ("Bengaluru B5 - Feeder", 269, 185),
        ("Kundli Feeder", 113, 117),
    ]
    assert {r["item_id"] for r in rows} == {"10191468"}
    assert {str(r["date"]) for r in rows} == {"2026-10-09"}


def test_one_upsert_key_per_item_warehouse_day():
    rows = parse_soh(RAW, TENANT, JOB)
    assert len({r["upsert_key"] for r in rows}) == 2


def test_mismatch_only_when_warehouses_do_not_add_up():
    assert soh_mismatches(RAW) == {}
    off = {**RAW, "totals": {"10191468": 716}}
    assert soh_mismatches(off) == {"10191468": (714, 716)}
