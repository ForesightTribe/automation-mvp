from beanie import Document
from datetime import datetime
from typing import Optional


class Product(Document):
    platform: str
    tenant_id: str
    platform_product_id: str
    name: str
    sku: str
    category: str
    price: float
    mrp: float
    scraped_at: datetime = datetime.utcnow()

    class Settings:
        name = "products"
