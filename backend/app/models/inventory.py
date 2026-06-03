from beanie import Document
from datetime import datetime
from typing import Optional


class Inventory(Document):
    platform: str
    tenant_id: str
    platform_product_id: str
    stock_available: int
    days_of_inventory: Optional[int] = None
    scraped_at: datetime = datetime.utcnow()

    class Settings:
        name = "inventory"
