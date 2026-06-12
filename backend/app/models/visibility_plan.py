from beanie import Document
from datetime import datetime, date
from typing import Optional
from pymongo import IndexModel, ASCENDING


class VisibilityPlan(Document):
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    data_type: str = "visibility_plan"
    scrape_job_id: str
    scraped_at: datetime
    date: date
    upsert_key: str             # {tenant_id}:{platform}:visibility_plan:{plan}:{period}

    # Visibility plan fields
    plan: str
    period: Optional[str] = None
    budget: Optional[float] = None
    status: Optional[str] = None

    class Settings:
        name = "visibility_plans"
        indexes = [
            IndexModel([("upsert_key", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING)]),
        ]
