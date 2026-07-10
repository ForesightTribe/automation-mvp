import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Index, JSON

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class BlinkitAdCampaign(SQLModel, table=True):
    """Campaign catalog + metadata snapshot (from /advertisers/campaigns).

    Pure metadata — the per-day metrics live in BlinkitAdCampaignDaily and the
    keyword/asset breakdown in BlinkitAdCampaignDetail. Upserted to the latest
    snapshot per campaign (keyed on tenant+campaign_id), so status/name changes
    overwrite in place. Used to enumerate campaigns to scrape and to render the
    campaign table."""

    __tablename__ = "blinkit_ad_campaigns"

    __table_args__ = (Index("idx_bac_tenant", "tenant_id"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    campaign_id: int
    name: str | None = None
    type: str | None = None
    status: str | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    infinite_campaign: bool = False
    daily_budget: int | None = None
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitAdCampaignDaily(SQLModel, table=True):
    """Per-campaign, per-day ad metrics (from /campaigns/metrics-trends/{id}).

    The backbone of all ad reporting: account/marketplace totals are sums of
    these rows, and RoAS over any window = Σ ad_sales / Σ budget_consumed
    (recompute the ratio — never average the daily `roas`). One row per
    (campaign, day); upserted on re-scrape of the same day."""

    __tablename__ = "blinkit_ad_campaign_daily"

    __table_args__ = (
        Index("idx_bacd_tenant_date", "tenant_id", "date"),
        Index("idx_bacd_campaign", "tenant_id", "campaign_id", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    campaign_id: int
    campaign_type: str | None = None  # denormalized so daily can be filtered by type
    budget_consumed: float = 0.0
    impressions: int = 0
    atc: int = 0  # total_atc
    quantities_sold: int = 0  # total_quantities_sold
    ad_sales: float = 0.0  # total_sales — ad-attributed revenue
    roas: float = 0.0  # total_roas (daily; recompute for windows)
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitAdCampaignDetail(SQLModel, table=True):
    """Per-campaign keyword / recommendation breakdown for a window (from
    /campaigns/reports/{id}).

    Range-aggregate snapshot (the endpoint isn't daily) keyed by snapshot_date,
    so it holds 'performance over the latest scraped window'. One unified table
    for both campaign shapes via `target_type`: keyword campaigns fill keyword/
    match_type/position; recommendation campaigns set target to the asset_type."""

    __tablename__ = "blinkit_ad_campaign_detail"

    __table_args__ = (Index("idx_bacdet_tenant_campaign", "tenant_id", "campaign_id"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    snapshot_date: date
    campaign_id: int
    campaign_type: str | None = None
    target_type: str  # 'keyword' | 'recommendation'
    target: str  # keyword string OR asset_type
    sub_campaign_id: int | None = None
    match_type: str | None = None
    impressions: int = 0
    budget_consumed: float = 0.0
    cpm: float = 0.0
    direct_atc: int = 0
    indirect_atc: int = 0
    direct_sales: float = 0.0
    indirect_sales: float = 0.0
    direct_quantities_sold: int = 0
    indirect_quantities_sold: int = 0
    new_users_acquired: int = 0
    most_viewed_position: int | None = None
    direct_roas: float = 0.0
    total_roas: float = 0.0
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitSponsoredSOV(SQLModel, table=True):
    __tablename__ = "blinkit_sponsored_sov"

    __table_args__ = (Index("idx_bsov_tenant", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    keyword: str
    monthly_searches: int = 0
    searches: int = 0
    sov: float = 0.0
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitBrandCollection(SQLModel, table=True):
    __tablename__ = "blinkit_brand_collections"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    collection_id: int
    collection_uuid: str | None = None
    name: str | None = None
    number_of_products: int = 0
    is_dynamic: bool = False
    created_by: str | None = None
    created_on: str | None = None
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitVisibilityPlan(SQLModel, table=True):
    __tablename__ = "blinkit_visibility_plans"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    plan_id: int
    name: str | None = None
    type: str | None = None
    budget: float = 0.0
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    scraped_at: datetime = Field(default_factory=now_ist)
