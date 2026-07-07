from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SohRow(BaseModel):
    item_id: str
    item_name: str | None
    backend_qty: int
    frontend_qty: int
    facilities: int
    date: date


class FillRateSummary(BaseModel):
    from_date: date | None
    total_po_quantity: int
    total_grn_quantity: int
    fill_rate: float
    potential_loss: float
    facilities_count: int


class AvailabilityRow(BaseModel):
    """Public availability/stock-out for the client's own brand (sku_snapshots),
    latest row per (marketplace, city, product)."""

    model_config = ConfigDict(from_attributes=True)

    platform_product_id: str
    product_name: str | None
    city: str
    lat: float | None
    lon: float | None
    mp_slug: str = Field(serialization_alias="marketplace")
    in_stock: bool
    inventory: int | None
    price: float | None
    scraped_at: datetime


class DistributionRow(BaseModel):
    """Per own SKU: how widely it's actually on-shelf across serviceable locations."""

    platform_product_id: str
    product_name: str | None
    total_locations: int
    in_stock_locations: int
    distribution_pct: float
    avg_price: float | None
    avg_discount: float | None


class DistributionResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    skus: list[DistributionRow]


class AvailabilityHistoryPoint(BaseModel):
    week: date
    availability_pct: float
    oos_pct: float
    samples: int


class AvailabilityHistoryResponse(BaseModel):
    period_days: int
    points: list[AvailabilityHistoryPoint]


class SkuPricingRow(BaseModel):
    platform_product_id: str
    product_name: str | None
    locations: int
    min_price: float | None
    median_price: float | None
    max_price: float | None
    avg_discount: float | None


class SkuPricingResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    skus: list[SkuPricingRow]
