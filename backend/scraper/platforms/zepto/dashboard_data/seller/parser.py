"""Zepto seller API responses → DB-row dicts.

Same contract as blinkit/dashboard_data/seller/parser.py: pure functions, no I/O,
one dict per row with an `upsert_key` so re-running a window is idempotent.
"""
import uuid
from datetime import date, datetime, timedelta

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


def parse_sales_by_city(
    by_city: dict[str, dict],
    city_names: dict[str, str],
    ids: dict,
    tenant_id: str,
    scrape_job_id: str | None,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """`fetch_sales_by_city` output -> one row per city per day.

    Cities with no sales at all are skipped rather than stored as zeros: 137 of
    138 cities were empty on 21-Aug-2026, and writing those would be ~1,000 zero
    rows a week that mean nothing. A city that genuinely drops to zero on a day
    it normally sells still gets its row, because the rest of its series is
    non-zero.

    Reuses `_label_matches` for the same reason `parse_sales_daily` does: the
    series carries no year, so a mismatch means the returned days are not the
    range that was asked for.
    """
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    days = _expected_dates(start, end)
    rows: list[dict] = []

    for city_id, data in by_city.items():
        gmv_series = ((data.get("metrics") or {}).get("gmv") or {}).get("data") or []
        units_series = ((data.get("metrics") or {}).get("units") or {}).get("data") or []
        if len(gmv_series) != len(days):
            raise ValueError(
                f"Zepto returned {len(gmv_series)} days for city {city_id} "
                f"({len(days)} expected) — cannot map values to dates safely"
            )
        if not any(_series_value(p) for p in gmv_series) and not any(
            _series_value(p) for p in units_series
        ):
            continue

        units_by_label = {p["key"]: _series_value(p) for p in units_series}
        for day, point in zip(days, gmv_series):
            label = point.get("key", "")
            if not _label_matches(label, day):
                raise ValueError(
                    f"Zepto day label {label!r} does not match derived date {day} "
                    f"for city {city_id} — the series is not the range requested"
                )
            rows.append(
                {
                    "upsert_key": make_upsert_key(
                        tenant_id, "zepto", "seller_sales_city_daily", city_id, day.isoformat()
                    ),
                    "tenant_id": uuid.UUID(tenant_id),
                    "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                    "date": day,
                    "brand_id": ids["brand_id"],
                    "city_id": city_id,
                    "city_name": city_names.get(city_id),
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


def _f(v) -> float | None:
    """Zepto sends every number as a string, and uses "" for absent rather than
    null (e.g. lifetime_budget on a campaign with none)."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v) -> int:
    f = _f(v)
    return int(f) if f is not None else 0


def _dt(v) -> datetime | None:
    """"2026-05-04 17:17:59" -> datetime; "" -> None (open-ended campaign)."""
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _boxed(v):
    """Several fields arrive as {"value": "16", "label": "Low ad rank"} rather
    than a bare value — the label is UI advice, so only the value is kept."""
    if isinstance(v, dict):
        return v.get("value")
    return v


# The campaign columns that come from /metrics/tabular rather than /campaigns.
# Single source of truth for both the placeholders `parse_ad_campaigns` emits
# and the patch `parse_ad_tabular_campaigns` builds, so the two cannot drift
# apart and reintroduce a ragged batch.
TABULAR_CAMPAIGN_FIELDS = (
    "revenue",
    "atc",
    "windowed_orders",
    "robas",
    "cpm",
    "same_skus",
    "other_skus",
    "unique_reach",
    "new_to_brand_pct",
)


def parse_ad_campaigns(
    campaigns: list[dict],
    tenant_id: str,
    scrape_job_id: str | None,
    day: str,
    category: str,
) -> list[dict]:
    """One `/ads-bff/api/v1/campaigns` response for a single day -> rows.

    `day` is both the window scraped and the row's date: the caller asks for
    from_date == to_date so the metrics belong to that one day.
    """
    d = date.fromisoformat(day)
    rows = []
    for c in campaigns:
        name_status = c.get("name_with_active_status") or {}
        rows.append(
            {
                # Deliberately NOT keyed on `category`. Zepto's categoryType
                # filter leaks: asking for sponsored_products also returns a
                # Display/PCA campaign, which the Sponsored Display tab would
                # return again. Keyed per tab, that same campaign-day would be
                # stored twice and its spend counted twice. Keyed on campaign +
                # day, the second write simply overwrites the first with the
                # same figures. `campaign_category` is kept as a column so it
                # is still visible which tab a row was found under.
                "upsert_key": make_upsert_key(
                    tenant_id, "zepto", "ad_campaign_daily", c["campaign_id"], day
                ),
                "tenant_id": uuid.UUID(tenant_id),
                "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                "date": d,
                "campaign_id": int(c["campaign_id"]),
                "campaign_name": c.get("campaign_name") or name_status.get("campaign_name"),
                "brand_id": c["brand_id"],
                "brand_name": c.get("brand_name"),
                "campaign_category": category,
                "campaign_type": c.get("campaign_type"),
                "campaign_sub_type": c.get("campaign_sub_type"),
                "status": c.get("status"),
                "is_active": name_status.get("is_active"),
                "bid_targeting_type": c.get("bid_targeting_type"),
                "campaign_targeting_type": c.get("campaign_targeting_type"),
                "daily_budget": _f(c.get("daily_budget")),
                "lifetime_budget": _f(c.get("lifetime_budget")),
                "base_bid": _f(c.get("base_bid")),
                "spend": _f(c.get("spend")) or 0.0,
                "impressions": _i(c.get("impressions")),
                "clicks": _i(c.get("clicks")),
                "orders": _i(_boxed(c.get("orders"))),
                "cpc": _f(c.get("cpc")),
                "ecpm": _f(c.get("ecpm")),
                "roi": _f(c.get("roi")),
                "sov": _f(_boxed(c.get("sov"))),
                "ad_position": _f(_boxed(c.get("ad_position"))),
                "campaign_start_date": _dt(c.get("start_date")),
                "campaign_end_date": _dt(c.get("end_date")),
                # Placeholders for the Analytics-table metrics, which this
                # endpoint does not report — `parse_ad_tabular_campaigns` fills
                # them in for campaigns that had activity in the window.
                #
                # They are spelled out here rather than left absent so every row
                # in a batch has the same keys. A multi-row INSERT ... VALUES
                # binds one parameter set per row and requires a uniform shape;
                # a batch mixing patched and unpatched rows failed with
                # "INSERT value for column ... is explicitly rendered as a
                # boundparameter", which does not obviously mean "your dicts
                # disagree". A campaign with no spend that day legitimately has
                # no analytics row, so None is the right stored value.
                **dict.fromkeys(TABULAR_CAMPAIGN_FIELDS),
                "scraped_at": now_ist(),
            }
        )
    return rows


def _tab(row: dict, dim: str, field: str):
    """Pull `{dim}_{field}` out of a /metrics/tabular row.

    Every view uses the same metric names prefixed with its dimension, so one
    accessor serves campaign_table, keyword_table and the rest.
    """
    return row.get(f"{dim}_{field}")


def parse_ad_tabular_campaigns(rows: list[dict]) -> dict[int, dict]:
    """`campaign_table` rows -> {campaign_id: metrics} for merging.

    Returns a patch rather than complete rows on purpose. These metrics belong
    on the same campaign x day row as the Campaign Management fields, and a
    partial upsert would blank the columns it does not carry (ON CONFLICT DO
    UPDATE writes every column from `excluded`). The caller merges this into
    the `parse_ad_campaigns` output before a single write.

    `campaign_name` is a box: {"id", "name", "campaign_sub_type"} — the id is
    the only place this view reports which campaign a row belongs to.
    """
    out: dict[int, dict] = {}
    for r in rows:
        box = r.get("campaign_name") or {}
        cid = box.get("id")
        if cid is None:
            continue
        out[int(cid)] = {
            "revenue": _f(_tab(r, "campaign", "revenue")),
            "atc": _i(_tab(r, "campaign", "atc")),
            # NOT the `orders` from /campaigns, which is a lifetime figure that
            # ignores the date range. This one moves with the window.
            "windowed_orders": _i(_tab(r, "campaign", "orders")),
            "robas": _f(_tab(r, "campaign", "robas")),
            "cpm": _f(_tab(r, "campaign", "cpm")),
            "same_skus": _i(_tab(r, "campaign", "same_skus")),
            "other_skus": _i(_tab(r, "campaign", "other_skus")),
            "unique_reach": _i(_tab(r, "campaign", "unique_reach")),
            "new_to_brand_pct": _f(_tab(r, "campaign", "new_to_brand_user_percentage")),
        }
        # The patch must cover exactly the placeholder set, or merging it leaves
        # the batch ragged and the insert fails far from the cause.
        assert set(out[int(cid)]) == set(TABULAR_CAMPAIGN_FIELDS), (
            "tabular patch keys drifted from TABULAR_CAMPAIGN_FIELDS"
        )
    return out


def parse_ad_keywords(
    rows: list[dict],
    tenant_id: str,
    scrape_job_id: str | None,
    day: str,
    category: str,
    brand_id: str,
) -> list[dict]:
    """`keyword_table` rows -> one row per keyword per match type per day.

    Two things about this endpoint's grain, both found by cross-checking a
    day's keyword rows against the same day's campaign rows (14-Aug-2026,
    sponsored products): spend, clicks, add-to-carts and orders agree to the
    unit — Rs 8,136 / 367 / 72 / 251 either way — so every row returned is
    additive and none may be discarded.

    1. `match_type` is part of the key, not an attribute. Zepto returns the
       same keyword once per match type ("sado bread" BROAD at Rs 2,014 and
       EXACT at Rs 60 are two separate bids).
    2. Even keyword+match_type is not unique. The response carries no campaign
       id, so a keyword bid by two campaigns comes back as two rows that are
       identical in every field ("bakers dozen bread" BROAD, 16 impressions,
       twice). They are summed rather than de-duplicated — dropping one would
       have lost real impressions, and the totals above prove they are
       distinct events. A row therefore means "this keyword, this match type,
       this day, across every campaign that bid it".

    `category` IS part of the key, unlike the campaign rows. The tabular
    endpoint honours `campaign_category` (verified same day: sponsored products
    6 campaigns / Rs 8,136, sponsored brands 1 / Rs 144, display 0 — disjoint,
    summing to the Rs 8,280 the campaigns endpoint reports for the day). So the
    same keyword under two tabs is two real bids, not the duplicate that
    `/campaigns` would have produced.
    """
    d = date.fromisoformat(day)

    # Sum the additive metrics per (keyword, match_type); ratios are rebuilt
    # from those sums afterwards, since averaging a per-row CPC would weight a
    # 2-click row the same as a 68-click one.
    _ADDITIVE = ("spend", "revenue", "impressions", "clicks", "orders", "atc",
                 "same_skus", "other_skus")
    groups: dict[tuple[str, str | None], dict] = {}
    for r in rows:
        kw = _tab(r, "keyword", "name")
        if not kw:
            continue
        match = _tab(r, "keyword", "match_type")
        g = groups.setdefault(
            (kw, match), {"keyword": kw, "match_type": match, "robas_x_spend": 0.0}
        )
        for f in _ADDITIVE:
            g[f] = (g.get(f) or 0) + (_f(_tab(r, "keyword", f)) or 0)
        # robas cannot be rebuilt from the columns we keep — it excludes
        # free-of-cost revenue, which is not reported separately. Weighting each
        # row's ratio by its spend reconstructs it exactly, because
        # sum(robas_i * spend_i) / sum(spend_i) == sum(foc_excluded_revenue_i)
        # / sum(spend_i).
        g["robas_x_spend"] += (_f(_tab(r, "keyword", "robas")) or 0) * (
            _f(_tab(r, "keyword", "spend")) or 0
        )

    out = []
    for (kw, match), g in groups.items():
        spend, impr, clicks = g["spend"], int(g["impressions"]), int(g["clicks"])
        revenue = g["revenue"]
        out.append(
            {
                "upsert_key": make_upsert_key(
                    tenant_id,
                    "zepto",
                    "ad_keyword_daily",
                    category,
                    kw,
                    match or "-",
                    day,
                ),
                "tenant_id": uuid.UUID(tenant_id),
                "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                "date": d,
                "brand_id": brand_id,
                "campaign_category": category,
                "keyword": kw,
                "match_type": match,
                "spend": spend,
                "revenue": revenue,
                "impressions": impr,
                "clicks": clicks,
                "orders": int(g["orders"]),
                "atc": int(g["atc"]),
                "ctr": round(clicks / impr * 100, 4) if impr else None,
                "cpc": round(spend / clicks, 4) if clicks else None,
                "cpm": round(spend / impr * 1000, 4) if impr else None,
                "roas": round(revenue / spend, 4) if spend else None,
                "robas": round(g["robas_x_spend"] / spend, 4) if spend else None,
                "same_skus": int(g["same_skus"]),
                "other_skus": int(g["other_skus"]),
                "scraped_at": now_ist(),
            }
        )
    return out


def _tab_metrics(row: dict, dim: str, *, ctr: bool) -> dict:
    """The metric set every /metrics/tabular view shares, under its prefix."""
    out = {
        "spend": _f(_tab(row, dim, "spend")) or 0.0,
        "revenue": _f(_tab(row, dim, "revenue")),
        "impressions": _i(_tab(row, dim, "impressions")),
        "clicks": _i(_tab(row, dim, "clicks")),
        "orders": _i(_tab(row, dim, "orders")),
        "atc": _i(_tab(row, dim, "atc")),
        "cpc": _f(_tab(row, dim, "cpc")),
        "cpm": _f(_tab(row, dim, "cpm")),
        "roas": _f(_tab(row, dim, "roas")),
        "robas": _f(_tab(row, dim, "robas")),
        "same_skus": _i(_tab(row, dim, "same_skus")),
        "other_skus": _i(_tab(row, dim, "other_skus")),
    }
    if ctr:
        out["ctr"] = _f(_tab(row, dim, "ctr"))
    return out


def parse_ad_products(
    rows: list[dict],
    tenant_id: str,
    scrape_job_id: str | None,
    day: str,
    category: str,
    brand_id: str,
) -> list[dict]:
    """`product_table` rows -> one row per SKU per day per ad type.

    One row per product variant, unlike the keyword view: product ids were
    unique within a category-day on every response checked, so no summing is
    needed here. `campaign_category` is still in the key — no product was seen
    under two ad types, but a retail category was (Cheese, 19-Aug-2026), so the
    same guard is applied rather than trusting that to hold.

    `product_details` is a box — {"id", "name", "image_link"} — and is the only
    place the variant id appears.
    """
    d = date.fromisoformat(day)
    out = []
    for r in rows:
        details = r.get("product_details") or {}
        pid = details.get("id")
        if not pid:
            continue
        out.append(
            {
                "upsert_key": make_upsert_key(
                    tenant_id, "zepto", "ad_product_daily", category, pid, day
                ),
                "tenant_id": uuid.UUID(tenant_id),
                "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                "date": d,
                "brand_id": brand_id,
                "campaign_category": category,
                "product_variant_id": pid,
                "product_name": details.get("name"),
                "image_link": details.get("image_link"),
                # The SKU's retail category, not the ad type.
                "product_category": _tab(r, "product", "category"),
                **_tab_metrics(r, "product", ctr=True),
                "scraped_at": now_ist(),
            }
        )
    return out


def parse_ad_breakdown(
    rows: list[dict],
    tenant_id: str,
    scrape_job_id: str | None,
    day: str,
    category: str,
    brand_id: str,
    dimension: str,
) -> list[dict]:
    """`category_table` / `city_table` / `page_table` rows -> breakdown rows.

    One parser for three views because they are structurally identical: each
    returns a `{dim}_name` and the same twelve metrics, nothing else. `dimension`
    says which, and is part of the key so a city and a retail category that
    happen to share a name on the same day cannot collide.

    Two senses of "category" meet here. `dimension="category"` means the RETAIL
    category ("Breads & Buns"), while the `category` argument is the AD type
    (sponsored_products / _brands / _display). Both are in the key: Cheese ran
    under two ad types on 19-Aug-2026 at Rs 1,422 and Rs 158, and keying on the
    name alone would have thrown one away.

    None of these three views reports CTR, unlike product and keyword.
    """
    d = date.fromisoformat(day)
    out = []
    for r in rows:
        name = _tab(r, dimension, "name")
        if not name:
            continue
        out.append(
            {
                "upsert_key": make_upsert_key(
                    tenant_id, "zepto", "ad_breakdown_daily", dimension, category, name, day
                ),
                "tenant_id": uuid.UUID(tenant_id),
                "scrape_job_id": uuid.UUID(scrape_job_id) if scrape_job_id else None,
                "date": d,
                "brand_id": brand_id,
                "campaign_category": category,
                "dimension": dimension,
                "name": name,
                **_tab_metrics(r, dimension, ctr=False),
                "scraped_at": now_ist(),
            }
        )
    return out
