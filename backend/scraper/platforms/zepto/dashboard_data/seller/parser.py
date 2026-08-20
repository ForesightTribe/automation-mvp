"""Zepto seller API responses → DB-row dicts.

Same contract as blinkit/dashboard_data/seller/parser.py: pure functions, no I/O,
one dict per row with an `upsert_key` so re-running a window is idempotent.
"""
import uuid
from datetime import date, timedelta

from app.utils.time import now_ist
from scraper.utils.storage import make_upsert_key


def _series_value(point: dict) -> float:
    """Pull the metric out of a daily point.

    Zepto keys the value by the (URL-encoded) brand name — `{"Brik%20Oven":
    56040, "key": "17 Jul"}` — so the metric is 'the entry that isn't "key"'
    rather than a fixed field name.
    """
    for k, v in point.items():
        if k != "key":
            return v or 0
    return 0


def _expected_dates(date_from: date, date_to: date) -> list[date]:
    return [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]


def _label_matches(label: str, day: date) -> bool:
    """Does Zepto's '17 Jul' label agree with the date we derived for it?

    The series carries no year, so dates come from the requested range. This
    guards that assumption: if Zepto ever returns a partial series, or skips a
    day, the labels stop lining up and we find out instead of silently writing
    every row against the wrong date.
    """
    try:
        d, mon = label.split()
        return int(d) == day.day and mon.lower() == day.strftime("%b").lower()
    except (ValueError, AttributeError):
        return False


def parse_sales_daily(
    data: dict,
    ids: dict,
    tenant_id: str,
    scrape_job_id: str | None,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """`fetch_sales_overview` response → one row per day.

    Raises ValueError if the returned series doesn't line up with the requested
    window — see _label_matches.
    """
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    days = _expected_dates(start, end)

    gmv_series = data["metrics"]["gmv"]["data"]
    units_series = data["metrics"]["units"]["data"]

    if len(gmv_series) != len(days):
        raise ValueError(
            f"Zepto returned {len(gmv_series)} days for {date_from}..{date_to} "
            f"({len(days)} expected) — cannot map values to dates safely"
        )

    units_by_label = {p["key"]: _series_value(p) for p in units_series}

    rows = []
    for day, point in zip(days, gmv_series):
        label = point.get("key", "")
        if not _label_matches(label, day):
            raise ValueError(
                f"Zepto day label {label!r} does not match derived date {day} — "
                "the series is not the contiguous range that was requested"
            )
        rows.append(
            {
                "upsert_key": make_upsert_key(
                    tenant_id, "zepto", "seller_sales_daily", ids["brand_id"], day.isoformat()
                ),
                "tenant_id": uuid.UUID(tenant_id),
                "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                "date": day,
                "brand_id": ids["brand_id"],
                "brand_name": ids.get("brand_name"),
                "gmv": float(_series_value(point)),
                "units": int(units_by_label.get(label, 0)),
                "scraped_at": now_ist(),
            }
        )
    return rows


def parse_product_perf(
    products: list[dict],
    tenant_id: str,
    scrape_job_id: str | None,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """`fetch_product_performance` response → one row per SKU for the window.

    The window is part of the key: this endpoint aggregates over start→end
    rather than per day, so the same SKU scraped for a different range is a
    different row, not an overwrite.
    """
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    return [
        {
            "upsert_key": make_upsert_key(
                tenant_id,
                "zepto",
                "seller_product_perf",
                p["productVariantId"],
                start.isoformat(),
                end.isoformat(),
            ),
            "tenant_id": uuid.UUID(tenant_id),
            "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
            "period_start": start,
            "period_end": end,
            "product_variant_id": p["productVariantId"],
            "product_name": p.get("productName"),
            "sku_name": p.get("skuName"),
            "pack_size": str(p["packSize"]) if p.get("packSize") is not None else None,
            "unit_of_measure": p.get("unitOfMeasure"),
            "category_name": p.get("categoryName"),
            "subcategory_name": p.get("subcategoryName"),
            "gmv": float(p.get("gmv") or 0),
            "qty_sold": int(p.get("qtySold") or 0),
            "sales_contribution": p.get("salesContribution"),
            "available_stores": p.get("availableStores"),
            "week_on_week_growth": p.get("weekOnWeekGrowth"),
            "month_on_month_growth": p.get("monthOnMonthGrowth"),
            # Null on every row observed so far — Stock View is subscription-gated.
            "stock_on_hand": p.get("stockOnHand"),
            "scraped_at": now_ist(),
        }
        for p in products
    ]
