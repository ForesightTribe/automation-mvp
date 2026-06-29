from datetime import date

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
    """One marketplace's ad slice for the 'Ads by marketplace' breakdown. Metrics
    are None for marketplaces without ad data yet (`connected=False`) so the UI can
    render a 'Not connected' card without faking numbers."""

    slug: str
    name: str
    color: str | None
    connected: bool
    ad_spend: Metric | None = None
    ad_sales: Metric | None = None
    roas: Metric | None = None
    impressions: Metric | None = None
