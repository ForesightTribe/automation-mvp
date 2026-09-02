from scraper.utils.storage import make_upsert_key
from app.utils.time import now_ist


def _day(date_ist: str) -> str:
    """'2026-03-25 11:00:00+05:30' -> '2026-03-25'."""
    return (date_ist or "")[:10]


def parse_campaign(raw: dict, tenant_id: str, scrape_job_id: str,
                   detail: dict | None = None, cities: dict | None = None) -> dict:
    """Campaign metadata only (metrics live in the daily/detail tables). Keyed on
    campaign so re-scrapes overwrite the latest snapshot in place.

    `raw` is a row from the campaign LIST; `detail` is that campaign's configuration
    response, which the list does not contain. Everything detail-derived is optional so a
    campaign whose detail call failed still upserts its list fields rather than being
    dropped — but note the columns then go NULL, since the upsert overwrites every
    updatable column (a partial write would leave yesterday's values looking current).

    `cities` is the account's `{id: name}` directory, used to resolve `region_ids` into
    names here so nothing downstream needs a city lookup table.
    """
    row = {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "campaign", str(raw["id"])),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "campaign_id": raw["id"],
        "name": raw.get("campaign_name", ""),
        "type": raw.get("campaign_type", ""),
        "status": raw.get("campaign_status", ""),
        "start_ts": raw.get("start_ts"),
        "end_ts": raw.get("end_ts"),
        "infinite_campaign": raw.get("infinite_campaign", False),
        # ⚠️ Blinkit's campaign LIST has no budget field at all — this is NULL unless the
        # detail call below supplies it.
        "daily_budget": raw.get("campaign_budget"),
        "scraped_at": now_ist(),
        # ⚠️ These MUST be present on every row, even when there is no detail. The storage
        # layer inserts the batch in one multi-row statement, and SQLAlchemy requires a
        # uniform column set across it — a row missing these keys fails the whole insert
        # with "explicitly rendered as a boundparameter in the VALUES clause". Absent means
        # NULL here, deliberately: the upsert overwrites every updatable column, so a
        # partial write would leave yesterday's targeting looking current.
        "region_type": None,
        "cities": None,
        "min_cpm": None,
        "pacing_type": None,
        "billed_amount": None,
        "campaign_cpm": None,
    }
    if not detail:
        return row

    campaign_type = detail.get("campaign_type") or raw.get("campaign_type") or ""
    row.update({
        "daily_budget": detail.get("campaign_budget", row["daily_budget"]),
        "region_type": detail.get("region_type"),
        "cities": _resolve_cities(detail.get("region_ids"), cities),
        "min_cpm": (detail.get("min_cpm_config") or {}).get(campaign_type),
        "pacing_type": detail.get("pacing_type"),
        "billed_amount": detail.get("billed_amount"),
        "campaign_cpm": detail.get("cpm"),
    })
    return row


def _resolve_cities(region_ids, cities: dict | None) -> list | None:
    """`region_ids` → `[{"id": 1, "name": "Delhi"}]` using the account's directory.

    None (not `[]`) when the campaign has no city targeting, so "pan-India" stays
    distinguishable from "targeted, but we could not read the names". An id missing from
    the directory keeps its number as the name — losing the row would silently narrow a
    campaign's targeting in the UI.
    """
    if not region_ids:
        return None
    if not isinstance(region_ids, list):
        region_ids = [region_ids]
    directory = cities or {}
    return [
        {"id": rid, "name": directory.get(str(rid)) or directory.get(rid) or str(rid)}
        for rid in region_ids
        if rid is not None
    ]


def parse_campaign_keywords(
    attributes: list,
    detail: dict,
    campaign_id: int,
    tenant_id: str,
    scrape_job_id: str,
) -> list[dict]:
    """A campaign's keywords with Blinkit's published bid range for each (V7).

    One row per (campaign, keyword, match_type) — the engine's write key. Blinkit publishes
    a range per match type (`exact_match` / `smart_match`) whether or not the campaign bids
    that type, so `current_cpm` is filled only where the campaign actually has a bid.

    `min_bid` here is the number the client meant by "the tech should know the min bid",
    and it genuinely varies per keyword (₹100 on 'soda', ₹200 on 'protein chips').
    """
    # The campaign's own bids, so a published range can be paired with the live CPM.
    entries = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
        or detail.get("keywords", []) or []
    )
    current: dict[tuple[str, str], int] = {}
    for kw in entries:
        name = (kw.get("keyword") or "").strip()
        for bid in kw.get("bids") or []:
            match = _norm_match(bid.get("match_type"))
            if name and match and bid.get("cpm") is not None:
                current[(name, match)] = int(bid["cpm"])

    campaign_type = detail.get("campaign_type")
    rows: list[dict] = []
    for attr in attributes or []:
        keyword = (attr.get("keyword") or "").strip()
        if not keyword:
            continue
        searches = attr.get("keyword_searches")
        for api_match, rng in (attr.get("bid_range") or {}).items():
            if not isinstance(rng, dict):
                continue
            match = _norm_match(api_match)
            rows.append({
                "upsert_key": make_upsert_key(
                    tenant_id, "blinkit", "ad_kw_bid", str(campaign_id), keyword, match,
                ),
                "tenant_id": tenant_id,
                "scrape_job_id": scrape_job_id,
                "campaign_id": campaign_id,
                "campaign_type": campaign_type,
                "keyword": keyword,
                "match_type": match,
                "current_cpm": current.get((keyword, match)),
                "min_bid": rng.get("min"),
                "max_bid": rng.get("max"),
                "suggested_min": rng.get("suggested_min"),
                "suggested_max": rng.get("suggested_max"),
                "min_for_boost": rng.get("min_for_boost"),
                "keyword_searches": searches,
                "scraped_at": now_ist(),
            })
    return rows


