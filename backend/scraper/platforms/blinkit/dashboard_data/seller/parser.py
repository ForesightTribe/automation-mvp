from scraper.utils.storage import make_upsert_key
from app.utils.time import now_ist


def _strip_quotes(val: str | None) -> str | None:
    """Remove escaped surrounding quotes that appear in some PO API fields."""
    if not isinstance(val, str):
        return val
    return val.strip('"')


def parse_sale_row(raw: dict, tenant_id: str, scrape_job_id: str, date: str) -> dict:
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_sale", raw["item_id"], raw["city_id"], date
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "item_id": raw["item_id"],
        "item_name": raw.get("item_name", ""),
        "category": raw.get("category", ""),
        "city_id": raw["city_id"],
        "city_name": raw.get("city_name", ""),
        "qty_sold": raw.get("qty_sold", 0),
        # mrp in the API response is total MRP value (qty_sold × unit MRP), not unit price
        "mrp_value": raw.get("mrp", 0.0),
        "scraped_at": now_ist(),
    }


def parse_sales_summary(raw: dict, tenant_id: str, scrape_job_id: str, date: str) -> dict:
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_sales_summary", date
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "distinct_skus": raw.get("distinct_skus", 0),
        "distinct_categories": raw.get("distinct_categories", 0),
        "max_sell_item": raw.get("max_sell_item", ""),
        "scraped_at": now_ist(),
    }


# ── PO parsers ────────────────────────────────────────────────────────────────

# Quote-wrapped strings the API sometimes double-encodes (e.g. '"...url..."').
_QUOTED_PO_FIELDS = (
    "download_url",
    "grn_report_excel_url",
    "po_excel_report_url",
    "entity_vendor_cin",
    "entity_vendor_legal_name",
)

# Header fields copied as-is from the PO API. Listed explicitly so the nested
# `items` list and any future/unknown API fields are never carried into the
# insert (which would raise "Unconsumed column names").
_PO_HEADER_FIELDS = (
    "po_number", "po_state", "vendor_id", "vendor_name", "manufacturer_id",
    "manufacturer_name", "facility_id", "facility_name", "city_name", "outlet_id",
    "po_type_id", "address", "issue_date", "expiry_date", "delivery_date",
    "schedule_date", "scheduled_on", "total_units_ordered", "item_count",
    "total_grn_quantity", "total_po_amount", "multiple_grn", "load_size", "active",
    "download_url", "po_excel_report_url", "grn_report_excel_url", "pm_name",
    "pm_phone", "pm_email", "entity_vendor_cin", "entity_vendor_legal_name",
    "delivery_type", "created_at", "updated_at", "created_by", "updated_by",
)

_PO_ITEM_FIELDS = (
    "item_id", "upc", "name", "uom_text", "variant_id", "units_ordered",
    "remaining_quantity", "cost_price", "landing_rate", "mrp", "margin_percentage",
    "total_amount", "tax_value", "cgst_value", "sgst_value", "igst_value",
    "cess_value", "bucket_type", "created_at",
)

_PO_SUMMARY_FIELDS = (
    "total_raised", "scheduled", "created", "cancelled", "expired_unfulfilled",
    "expired_partial", "po_amount", "items_delivered",
)


def parse_po_row(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    row = {f: raw.get(f) for f in _PO_HEADER_FIELDS}
    for field in _QUOTED_PO_FIELDS:
        if row.get(field) is not None:
            row[field] = _strip_quotes(row[field])
    row.update({
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "seller_po", raw["po_number"]),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "scraped_at": now_ist(),
    })
    return row


def parse_po_item(raw: dict, po_number: str, tenant_id: str, scrape_job_id: str) -> dict:
    row = {f: raw.get(f) for f in _PO_ITEM_FIELDS}
    row.update({
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_po_item", po_number, raw["item_id"]
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "po_number": po_number,
        "line_id": raw.get("id"),
        "scraped_at": now_ist(),
    })
    return row


def parse_po_summary(raw: dict, tenant_id: str, scrape_job_id: str, window_start: str) -> dict:
    row = {f: raw.get(f) for f in _PO_SUMMARY_FIELDS}
    row.update({
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "seller_po_snapshot", scrape_job_id),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "window_start": window_start,
        "scraped_at": now_ist(),
    })
    return row


