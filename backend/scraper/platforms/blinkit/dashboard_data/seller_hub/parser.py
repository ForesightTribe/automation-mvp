import re
from datetime import date as date_cls, datetime

from scraper.utils.storage import make_upsert_key
from app.utils.time import now_ist

_ORDINAL = re.compile(r"(\d+)(st|nd|rd|th)", re.IGNORECASE)


def _resolve_bucket_date(bucket_title: str, as_of: date_cls) -> str:
    """"23rd Sep" -> "2026-09-23". The API gives no year, so infer one from
    `as_of` (the scrape date): a bucket whose month is AHEAD of the current
    month means it must be last year (e.g. scraping in January, bucket "28th
    Dec" is December of the YEAR BEFORE the current one, not the current
    year's December, which hasn't happened yet)."""
    no_ordinal = _ORDINAL.sub(r"\1", bucket_title)
    day_str, mon_str = no_ordinal.split()
    try:
        parsed = datetime.strptime(f"{day_str} {mon_str} {as_of.year}", "%d %b %Y").date()
    except ValueError:
        parsed = datetime.strptime(f"{day_str} {mon_str} {as_of.year}", "%d %B %Y").date()
    if parsed > as_of:
        parsed = parsed.replace(year=parsed.year - 1)
    return parsed.isoformat()


def parse_sales_daily(histogram: list[dict], tenant_id: str, scrape_job_id: str) -> list[dict]:
    """`histogram` is the raw `sales_performance_histogram_metrics` list — two
    entries by `title` ("Sales (in INR)", "Sales (in Units)"), each with its
    own `bucket_data` keyed by a date label. Merges the two by date."""
    as_of = now_ist().date()
    by_title = {h["title"]: h for h in histogram}
    inr = by_title.get("Sales (in INR)", {}).get("bucket_data", [])
    units = by_title.get("Sales (in Units)", {}).get("bucket_data", [])
    unit_by_label = {b["bucket_title"]: b["bucket_value"] for b in units}

    rows = []
    for b in inr:
        label = b["bucket_title"]
        day = _resolve_bucket_date(label, as_of)
        rows.append({
            "upsert_key": make_upsert_key(tenant_id, "blinkit", "seller_hub_sales_daily", day),
            "tenant_id": tenant_id,
            "scrape_job_id": scrape_job_id,
            "date": day,
            "sales_amount": _money(b.get("bucket_value")),
            "units_sold": unit_by_label.get(label, 0),
            "scraped_at": now_ist(),
        })
    return rows


def parse_sales_city_daily(
    histogram: list[dict], city: str, tenant_id: str, scrape_job_id: str
) -> list[dict]:
    """Same shape as `parse_sales_daily`, tagged with the city that was
    REQUESTED — the API returns no city field of its own, see
    `BlinkitSellerHubSalesCityDailyRO`'s docstring."""
    as_of = now_ist().date()
    by_title = {h["title"]: h for h in histogram}
    inr = by_title.get("Sales (in INR)", {}).get("bucket_data", [])
    units = by_title.get("Sales (in Units)", {}).get("bucket_data", [])
    unit_by_label = {b["bucket_title"]: b["bucket_value"] for b in units}

    rows = []
    for b in inr:
        label = b["bucket_title"]
        day = _resolve_bucket_date(label, as_of)
        rows.append({
            "upsert_key": make_upsert_key(
                tenant_id, "blinkit", "seller_hub_sales_city_daily", city, day
            ),
            "tenant_id": tenant_id,
            "scrape_job_id": scrape_job_id,
            "city": city,
            "date": day,
            "sales_amount": _money(b.get("bucket_value")),
            "units_sold": unit_by_label.get(label, 0),
            "scraped_at": now_ist(),
        })
    return rows


def parse_sales_category_daily(
    histogram: list[dict], category: str, tenant_id: str, scrape_job_id: str
) -> list[dict]:
    """Same shape as `parse_sales_daily`, tagged with the category that was
    REQUESTED — see `BlinkitSellerHubSalesCategoryDailyRO`'s docstring."""
    as_of = now_ist().date()
    by_title = {h["title"]: h for h in histogram}
    inr = by_title.get("Sales (in INR)", {}).get("bucket_data", [])
    units = by_title.get("Sales (in Units)", {}).get("bucket_data", [])
    unit_by_label = {b["bucket_title"]: b["bucket_value"] for b in units}

    rows = []
    for b in inr:
        label = b["bucket_title"]
        day = _resolve_bucket_date(label, as_of)
        rows.append({
            "upsert_key": make_upsert_key(
                tenant_id, "blinkit", "seller_hub_sales_category_daily", category, day
            ),
            "tenant_id": tenant_id,
            "scrape_job_id": scrape_job_id,
            "category": category,
            "date": day,
            "sales_amount": _money(b.get("bucket_value")),
            "units_sold": unit_by_label.get(label, 0),
            "scraped_at": now_ist(),
        })
    return rows


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
    Applied to every money-bearing field this module parses, even the ones
    that currently come back numeric (histogram bucket_value) rather than as
    a formatted string (by-product sales_amount, order report columns) — a
    2026-10-01 fix: if Blinkit ever changes a numeric endpoint to send money
    as a string instead, this keeps reading it correctly instead of silently
    treating it as zero."""
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
