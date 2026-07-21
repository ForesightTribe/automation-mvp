from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.analytics import Metric


class AdsSummary(BaseModel):
    """KPI strip for the Ads page. Each tile is a `Metric` (value + previous-period
    value + growth), computed over the window vs the equal-length prior window.
    RoAS = ad_sales / spend; ACoS = spend / ad_sales (lower is better)."""

    ad_spend: Metric
    ad_sales: Metric
    roas: Metric
    acos: Metric
    impressions: Metric
    atc: Metric
    units_sold: Metric
    active_campaigns: Metric


class CampaignRow(BaseModel):
    """Campaign metadata + its metric rollup over the window."""

    model_config = ConfigDict(from_attributes=True)

    campaign_id: int
    name: str | None
    type: str | None
    status: str | None
    daily_budget: int | None = None
    budget_consumed: float
    impressions: int
    atc: int
    quantities_sold: int
    ad_sales: float
    roas: float


class AdPerformancePoint(BaseModel):
    """One day on the spend/revenue trend. `roas` is the day's ad_sales / spend
    (0.0 when there was no spend that day)."""

    date: date
    budget_consumed: float
    impressions: int
    ad_sales: float
    roas: float


class BudgetSplitRow(BaseModel):
    """Spend (and recomputed RoAS) for one campaign type over the window — powers
    the budget-split donut and the by-type table."""

    campaign_type: str | None
    budget_consumed: float
    ad_sales: float
    roas: float


class KeywordRow(BaseModel):
    """One keyword/asset row from the latest campaign-detail snapshot. `target` is
    the keyword string (keyword campaigns) or the asset type (recommendation
    campaigns); `target_type` says which."""

    model_config = ConfigDict(from_attributes=True)

    campaign_id: int
    campaign_type: str | None
    target_type: str
    target: str
    match_type: str | None
    impressions: int
    budget_consumed: float
    cpm: float
    direct_atc: int
    indirect_atc: int
    direct_sales: float
    indirect_sales: float
    new_users_acquired: int
    most_viewed_position: int | None
    direct_roas: float
    total_roas: float
    snapshot_date: date


class SponsoredSovRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    keyword: str
    monthly_searches: int
    searches: int
    sov: float
    date: date


class VisibilityPlanRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_id: int
    name: str | None
    type: str | None
    budget: float
    start_date: str | None
    end_date: str | None
    status: str | None


class CollectionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collection_id: int
    name: str | None
    number_of_products: int
    is_dynamic: bool


class AdMarketplaceRow(BaseModel):
    """One marketplace's ad slice for the 'Ads by marketplace' breakdown."""

    slug: str
    name: str
    color: str | None
    connected: bool
    ad_spend: Metric | None = None
    ad_sales: Metric | None = None
    roas: Metric | None = None
    impressions: Metric | None = None


# ── Budget scheduling ─────────────────────────────────────────────────────────

class BudgetRule(BaseModel):
    type: Literal["recurring", "once"] = "recurring"
    days: list[str] = []
    time_slots: list[str] = []
    budget: float
    date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class BudgetSchedule(BaseModel):
    campaign_id: int
    campaign_name: str
    name: str | None = None
    default_budget: float
    rules: list[BudgetRule] = []
    enabled: bool = True


class SchedulerLogEntry(BaseModel):
    timestamp: str
    campaign_id: int | None = None
    campaign_name: str
    schedule_name: str | None = None
    budget_applied: float
    rule: str
    success: bool


class SchedulerTriggerResponse(BaseModel):
    message: str


# ── Campaign products ─────────────────────────────────────────────────────────

class CampaignProduct(BaseModel):
    pid: str
    name: str
    brand: str


# ── Campaign keywords ─────────────────────────────────────────────────────────

class CampaignKeyword(BaseModel):
    keyword: str
    match_type: str
    current_cpm: int
    position: float | None = None
    impressions: int = 0


# ── Bid Optimizer ────────────────────────────────────────────────────────────

class BidOptimizerRule(BaseModel):
    id: str | None = None
    campaign_id: int
    campaign_name: str
    keyword: str
    match_type: str = "EXACT"
    target_position: int
    min_bid: int
    max_bid: int
    start_time: str | None = None
    stop_time: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    active: bool = True
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    brand_name: str | None = None
    last_cpm: int | None = None
    last_position: float | None = None
    last_bid_updated_at: str | None = None


class BidOptimizerLogEntry(BaseModel):
    timestamp: str
    campaign_id: int | None = None
    campaign_name: str
    keyword: str | None = None
    action: str
    old_cpm: int | None = None
    new_cpm: int | None = None
    position: float | None = None
    target_position: int | None = None
    impressions: int | None = None
    detail: str | None = None
    success: bool


# ── Blinkit reconnect ─────────────────────────────────────────────────────────

class ReconnectBlinkitRequest(BaseModel):
    magic_link: str


class ReconnectBlinkitResponse(BaseModel):
    message: str


class SetBudgetRequest(BaseModel):
    budget: float


class SetBudgetResponse(BaseModel):
    message: str
