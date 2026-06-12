from beanie import Document
from datetime import datetime, date
from typing import Optional
from pymongo import IndexModel, ASCENDING


class BrandCollection(Document):
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    data_type: str = "brand_collection"
    scrape_job_id: str
    scraped_at: datetime
    date: date
    upsert_key: str             # {tenant_id}:{platform}:brand_collection:{name}

    # Brand collection fields
    name: str
    product_count: Optional[int] = None
    collection_type: Optional[str] = None
    created_by: Optional[str] = None
    created_on: Optional[str] = None

    class Settings:
        name = "brand_collections"
        indexes = [
            IndexModel([("upsert_key", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING), ("platform", ASCENDING)]),
        ]
