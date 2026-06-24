from scraper.utils.storage import make_upsert_key
from app.utils.time import now_ist


def _day(date_ist: str) -> str:
    """'2026-03-25 11:00:00+05:30' -> '2026-03-25'."""
    return (date_ist or "")[:10]


def parse_campaign(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    """Campaign metadata only (metrics live in the daily/detail tables). Keyed on
    campaign so re-scrapes overwrite the latest snapshot in place."""
    return {
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
        "scraped_at": now_ist(),
    }


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
