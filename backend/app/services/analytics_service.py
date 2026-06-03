from app.models.sales import Sales
from app.models.product import Product


async def get_overview(tenant_id: str, platform: str) -> dict:
    pass


async def get_revenue_over_time(tenant_id: str, platform: str, days: int = 30) -> list:
    pass
