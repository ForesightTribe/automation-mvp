from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.analytics import Metric


class ScorecardWeeklyOut(BaseModel):
    """A single scorecard week. `overall` is the raw snapshot JSON; `metrics`
    repacks each overall number as a {value, prev, delta_pct} against the
    immediately-preceding week so the KPI tiles get growth badges (consistent
    with the rest of the dashboard). `categories`/`best_category` feed the
    per-category section."""

    from_date: date
    prev_from_date: date | None
    overall: dict[str, Any]
    metrics: dict[str, Metric]
    best_category: dict[str, Any] | None
    categories: list[dict[str, Any]]


class ScorecardTrendPoint(BaseModel):
    """One week on the fill-rate / potential-loss trend line."""

    from_date: date
    fill_rate: float | None
    weighted_fill_rate_percent: float | None
    potential_loss: float | None
    total_gmv: float | None
    total_po_quantity: int | None
    total_grn_quantity: int | None
    manufacturer_rank: int | None


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


class FacilityPoRow(BaseModel):
    """A PO behind a facility's fill loss — the supply story for a poor week."""

    model_config = ConfigDict(from_attributes=True)

    po_number: str
    po_state: str | None
    issue_date: datetime | None
    total_units_ordered: int | None
    total_grn_quantity: int | None
    total_po_amount: float | None
