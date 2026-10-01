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
            "sales_amount": b.get("bucket_value", 0.0),
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
            "sales_amount": b.get("bucket_value", 0.0),
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
            "sales_amount": b.get("bucket_value", 0.0),
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


def _money(val) -> float:
    """"₹89,693" -> 89693.0. The API returns sales_amount as a formatted
    string, unlike units_sales which is already numeric."""
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
