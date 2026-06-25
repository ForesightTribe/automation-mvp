import uuid
from datetime import date

from pydantic import BaseModel


class Metric(BaseModel):
    """A headline number with its previous-period value and growth. `value`/`prev`
    are None when there's no data (e.g. no public samples); `delta_pct` is None
    when growth can't be computed (no prior value to grow from). Fractions like
    visibility/SOV are passed through as-is (0..1) for the frontend to format."""

    value: float | None
    prev: float | None
    delta_pct: float | None


class AnalyticsOverview(BaseModel):
    client_id: uuid.UUID
    start: date
    end: date
    marketplaces: list[str] | None  # None = all platforms (no filter)
    # Performance plane (private, tenant-scoped, filtered by marketplace/platform)
    revenue: Metric  # total store revenue (seller sales mrp_value)
    organic_revenue: Metric  # total revenue - ad-attributed revenue
    units_sold: Metric
    distinct_skus: Metric
    ad_spend: Metric  # budget_consumed
    ad_sales: Metric  # ad-attributed revenue
    impressions: Metric
    roas: Metric  # ad-attributed = ad_sales / ad_spend
    # Market plane (public, own-brand via watchlist)
    visibility: Metric  # avg brand_sov
    avg_rank: Metric  # avg brand_rank (lower is better)


class RevenuePoint(BaseModel):
    date: date
    revenue: float
    units_sold: int


class TrendPoint(BaseModel):
    """One day on the unified Overview trend. Built over a full date spine, so
    every day in the window is present; a metric is None on days its source has
    no data (honest gaps rather than fake zeros)."""

    date: date
    ad_spend: float | None
    ad_sales: float | None
    impressions: int | None
    revenue: float | None
    units: int | None


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
