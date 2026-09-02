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
    # ⚠️ Blinkit's campaign LIST carries no budget field at all, so this stayed NULL for
    # every live campaign until V7 — it is populated from the per-campaign DETAIL call the
    # scrape now makes.
    daily_budget: int | None = None

    # ── From the per-campaign detail call (V7) ────────────────────────────────
    # Campaign-grain facts the campaign manager enforces against. They live here rather
    # than in a cm_* table because the SCRAPER writes them: a second CM-owned copy would
    # drift from this one, the same reasoning that put `repo.upsert_campaign_catalog`'s
    # writes into this table.
    region_type: str | None = None                  # PAN_INDIA | CITY
    # Blinkit's `region_ids` resolved to names at scrape time, [{"id": 1, "name": "Delhi"}]
    # — resolving here is what removes any need for a city-directory table.
    cities: list | None = Field(default=None, sa_column=Column(JSON))
    # ── Budget facts ─────────────────────────────────────────────────────────
    # Blinkit publishes NO minimum-budget field; its dashboard derives one in the browser
    # from these plus the campaign type. We store the ingredients and let Blinkit reject a
    # too-low budget at write time (2026-08-27 — deliberately not enforcing it locally).
    # ⚠️ `min_cpm` is `min_cpm_config[campaign_type]`, which despite its name is a BUDGET
    # input and never a bid floor — the bid floor is per keyword, on the table below, and
    # Blinkit publishes THAT one directly.
    min_cpm: int | None = None
    pacing_type: str | None = None                  # DAILY | NONPACED
    # Spend to date. A NONPACED campaign's budget must EXCEED it, and it raises the floor
    # for several campaign types.
    billed_amount: float | None = None
    # The campaign-level CPM — the bid for reach-type assets; 0 on keyword campaigns.
    campaign_cpm: int | None = None
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitAdCampaignKeyword(SQLModel, table=True):
    """A campaign's configured keywords and the bid range Blinkit publishes for each
    (from /campaigns/keywords/attributes — V7).

    One row per (campaign, keyword, match_type), which is exactly the engine's write key
    (`adapter.apply_bid(campaign, keyword, cpm, match_type)`).

    **Current state, not a time series** — upserted in place like the campaign catalogue,
    NOT appended per day. Deliberately not extra columns on BlinkitAdCampaignDetail: that
    table is a per-day snapshot of PERFORMANCE and only holds keywords that had report
    data, so a keyword with no impressions would have no floor — precisely the keyword a
    bid rule is about to start bidding on.

    `min_bid` here is Blinkit's floor, and it genuinely varies per keyword (₹100 on 'soda',
    ₹200 on 'protein chips'). `suggested_*` is stored but not surfaced yet, so using
    suggested bids later needs no backfill."""

    __tablename__ = "blinkit_ad_campaign_keywords"

    __table_args__ = (
        Index("idx_backw_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    campaign_id: int
    campaign_type: str | None = None
    keyword: str
    match_type: str                                 # EXACT | SMART (Blinkit's bid_range key)
    # The campaign's live bid for this keyword+match type; None when the campaign does not
    # currently bid that match type (the range is published either way).
    current_cpm: int | None = None
    min_bid: int | None = None
    max_bid: int | None = None
    suggested_min: int | None = None
    suggested_max: int | None = None
    min_for_boost: int | None = None
    keyword_searches: int | None = None
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
