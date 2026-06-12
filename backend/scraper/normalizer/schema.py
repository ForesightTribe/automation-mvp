from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


# ---------------------------------------------------------------------------
# Every normalized schema carries these envelope fields.
# They are populated by the scraper pipeline before calling storage functions.
# ---------------------------------------------------------------------------

@dataclass
class NormalizedProduct:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:product:{product_id}
    data_type: str = "product"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Product fields
    product_id: str = ""
    name: str = ""
    sku: Optional[str] = None
    category: Optional[str] = None
    price: float = 0.0
    mrp: Optional[float] = None


@dataclass
class NormalizedSales:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:sales:{product_id}:{date}
    data_type: str = "sales"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Sales fields
    product_id: str = ""
    product_name: Optional[str] = None
    units_sold: int = 0
    revenue: float = 0.0
    returns: Optional[int] = None


@dataclass
class NormalizedInventory:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:inventory:{product_id}:{date}
    data_type: str = "inventory"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Inventory fields
    product_id: str = ""
    product_name: Optional[str] = None
    stock_available: int = 0
    days_of_inventory: Optional[int] = None


@dataclass
class NormalizedAdCampaign:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:campaign:{name}:{date}
    data_type: str = "campaign"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Campaign fields
    name: Optional[str] = None
    status: Optional[str] = None
    campaign_type: Optional[str] = None
    duration: Optional[str] = None
    budget_consumed: Optional[float] = None
    impressions: Optional[int] = None
    atcs: Optional[int] = None
    roas: Optional[float] = None
    ctr: Optional[float] = None


@dataclass
class NormalizedAdSnapshot:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:snapshot:{date}
    data_type: str = "snapshot"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Aggregate snapshot fields
    total_budget_consumed: Optional[float] = None
    total_impressions: Optional[int] = None
    total_atcs: Optional[int] = None
    total_qty_sold: Optional[int] = None
    total_sales: Optional[float] = None
    overall_roas: Optional[float] = None
    overall_ctr: Optional[float] = None


@dataclass
class NormalizedBrandCollection:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:brand_collection:{name}
    data_type: str = "brand_collection"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Brand collection fields
    name: str = ""
    product_count: Optional[int] = None
    collection_type: Optional[str] = None
    created_by: Optional[str] = None
    created_on: Optional[str] = None


@dataclass
class NormalizedVisibilityPlan:
    # Envelope
    tenant_id: str
    platform: str
    dashboard: str
    scrape_job_id: str
    date: date
    upsert_key: str             # {tenant_id}:{platform}:visibility_plan:{plan}:{period}
    data_type: str = "visibility_plan"
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    # Visibility plan fields
    plan: str = ""
    period: Optional[str] = None
    budget: Optional[float] = None
    status: Optional[str] = None
