from beanie import Document
from datetime import datetime, date
from typing import Optional
from pymongo import IndexModel, ASCENDING, DESCENDING


class Sales(Document):
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    data_type: str = "sales"
    scrape_job_id: str
    scraped_at: datetime
    date: date
    upsert_key: str             # {tenant_id}:{platform}:sales:{product_id}:{date}

    # Sales fields
    product_id: str
    product_name: Optional[str] = None
    units_sold: int
    revenue: float
    returns: Optional[int] = None

    class Settings:
        name = "sales_data"
        indexes = [
            IndexModel([("upsert_key", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING), ("date", DESCENDING)]),
        ]
