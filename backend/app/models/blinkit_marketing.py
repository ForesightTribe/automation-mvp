import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Index, JSON

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class AdPerformanceSummary(SQLModel, table=True):
    __tablename__ = "ad_performance_summary"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    budget_consumed: float = 0.0
    impressions: int = 0
    budget_distribution: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    scraped_at: datetime = Field(default_factory=now_ist)


class AdCampaign(SQLModel, table=True):
    __tablename__ = "ad_campaigns"

    __table_args__ = (Index("idx_ac_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    campaign_id: int
    name: str | None = None
    type: str | None = None
    status: str | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    infinite_campaign: bool = False
    budget_consumed: float = 0.0
    impressions: int = 0
    atcs: int = 0
    roas: float = 0.0
    reach: int = 0
    scraped_at: datetime = Field(default_factory=now_ist)


class SponsoredSOV(SQLModel, table=True):
    __tablename__ = "sponsored_sov"

    __table_args__ = (Index("idx_sov_tenant", "tenant_id", "date"),)

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


class BrandCollection(SQLModel, table=True):
    __tablename__ = "brand_collections"

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


class VisibilityPlan(SQLModel, table=True):
    __tablename__ = "visibility_plans"

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
