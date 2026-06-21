import uuid
from datetime import date

from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    client_id: uuid.UUID
    period_days: int
    revenue: float
    units_sold: int
    distinct_skus: int
    active_campaigns: int
    ad_spend: float
    impressions: int


class RevenuePoint(BaseModel):
    date: date
    revenue: float
    units_sold: int


class TopSku(BaseModel):
    item_id: str
    item_name: str | None
    revenue: float
    units_sold: int


class CityBreakdown(BaseModel):
    city: str
    revenue: float
    units_sold: int


class CategoryBreakdown(BaseModel):
    category: str
    revenue: float
    units_sold: int
