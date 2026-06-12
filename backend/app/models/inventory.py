from beanie import Document
from datetime import datetime, date
from typing import Optional
from pymongo import IndexModel, ASCENDING, DESCENDING


class Inventory(Document):
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    data_type: str = "inventory"
    scrape_job_id: str
    scraped_at: datetime
    date: date
    upsert_key: str             # {tenant_id}:{platform}:inventory:{product_id}:{date}

    # Inventory fields
    product_id: str
    product_name: Optional[str] = None
    stock_available: int
    days_of_inventory: Optional[int] = None

    class Settings:
        name = "inventory_data"
        indexes = [
            IndexModel([("upsert_key", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING), ("date", DESCENDING)]),
        ]
