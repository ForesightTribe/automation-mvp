from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.analytics import Metric


class MarketplaceRow(BaseModel):
    """One marketplace's slice of the overview. Metrics are None for marketplaces
    without real data yet (`connected=False`) — the UI renders those as a
    'Not connected' card. Connected rows carry visibility/avg_rank always, plus
    revenue/roas/ad_spend/units_sold only when `data_scope == "full"` (a
    marketplace whose scrape is public-data-only, like Zepto today, has no
    order/ads feed to compute those from — they stay None, not zero)."""

    slug: str
    name: str
    color: str | None
    connected: bool
    data_scope: str = "public"
    revenue: Metric | None = None
    roas: Metric | None = None  # ad_sales / ad_spend, same basis as the Overview
    ad_spend: Metric | None = None
    ad_sales: Metric | None = None
    organic_revenue: Metric | None = None  # revenue - ad_sales
    units_sold: Metric | None = None
    visibility: Metric | None = None  # avg brand_sov
    avg_rank: Metric | None = None  # avg brand_rank (lower is better)


class FreshnessChip(BaseModel):
    """Last scrape per dashboard — drives the 'synced Xh ago' chips."""

    dashboard: str
    platform: str
    status: str
    last_synced_at: datetime | None
    age_hours: float | None


class MarketplaceTrendPoint(BaseModel):
    """One day of one marketplace's revenue. `revenue` is None on a day with no
    row, so a gap draws as a gap rather than a fall to zero."""

    date: date
    revenue: float | None = None


class MarketplaceTrend(BaseModel):
    """One marketplace's daily revenue series, with the colour it is drawn in."""

    slug: str
    name: str
    color: str | None = None
    points: list[MarketplaceTrendPoint]






class SupplyItem(BaseModel):
    """One SKU's near-term supply position. `days_cover` is stock divided by
    trailing velocity — an operational indicator, not a forecast."""

    item_id: str
    item_name: str | None = None
    frontend_qty: int
    backend_qty: int
    facilities: int
    facilities_empty: int
    daily_velocity: float | None = None
    days_cover: float | None = None
    incoming_qty: int = 0
    incoming_on: str | None = None
    days_cover_after_po: float | None = None
    state: str


class SupplyOutlook(BaseModel):
    as_of: str | None = None
    velocity_days: int = 28
    low_cover_days: float = 3.0
    items: list[SupplyItem] = []
