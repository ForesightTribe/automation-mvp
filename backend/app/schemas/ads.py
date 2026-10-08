from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.analytics import Metric


class AdsSummaryMarketplace(BaseModel):
    """One marketplace's share of the KPI strip, current window only — the split under each
    tile. Additive bases only; the UI rebuilds RoAS / ACoS from them. `units_sold` is None
    where the marketplace's figure is not usable (Instamart reports none it can be trusted
    on, see CampaignInsights)."""

    platform: str
    ad_spend: float
    ad_sales: float
    impressions: int
    atc: int
    units_sold: int | None = None
    active_campaigns: int


class AdsSummaryPeriod(BaseModel):
    """The windows the KPI tiles were computed over. `end` is the newest day with ad data,
    which is before `picked_end` when the picker reaches days not scraped yet (today);
    `prev_*` is the same number of days immediately before `start`."""

    start: date
    end: date
    prev_start: date
    prev_end: date
    picked_end: date


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
    by_marketplace: list[AdsSummaryMarketplace] = []
    period: AdsSummaryPeriod | None = None


class CampaignRow(BaseModel):
    """Campaign metadata + its metric rollup over the window.

    `platform` says which marketplace the campaign belongs to. The list merges Blinkit and
    Zepto rows, and their campaign ids are separate namespaces — without it a Zepto row is
    indistinguishable from a Blinkit one, which is how a Zepto campaign could be picked on a
    Blinkit-only write surface."""

    model_config = ConfigDict(from_attributes=True)

    # Blinkit and Zepto both use integer campaign ids; Instamart's are UUID
    # strings ("2d497b84-..."), so this widens rather than coercing — a
    # coercion would silently mangle the id you need to look the campaign
    # back up by.
    campaign_id: int | str
    # Required — no default marketplace (ZC-D1). Every path that builds rows sets it.
    platform: str
    name: str | None
    type: str | None
    # Can automations run on this campaign (ZC-D3)? False with a reason for a Zepto
    # Display or automatic-bidding campaign, so a picker greys it out instead of the save
    # failing. True for anything not catalogued yet — the save-time check allows those too.
    automatable: bool = True
    not_automatable_reason: str | None = None
    # `status` is the marketplace's own word (ACTIVE / ON_HOLD / DAILY_BUDGET_EXHAUSTED …);
    # `state` is what it MEANS, in the vocabulary the engines act on: running / paused /
    # held / ended / draft. UI decisions — offer Start or Stop — must read `state`: the raw
    # words differ per marketplace, and a Zepto campaign out of budget is live (Stop), not
    # stopped (Start). An unmapped status passes through unchanged in both.
    status: str | None
    state: str | None = None
    daily_budget: int | None = None
    budget_consumed: float
    impressions: int
    # Zepto only — it bills per click, so the pickers show Avg CPC from this (ZC-E12).
    # None on Blinkit, which reports no clicks; never 0 there, which would read as "none".
    clicks: int | None = None
    atc: int
    quantities_sold: int
    ad_sales: float
    roas: float


class CampaignDayRow(BaseModel):
    """One campaign's spend on one day — the budget-utilisation views' grain.

    Exactly the fields those views read off a one-day `/ads/campaigns` call, for a whole
    window in ONE request: they used to make one call per day (up to 31, four at a time), and
    every one held a pooled connection (2026-09-25). Only days a campaign SPENT on are
    returned — a day it did not run is absent, which the views read as "did not run".
    `daily_budget` is the campaign's current setting, as on `/ads/campaigns`."""

    date: date
    campaign_id: int | str
    platform: str
    name: str | None
    type: str | None
    budget_consumed: float
    daily_budget: int | None = None
    ad_sales: float


class AdPerformanceSlice(BaseModel):
    """One marketplace's part of a day on the trend."""

    budget_consumed: float
    impressions: int
    ad_sales: float


class AdPerformancePoint(BaseModel):
    """One day on the spend/revenue trend. `roas` is the day's ad_sales / spend
    (0.0 when there was no spend that day). `by_marketplace` splits the day's figures by
    marketplace slug (only marketplaces with a row that day), for the "By marketplace" view."""

    date: date
    budget_consumed: float
    impressions: int
    ad_sales: float
    roas: float
    by_marketplace: dict[str, AdPerformanceSlice] = {}


class BudgetSplitRow(BaseModel):
    """Spend (and recomputed RoAS) for one campaign type of one marketplace over the
    window — powers the budget-split donut and its table. `campaign_type` is the
    marketplace's own word, so it only means something beside `platform`."""

    platform: str
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
    platform: str
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


class CampaignKeywordRow(BaseModel):
    """One keyword (+ match type) of ONE campaign, in the shape every marketplace can fill.
    `position` is Blinkit's most-viewed position (None elsewhere — not reported)."""

    keyword: str
    match_type: str | None = None
    spend: float
    sales: float
    impressions: int
    roas: float | None = None
    position: int | None = None


class CampaignKeywords(BaseModel):
    """A campaign's top keywords by spend, and what period they cover. For Blinkit that is
    its snapshot's 8 days (`snapshot_date − 7 … snapshot_date`), whatever was asked for —
    the UI labels these dates, never the picker's. `total` = keywords in the period (for
    Instamart, the rows returned: its rollup is limited at the query)."""

    platform: str
    period_start: date | None = None
    period_end: date | None = None
    total: int
    items: list[CampaignKeywordRow]


class KeywordPeriod(BaseModel):
    """What one marketplace's keyword rows cover. `snapshot` = a fixed-length total the
    marketplace reports (Blinkit's 8 days to `end`), NOT the requested window — the UI must
    label these dates. start/end None = that marketplace has no report on or before the
    requested end."""

    platform: str
    snapshot: bool
    start: date | None = None
    end: date | None = None


class KeywordInsightRow(BaseModel):
    """One campaign × keyword × match type, in the shape every marketplace can fill. A
    figure the marketplace does not report is None, never 0: Blinkit reports no clicks or
    orders; Zepto no position and no direct/indirect SALES split (it splits ORDERS instead —
    `direct_orders` same SKU, `halo_orders` another of the brand's)."""

    platform: str
    campaign_id: int | str
    keyword: str
    match_type: str | None = None
    spend: float
    sales: float
    impressions: int
    clicks: int | None = None
    atc: int | None = None
    orders: int | None = None
    direct_sales: float | None = None
    indirect_sales: float | None = None
    direct_orders: int | None = None
    halo_orders: int | None = None
    position: int | None = None
    # Blinkit's own reported CPM (it is not spend ÷ impressions); None elsewhere.
    cpm: float | None = None
    snapshot_date: date | None = None


class KeywordInsights(BaseModel):
    periods: list[KeywordPeriod]
    items: list[KeywordInsightRow]


class AdBreakdownRow(BaseModel):
    """One product, retail category or city of one marketplace, summed over the window.
    `key` is stable within its marketplace (the SKU id for a product, else the name);
    `detail` is a product's retail category. `units_sold` is Zepto's orders count."""

    platform: str
    key: str
    name: str
    detail: str | None = None
    image_link: str | None = None
    ad_types: list[str] = []
    spend: float
    sales: float
    impressions: int
    clicks: int | None = None
    units_sold: int | None = None
    atc: int | None = None
    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None
    # Which campaigns the row's total is made of, where the marketplace reports it
    # (Instamart products); empty otherwise.
    campaigns: list[dict] = []


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
