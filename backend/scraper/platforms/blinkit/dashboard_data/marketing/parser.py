from datetime import datetime, timezone, timedelta
from scraper.utils.storage import make_upsert_key

_IST = timezone(timedelta(hours=5, minutes=30))


def parse_performance_summary(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    now = datetime.now(_IST)
    date = now.strftime("%Y-%m-%d")
    summary = raw.get("summary", {})
    return {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "performance_summary", date),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "budget_consumed": summary.get("budget_consumed", 0),
        "impressions": summary.get("impressions", 0),
        "budget_distribution": raw.get("budget_distribution", {}),
        "scraped_at": now,
    }


def parse_campaign(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    now = datetime.now(_IST)
    date = now.strftime("%Y-%m-%d")
    return {
        "upsert_key": make_upsert_key(tenant_id, "blinkit", "campaign", str(raw["id"]), date),
        "tenant_id": tenant_id,
        "scrape_job_id": scrape_job_id,
        "date": date,
        "campaign_id": raw["id"],
        "name": raw.get("campaign_name", ""),
        "type": raw.get("campaign_type", ""),
        "status": raw.get("campaign_status", ""),
        "start_ts": raw.get("start_ts"),
        "end_ts": raw.get("end_ts"),
        "infinite_campaign": raw.get("infinite_campaign", False),
        "budget_consumed": raw.get("budget_consumed", 0),
        "impressions": raw.get("impressions", 0),
        "atcs": raw.get("atcs", 0),
        "roas": raw.get("roas", 0),
        "reach": raw.get("reach", 0),
        "scraped_at": now,
    }


def parse_sponsored_sov(raw: dict, tenant_id: str, scrape_job_id: str) -> dict:
    now = datetime.now(_IST)
    date = now.strftime("%Y-%m-%d")
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
        "scraped_at": now,
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
        "scraped_at": datetime.now(_IST),
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
        "scraped_at": datetime.now(_IST),
    }
