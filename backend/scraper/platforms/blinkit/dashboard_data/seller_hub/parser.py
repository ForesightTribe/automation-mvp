import re

from scraper.platforms.blinkit.dashboard_data.seller.parser import parse_soh_row
from scraper.utils.storage import make_upsert_key
from app.utils.time import now_ist


def parse_sales_by_product(
    products: list[dict], window_label: str, tenant_id: str, scrape_job_id: str
) -> list[dict]:
    as_of = now_ist().date().isoformat()
    rows = []
    for p in products:
        item_id = str(p["item_id"])
        rows.append({
            "upsert_key": make_upsert_key(
                tenant_id, "blinkit", "seller_hub_sales_by_product", item_id, window_label, as_of
            ),
            "tenant_id": tenant_id,
            "scrape_job_id": scrape_job_id,
            "window_label": window_label,
            "as_of_date": as_of,
            "product_id": str(p.get("product_id")) if p.get("product_id") is not None else None,
            "item_id": item_id,
            "upc": p.get("upc"),
            "product_name": p.get("product_name"),
            "unit": p.get("unit"),
            "business_category_name": p.get("business_category_name"),
            "units_sold": p.get("units_sales", 0),
            "sales_amount": _money(p.get("sales_amount")),
            "sales_contribution_pct": _to_float(p.get("sales_contribution_in_percentage")),
            "is_transitioned": p.get("is_transitioned"),
            "transition_date": p.get("transition_date"),
            "scraped_at": now_ist(),
        })
    return rows


def parse_soh(raw: dict, tenant_id: str, scrape_job_id: str) -> list[dict]:
    """scraper.scrape_soh output -> blinkit_soh rows, built by the OLD
    dashboard's own `parse_soh_row` so both domains write the same row shape
    (and the same upsert key) into the one table the product page reads.

    Seller-hub's "sellable warehouse" is the old dashboard's backend qty and
    "sellable darkstore" its frontend qty. "In between" (on the way from a
    warehouse to a dark store) has no column there and is left out — it is
    still in Blinkit's own sellable total, so the two can differ by it."""
    out = []
    for r in raw["rows"]:
        d, s = r["item"]["item_details"], r["item"]["stock_on_hand"]["sellable"]
        out.append(parse_soh_row({
            "item_id": str(d["item_id"]),
            "item_name": d.get("product_name") or "",
            "backend_facility_id": str(r["warehouse"]["id"]),
            "backend_facility_name": r["warehouse"].get("name") or "",
            "backend_inv_qty": _to_int(s.get("warehouse")),
            "frontend_inv_qty": _to_int(s.get("darkstore")),
        }, tenant_id, scrape_job_id, raw["date"]))
    return out


def soh_mismatches(raw: dict) -> dict[str, tuple[int, int]]:
    """Items whose per-warehouse sellable stock does not add up to Blinkit's
    own all-warehouse total: {item_id: (sum of warehouses, Blinkit total)}."""
    summed: dict[str, int] = {}
    for r in raw["rows"]:
        iid = str(r["item"]["item_details"]["item_id"])
        summed[iid] = summed.get(iid, 0) + _to_int(r["item"]["stock_on_hand"]["sellable"].get("total"))
    return {i: (summed.get(i, 0), _to_int(t)) for i, t in raw["totals"].items() if summed.get(i, 0) != _to_int(t)}


def parse_sales_orders(rows: list[dict], tenant_id: str, scrape_job_id: str) -> list[dict]:
    """`rows` is one dict per Excel data row, keyed by the "Download sales
    sheet" report's own column headers (see scraper.fetch_sales_order_report)
    — mapped here to BlinkitSellerHubSalesOrderRO's field names. The sheet
    mixes str/int/float for the same numeric column across rows (verified
    live), so every numeric field goes through `_money`/`_to_int`, never used
    raw.

    Key is (order_id, item_id), not order_id alone — an order with 2 items is
    2 rows in the sheet, confirmed live."""
    out = []
    for r in rows:
        order_id = str(r.get("Order Id") or "").strip()
        item_id = str(r.get("Item Id") or "").strip()
        if not order_id or not item_id:
            continue
        order_date_raw = r.get("Order Date")
        order_date = str(order_date_raw)[:10] if order_date_raw else None
        if not order_date:
            continue
        out.append({
            "upsert_key": make_upsert_key(
                tenant_id, "blinkit", "seller_hub_sales_order", order_id, item_id
            ),
            "tenant_id": tenant_id,
            "scrape_job_id": scrape_job_id,
            "order_id": order_id,
            "order_date": order_date,
            "item_id": item_id,
            "product_name": r.get("Product Name"),
            "brand_name": r.get("Brand Name"),
            "upc": r.get("UPC"),
            "variant_description": r.get("Variant Description"),
            "consumer_app_mapping": r.get("Mapping on consumer app (L0, L1, L2)"),
            "business_category": r.get("Business Category"),
            "expansion_level": r.get("Expansion Level"),
            "supply_city": r.get("Supply City"),
            "supply_state": r.get("Supply State"),
            "supply_state_gst": r.get("Supply State GST"),
            "customer_city": r.get("Customer City"),
            "customer_state": r.get("Customer State"),
            "order_status": r.get("Order Status"),
            "hsn_code": r.get("HSN Code"),
            "igst_pct": _to_float(r.get("IGST(%)")),
            "cgst_pct": _to_float(r.get("CGST(%)")),
            "sgst_pct": _to_float(r.get("SGST(%)")),
            "cess_pct": _to_float(r.get("CESS(%)")),
            "quantity": _to_int(r.get("Quantity")),
            "mrp": _money(r.get("MRP (Rs)")),
            "selling_price": _money(r.get("Selling Price (Rs)")),
            "igst_value": _money(r.get("IGST Value")),
            "cgst_value": _money(r.get("CGST Value")),
            "sgst_value": _money(r.get("SGST Value")),
            "cess_value": _money(r.get("CESS Value")),
            "total_tax": _money(r.get("Total Tax")),
            "total_gross_amount": _money(r.get("Total Gross Bill Amount")),
            "scraped_at": now_ist(),
        })
    return out


def _money(val) -> float:
    """"₹89,693" -> 89693.0, and passes a plain number through unchanged.
    Applied to every money-bearing field this module parses, so a field that
    switches between a number and a formatted string is read correctly
    either way instead of silently becoming zero."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[₹,\s]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val) -> int:
    if val is None:
        return 0
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0
