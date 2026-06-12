from beanie import Document
from datetime import datetime, date
from typing import Optional
from pymongo import IndexModel, ASCENDING, DESCENDING


class AdCampaign(Document):
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    data_type: str              # "campaign" | "snapshot"
    scrape_job_id: str
    scraped_at: datetime
    date: date
    upsert_key: str             # see upsert_key convention in db_architecture.md

    # Campaign fields (data_type = "campaign")
    name: Optional[str] = None
    status: Optional[str] = None
    campaign_type: Optional[str] = None
    duration: Optional[str] = None
    budget_consumed: Optional[float] = None
    impressions: Optional[int] = None
    atcs: Optional[int] = None
    roas: Optional[float] = None
    ctr: Optional[float] = None

    # Snapshot fields (data_type = "snapshot") — aggregate over all campaigns
    total_budget_consumed: Optional[float] = None
    total_impressions: Optional[int] = None
    total_atcs: Optional[int] = None
    total_qty_sold: Optional[int] = None
    total_sales: Optional[float] = None
    overall_roas: Optional[float] = None
    overall_ctr: Optional[float] = None

    class Settings:
        name = "ad_campaigns"
        indexes = [
            IndexModel([("upsert_key", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING), ("date", DESCENDING)]),
        ]
