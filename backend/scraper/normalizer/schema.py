from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


@dataclass
class NormalizedProduct:
    platform: str
    tenant_id: str
    platform_product_id: str
    name: str
    sku: str
    category: str
    price: float
    mrp: float
    scraped_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NormalizedSales:
    platform: str
    tenant_id: str
    platform_product_id: str
    date: date
    units_sold: int
    revenue: float
    scraped_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NormalizedInventory:
    platform: str
    tenant_id: str
    platform_product_id: str
    stock_available: int
    days_of_inventory: Optional[int] = None
    scraped_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NormalizedAd:
    platform: str
    tenant_id: str
    campaign_id: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    orders: int
    revenue: float
    date: date
    scraped_at: datetime = field(default_factory=datetime.utcnow)
