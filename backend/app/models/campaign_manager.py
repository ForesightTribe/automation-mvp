import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.utils.time import now_ist


class BudgetScheduleDB(SQLModel, table=True):
    __tablename__ = "budget_schedules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", name="uq_budget_schedule_tenant_campaign"),
        Index("idx_bs_tenant", "tenant_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    campaign_id: int
    campaign_name: str
    name: str | None = None
    default_budget: float
    enabled: bool = True
    created_at: datetime = Field(default_factory=now_ist)


class BudgetScheduleRuleDB(SQLModel, table=True):
    __tablename__ = "budget_schedule_rules"
    __table_args__ = (Index("idx_bsr_schedule", "schedule_id"),)

    id: int | None = Field(default=None, primary_key=True)
    schedule_id: int = Field(foreign_key="budget_schedules.id")
    type: str = "recurring"
    days: list = Field(default=[], sa_column=Column(JSON))
    time_slots: list = Field(default=[], sa_column=Column(JSON))
    start_time: str | None = None
    end_time: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None
    budget: float


class BudgetSchedulerLogDB(SQLModel, table=True):
    __tablename__ = "budget_scheduler_log"
    __table_args__ = (Index("idx_bsl_tenant", "tenant_id", "timestamp"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    campaign_id: int | None = None
    campaign_name: str
    budget_applied: float
    rule: str
    success: bool
    timestamp: datetime = Field(default_factory=now_ist)


class BidOptimizerRuleDB(SQLModel, table=True):
    __tablename__ = "bid_optimizer_rules"
    __table_args__ = (Index("idx_bor_tenant", "tenant_id"),)

    id: str = Field(primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
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
    created_at: datetime = Field(default_factory=now_ist)


class CampaignDataCache(SQLModel, table=True):
    """Cached keywords + products per campaign, populated by VM sync job."""
    __tablename__ = "campaign_data_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", name="uq_cdc_tenant_campaign"),
        Index("idx_cdc_tenant", "tenant_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    campaign_id: int
    keywords: list = Field(default=[], sa_column=Column(JSON))
    products: list = Field(default=[], sa_column=Column(JSON))
    synced_at: datetime = Field(default_factory=now_ist)


class BidOptimizerLogDB(SQLModel, table=True):
    __tablename__ = "bid_optimizer_log"
    __table_args__ = (Index("idx_bol_tenant", "tenant_id", "timestamp"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
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
    timestamp: datetime = Field(default_factory=now_ist)
