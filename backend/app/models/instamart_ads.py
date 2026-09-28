"""Instamart Brand Portal (partner.instamart.in) ads tables.

`/api/v1/campaigns` (the same signed data host and session as the seller sales
report — see `scraper/platforms/instamart/dashboard_data/seller/session.py`)
returns campaign identity and metrics together, one call, LIFETIME-to-date —
not a daily backbone like Blinkit's or Zepto's. The response's only per-day
dimension carries a single uptime-efficiency metric, nothing resembling a daily
GMV/spend/impressions series. So there is no `InstamartAdCampaignDaily`: one
row per campaign, replaced whole on every scrape, is what the source actually
gives. Do not build a window-over-window comparison on this table — there is
no "previous period" to compare against, only "as of the last scrape".
"""
import uuid
from datetime import date as date_, datetime

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class InstamartAdCampaign(SQLModel, table=True):
    """One row per campaign, upserted on every scrape (lifetime totals, not a
    window). `campaign_id` is Instamart's own UUID string — unlike Blinkit's
    and Zepto's integer ids, so it is never cast to int anywhere downstream.
    """

    __tablename__ = "instamart_ad_campaigns"

    __table_args__ = (
        Index("idx_iac_tenant", "tenant_id", "campaign_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    campaign_id: str
    name: str | None = None
    status: str | None = None
    campaign_type: str | None = None
    placements: str | None = None          # comma-joined; a filter list, not a metric
    start_time: datetime | None = None
    end_time: datetime | None = None

    budget_type: str | None = None
    daily_budget: float | None = None      # None when the campaign has no daily cap

    spend: float = 0.0                     # METRIC_TYPE_BUDGET_BURNT
    gmv: float = 0.0                       # METRIC_TYPE_GMV
    impressions: int = 0
    clicks: int = 0
    ctr: float | None = None
    add_to_cart_count: int = 0
    conversions: int = 0
    conversion_rate: float | None = None
    roi: float | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartAdAccountDaily(SQLModel, table=True):
    """One row per tenant per DAY — account-wide ad totals (not per-campaign),
    from `POST /api/v1/advertiser/metrics/batch` with `dimensions:
    ["DIMENSION_TYPE_DAY"]`. This is the endpoint the portal's own trend chart
    uses, and unlike `/api/v1/campaigns` its `spend` genuinely reflects the
    requested day (verified: 8 days summed here matched the portal's windowed
    dashboard exactly on GMV, impressions AND spend — the campaigns-list
    endpoint's spend does not, it is always lifetime regardless of filter).

    This table is what makes Instamart's KPI-strip growth and the daily
    trend chart real: unlike `InstamartAdCampaign`, there IS a genuine
    previous-period to compare against here.
    """

    __tablename__ = "instamart_ad_account_daily"

    __table_args__ = (
        Index("idx_iaad_tenant_date", "tenant_id", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date_
    spend: float = 0.0
    gmv: float = 0.0
    impressions: int = 0
    clicks: int = 0
    ctr: float | None = None
    add_to_cart_count: int = 0
    conversions: int = 0
    conversion_rate: float | None = None
    roi: float | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartAdProductDaily(SQLModel, table=True):
    """One row per DAY per advertised product (`DIMENSION_TYPE_AD_CANDIDATE`),
    account-wide — not scoped to one campaign, same as Zepto's product table.
    `candidate_id` is the same public product id `sku_snapshots.platform_product_id`
    already carries (verified: AEYU74I37R here is the same AEYU74I37R the public
    scraper stores for Artisanal Sourdough Bread), so name/pack are resolved by
    joining that table rather than a separate catalogue fetch.
    """

    __tablename__ = "instamart_ad_product_daily"

    __table_args__ = (
        Index("idx_iapd_tenant_date", "tenant_id", "date"),
        Index("idx_iapd_candidate", "tenant_id", "candidate_id", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date_
    candidate_id: str
    # None = the unfiltered "All types" row (the proven-correct total).
    # A real value ("ITEM", "BANNER", ...) is an ADDITIVE breakdown scraped
    # separately via the ad-type filter, not a recomputation of the total —
    # see asset_metrics.py's CAMPAIGN_TYPES comment for why they can't be
    # fetched together in one call.
    campaign_type: str | None = None
    # Only populated on campaign_type rows (the by-type breakdown adds
    # DIMENSION_TYPE_CAMPAIGN alongside the type filter — verified live that
    # all three dimensions return together). None on the unfiltered "All
    # types" rows, which never carry this dimension. When a product is
    # advertised by more than one campaign of the same type on the same day,
    # each campaign gets its OWN row (this is what makes that possible —
    # without it, two campaigns' rows would collide on the same upsert key
    # and only the last-saved one would survive).
    campaign_id: str | None = None
    spend: float = 0.0
    gmv: float = 0.0
    impressions: int = 0
    clicks: int = 0
    add_to_cart_count: int = 0

    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartAdKeywordDaily(SQLModel, table=True):
    """One row per DAY per keyword (`DIMENSION_TYPE_KEYWORD`), account-wide —
    like Zepto's keyword table, this carries no campaign id on the unfiltered
    rows: the same keyword can be bid by more than one campaign, and the
    query sums across them. The by-type breakdown (campaign_type set) DOES
    carry one, same as InstamartAdProductDaily.campaign_id.
    """

    __tablename__ = "instamart_ad_keyword_daily"

    __table_args__ = (
        Index("idx_iakd_tenant_date", "tenant_id", "date"),
        Index("idx_iakd_keyword", "tenant_id", "keyword", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date_
    keyword: str
    # Same meaning as InstamartAdProductDaily.campaign_type / .campaign_id.
    campaign_type: str | None = None
    campaign_id: str | None = None
    spend: float = 0.0
    gmv: float = 0.0
    impressions: int = 0
    clicks: int = 0
    add_to_cart_count: int = 0

    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartProductCatalog(SQLModel, table=True):
    """Product name + image, from `POST /api/v1/products/batch` keyed by
    `candidate_id` (the same id `instamart_ad_product_daily.candidate_id` and
    `sku_snapshots.platform_product_id` both carry). Static catalogue data,
    not a daily fact -- one row per product, overwritten on each scrape
    rather than accumulated, the same shape as `instamart_ad_campaigns`.

    `image_url` is a FULL url: the API returns only a relative catalogue
    path (e.g. "NI_CATALOG/IMAGES/ciw/2025/12/17/...png"); the CDN prefix
    `https://media-assets.swiggy.com/swiggy/image/upload/` was verified live
    (200 OK, valid image) and is applied at scrape time so nothing downstream
    needs to know the prefix.
    """

    __tablename__ = "instamart_product_catalog"

    __table_args__ = (
        Index("idx_ipc_tenant_candidate", "tenant_id", "candidate_id", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    candidate_id: str
    product_name: str | None = None
    image_url: str | None = None
    scraped_at: datetime = Field(default_factory=now_ist)
