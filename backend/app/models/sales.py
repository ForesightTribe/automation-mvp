from beanie import Document
from datetime import datetime, date


class Sales(Document):
    platform: str
    tenant_id: str
    platform_product_id: str
    date: date
    units_sold: int
    revenue: float
    scraped_at: datetime = datetime.utcnow()

    class Settings:
        name = "sales"
