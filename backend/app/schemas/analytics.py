from pydantic import BaseModel
from datetime import date
from typing import Optional


class RevenuePoint(BaseModel):
    date: date
    revenue: float
    units_sold: int


class OverviewStats(BaseModel):
    total_revenue: float
    total_units: int
    total_products: int
    active_campaigns: int
