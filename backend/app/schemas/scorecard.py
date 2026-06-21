from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


class ScorecardWeeklyOut(BaseModel):
    from_date: date
    overall: dict[str, Any]
    best_category: dict[str, Any] | None
    categories: list[dict[str, Any]]


class KeySkuRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: str
    item_name: str | None
    upc: str | None
    variant_description: str | None
    proxy_category: str | None
    potential_loss: float
    total_gmv: float


class FacilityRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    facility_id: str
    facility_name: str | None
    city_name: str | None
    total_po_quantity: int
    total_grn_quantity: int
    fill_rate: float
    weighted_fill_rate_percent: float
    potential_loss: float
    manufacturer_rank: int | None