# ── SOH parser ───────────────────────────────────────────────────────────────

def parse_soh_row(raw: dict, tenant_id: str, scrape_job_id: str, date: str) -> dict:
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_soh", raw["item_id"], raw["backend_facility_id"], date
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "item_id": raw["item_id"],
        "item_name": raw.get("item_name", ""),
        "backend_facility_id": raw["backend_facility_id"],
        "backend_facility_name": raw.get("backend_facility_name", ""),
        "manufacturer_id": raw.get("manufacturer_id"),
        "backend_inv_qty": raw.get("backend_inv_qty", 0),
        "frontend_inv_qty": raw.get("frontend_inv_qty", 0),
        "scraped_at": now_ist(),
    }


# ── Scorecard parsers ─────────────────────────────────────────────────────────

def parse_scorecard_weekly(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    from_date = raw["from_date_ist"]
    manufacturer_id = raw["manufacturer_id"]
    overall = raw.get("overall") or {}
    best_cat = raw.get("best_category") or {}
    categories = raw.get("categories") or []

    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_scorecard_weekly", manufacturer_id, from_date
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "manufacturer_id": int(manufacturer_id),
        "from_date_ist": from_date,
        "overall": {
            "total_po_quantity": overall.get("total_po_quantity", 0),
            "total_grn_quantity": overall.get("total_grn_quantity", 0),
            "fill_rate": overall.get("fill_rate", 0.0),
            "weighted_fill_rate_percent": overall.get("weighted_fill_rate_percent", 0.0),
            "potential_loss": overall.get("potential_loss", 0),
            "total_gmv": overall.get("total_gmv", 0.0),
            "manufacturer_rank": overall.get("manufacturer_rank"),
        },
        "best_category": {
            "proxy_category": best_cat.get("proxy_category"),
            "fill_rate": best_cat.get("fill_rate"),
            "weighted_fill_rate_percent": best_cat.get("weighted_fill_rate_percent"),
            "manufacturer_rank": best_cat.get("manufacturer_rank"),
        } if best_cat else None,
        "categories": [
            {
                "proxy_category": c.get("proxy_category"),
                "fill_rate": c.get("fill_rate"),
                "weighted_fill_rate_percent": c.get("weighted_fill_rate_percent"),
                "manufacturer_rank": c.get("manufacturer_rank"),
                "potential_loss": c.get("potential_loss", 0),
                "total_po_quantity": c.get("total_po_quantity", 0),
                "total_grn_quantity": c.get("total_grn_quantity", 0),
            }
            for c in categories
        ],
        "scraped_at": now_ist(),
    }


def parse_scorecard_facility(
    raw: dict, tenant_id: str, scrape_job_id: str, manufacturer_id: str, from_date: str
) -> dict:
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_scorecard_facility", manufacturer_id, from_date, raw["facility_id"]
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "manufacturer_id": int(manufacturer_id),
        "from_date_ist": from_date,
        "facility_id": raw["facility_id"],
        "facility_name": raw.get("facility_name", ""),
        "city_id": raw.get("city_id"),
        "city_name": raw.get("city_name", ""),
        "total_po_quantity": raw.get("total_po_quantity", 0),
        "total_grn_quantity": raw.get("total_grn_quantity", 0),
        "fill_rate": raw.get("fill_rate", 0.0),
        "weighted_fill_rate_percent": raw.get("weighted_fill_rate_percent", 0.0),
        "potential_loss": raw.get("potential_loss", 0),
        "manufacturer_rank": raw.get("manufacturer_rank"),
        "scraped_at": now_ist(),
    }


def parse_scorecard_key_sku(
    raw: dict, tenant_id: str, scrape_job_id: str, manufacturer_id: str, from_date: str
) -> dict:
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "seller_scorecard_sku", manufacturer_id, from_date, raw["item_id"]
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "manufacturer_id": int(manufacturer_id),
        "from_date_ist": from_date,
        "item_id": raw["item_id"],
        "item_name": raw.get("item_name", ""),
        "upc": raw.get("upc", ""),
        "variant_description": raw.get("variant_description", ""),
        "proxy_category": raw.get("proxy_category", ""),
        "potential_loss": raw.get("potential_loss", 0.0),
        "total_gmv": raw.get("total_gmv", 0.0),
        "scraped_at": now_ist(),
    }