def _norm_match(value: str | None) -> str:
    """Blinkit names match types two ways depending on which response you read:
    `bid_range` is keyed `exact_match`/`smart_match`, while a campaign's bids carry
    `EXACT`/`SMART` (and legacy `EXACT_MATCH`). Normalise to the campaign-write vocabulary
    so a range and a live bid for the same keyword land on the SAME row."""
    v = (value or "").strip().upper().replace("_MATCH", "")
    return v or "EXACT"


def parse_campaign_daily(
    raw: dict, campaign_id: int, campaign_type: str | None, tenant_id: str, scrape_job_id: str
) -> dict:
    """One day of a campaign's metrics (from metrics-trends/{id})."""
    date = _day(raw.get("date_ist"))
    return {
        "upsert_key": make_upsert_key(
            tenant_id, "blinkit", "ad_daily", str(campaign_id), date
        ),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "campaign_id": campaign_id,
        "campaign_type": campaign_type,
        "budget_consumed": raw.get("budget_consumed", 0),
        "impressions": raw.get("impressions", 0),
        "atc": raw.get("total_atc", 0),
        "quantities_sold": raw.get("total_quantities_sold", 0),
        "ad_sales": raw.get("total_sales", 0.0),
        "roas": raw.get("total_roas", 0.0),
        "scraped_at": now_ist(),
    }


def parse_campaign_detail(
    report_data: dict,
    campaign_id: int,
    campaign_type: str | None,
    snapshot_date: str,
    tenant_id: str,
    scrape_job_id: str,
) -> list[dict]:
    """Flatten a campaign report's keyword / recommendation breakdown into rows
    for the unified detail table. `reporting` is keyed by group ('keyword' or
    'product_recommendation'); each row becomes one target."""
    reporting = report_data.get("reporting") or {}
    rows: list[dict] = []
    for group, entries in reporting.items():
        is_keyword = group == "keyword"
        target_type = "keyword" if is_keyword else "recommendation"
        for r in entries or []:
            target = r.get("keyword") or r.get("asset_type") or group
            # The same keyword can appear under several match types, each its own
            # sub-campaign — key on sub_campaign_id when present so they don't
            # collide (fall back to target for recommendation/asset rows).
            disc = (
                str(r["sub_campaign_id"])
                if r.get("sub_campaign_id") is not None
                else str(target)
            )
            rows.append(
                {
                    "upsert_key": make_upsert_key(
                        tenant_id, "blinkit", "ad_detail",
                        str(campaign_id), disc, snapshot_date,
                    ),
                    "tenant_id": tenant_id,
                    "scrape_job_id": scrape_job_id,
                    "snapshot_date": snapshot_date,
                    "campaign_id": campaign_id,
                    "campaign_type": campaign_type,
                    "target_type": target_type,
                    "target": str(target),
                    "sub_campaign_id": r.get("sub_campaign_id"),
                    "match_type": r.get("match_type"),
                    "impressions": r.get("impressions", 0),
                    "budget_consumed": r.get("budget_consumed", 0),
                    "cpm": r.get("cpm", 0),
                    "direct_atc": r.get("direct_atc", 0),
                    "indirect_atc": r.get("indirect_atc", 0),
                    "direct_sales": r.get("direct_sales", 0.0),
                    "indirect_sales": r.get("indirect_sales", 0.0),
                    "direct_quantities_sold": r.get("direct_quantities_sold", 0),
                    "indirect_quantities_sold": r.get("indirect_quantities_sold", 0),
                    "new_users_acquired": r.get("new_users_acquired", 0),
                    "most_viewed_position": r.get("most_viewed_position"),
                    "direct_roas": r.get("direct_roas", 0.0),
                    "total_roas": r.get("total_roas", 0.0),
                    "scraped_at": now_ist(),
                }
            )
    return rows


def parse_sponsored_sov(raw: dict, tenant_id: str, scrape_job_id: str, date: str) -> dict:
    keyword = raw.get("keyword", "")
    return {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "sov", keyword, date),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "keyword": keyword,
        "monthly_searches": raw.get("monthly_searches", 0),
        "searches": raw.get("searches", 0),
        "sov": raw.get("sov", 0.0),
        "scraped_at": now_ist(),
    }


def parse_brand_collection(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    return {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "brand_collection", str(raw["id"])),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "collection_id": raw["id"],
        "collection_uuid": raw.get("collection_uuid"),
        "name": raw.get("collection_name", ""),
        "number_of_products": raw.get("number_of_products", 0),
        "is_dynamic": raw.get("is_dynamic", False),
        "created_by": raw.get("created_by"),
        "created_on": raw.get("created_on"),
        "scraped_at": now_ist(),
    }


def parse_visibility_plan(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    return {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "visibility_plan", str(raw["id"])),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "plan_id": raw["id"],
        "name": raw.get("name", ""),
        "type": raw.get("type", ""),
        "budget": raw.get("budget", 0),
        "start_date": raw.get("start_date"),
        "end_date": raw.get("end_date"),
        "status": raw.get("status", ""),
        "scraped_at": now_ist(),
    }
