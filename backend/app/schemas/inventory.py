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
    """Public availability/stock-out for the client's own brand (inventory_depth)."""

    model_config = ConfigDict(from_attributes=True)

    sku: str
    product_name: str | None
    city: str
    zone: str
    mp_slug: str = Field(serialization_alias="marketplace")
    in_stock: bool
    depth: int | None
    price: float | None
    scraped_at: datetime
