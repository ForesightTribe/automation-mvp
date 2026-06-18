import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Index, JSON
from sqlmodel import Field, SQLModel


class BlinkitSellerSale(SQLModel, table=True):
    __tablename__ = "blinkit_seller_sales"

    __table_args__ = (Index("idx_bss_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    item_id: str
    item_name: str | None = None
    category: str | None = None
    city_id: str
    city_name: str | None = None
    qty_sold: int = 0
    mrp_value: float = 0.0
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitSellerSalesSummary(SQLModel, table=True):
    __tablename__ = "blinkit_seller_sales_summary"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    distinct_skus: int = 0
    distinct_categories: int = 0
    max_sell_item: str | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitPO(SQLModel, table=True):
    __tablename__ = "blinkit_pos"

    __table_args__ = (Index("idx_pos_tenant_po", "tenant_id", "po_number"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    po_number: str
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitPOSnapshot(SQLModel, table=True):
    __tablename__ = "blinkit_po_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    window_start: date
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitSOH(SQLModel, table=True):
    __tablename__ = "blinkit_soh"

    __table_args__ = (Index("idx_soh_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    item_id: str
    item_name: str | None = None
    backend_facility_id: str
    backend_facility_name: str | None = None
    manufacturer_id: str | None = None
    backend_inv_qty: int = 0
    frontend_inv_qty: int = 0
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitScorecardWeekly(SQLModel, table=True):
    __tablename__ = "blinkit_scorecard_weekly"

    __table_args__ = (Index("idx_scw_tenant", "tenant_id", "from_date_ist"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    manufacturer_id: int
    from_date_ist: date
    overall: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    best_category: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    categories: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitScorecardFacility(SQLModel, table=True):
    __tablename__ = "blinkit_scorecard_facilities"

    __table_args__ = (Index("idx_scf_tenant", "tenant_id", "from_date_ist"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    manufacturer_id: int
    from_date_ist: date
    facility_id: str
    facility_name: str | None = None
    city_id: str | None = None
    city_name: str | None = None
    total_po_quantity: int = 0
    total_grn_quantity: int = 0
    fill_rate: float = 0.0
    weighted_fill_rate_percent: float = 0.0
    potential_loss: float = 0.0
    manufacturer_rank: int | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BlinkitScorecardKeySku(SQLModel, table=True):
    __tablename__ = "blinkit_scorecard_key_skus"

    __table_args__ = (Index("idx_scs_tenant", "tenant_id", "from_date_ist"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    manufacturer_id: int
    from_date_ist: date
    item_id: str
    item_name: str | None = None
    upc: str | None = None
    variant_description: str | None = None
    proxy_category: str | None = None
    potential_loss: float = 0.0
    total_gmv: float = 0.0
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
