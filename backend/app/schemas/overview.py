from datetime import datetime

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
    roas: Metric | None = None  # blended = revenue / spend
    ad_spend: Metric | None = None
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


class MonthlyTrendPoint(BaseModel):
    """One month of operations trends for the Overview. Built over a month spine
    (last N months); a metric is None for months with no source data. Percentages
    are 0–100; `po_amount` is rupees."""

    month: str  # "YYYY-MM"
    osa_pct: float | None  # avg on-shelf availability % (SOH frontend stock)
    fill_rate: float | None  # avg weekly fill rate %
    po_amount: float | None  # total PO value (rupees)
    po_count: int | None


class AlertItem(BaseModel):
    """One attention-feed entry. `severity` orders the list; `category` lets the
    UI pick an icon/accent."""

    severity: str  # 'critical' | 'warning' | 'info'
    category: str  # 'scrape' | 'stock' | 'fill' | 'visibility'
    title: str
    detail: str | None = None
