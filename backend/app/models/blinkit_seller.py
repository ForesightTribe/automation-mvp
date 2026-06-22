import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Index, JSON, Text

from app.utils.time import now_ist
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
    scraped_at: datetime = Field(default_factory=now_ist)


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
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitPO(SQLModel, table=True):
    __tablename__ = "blinkit_pos"

    __table_args__ = (Index("idx_pos_tenant_po", "tenant_id", "po_number"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    scraped_at: datetime = Field(default_factory=now_ist)

    # ── PO header (stored as-is from the Blinkit API) ──
    po_number: str
    po_state: str | None = None
    vendor_id: str | None = None
    vendor_name: str | None = None
    manufacturer_id: str | None = None
    manufacturer_name: str | None = None
    facility_id: str | None = None
    facility_name: str | None = None
    city_name: str | None = None
    outlet_id: str | None = None
    po_type_id: str | None = None
    address: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    issue_date: datetime | None = None
    expiry_date: datetime | None = None
    delivery_date: datetime | None = None
    schedule_date: datetime | None = None
    scheduled_on: datetime | None = None
    total_units_ordered: int | None = None
    item_count: int | None = None
    total_grn_quantity: int | None = None
    total_po_amount: float | None = None
    multiple_grn: int | None = None
    load_size: int | None = None
    active: bool | None = None
    download_url: str | None = None
    po_excel_report_url: str | None = None
    grn_report_excel_url: str | None = None
    pm_name: str | None = None
    pm_phone: str | None = None
    pm_email: str | None = None
    entity_vendor_cin: str | None = None
    entity_vendor_legal_name: str | None = None
    delivery_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None


class BlinkitPOItem(SQLModel, table=True):
    __tablename__ = "blinkit_po_items"

    __table_args__ = (Index("idx_po_items_tenant_po", "tenant_id", "po_number"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    scraped_at: datetime = Field(default_factory=now_ist)

    # ── PO line item (stored as-is from the Blinkit API) ──
    po_number: str
    line_id: str | None = None
    item_id: str
    upc: str | None = None
    name: str | None = None
    uom_text: str | None = None
    variant_id: str | None = None
    units_ordered: int | None = None
    remaining_quantity: int | None = None
    cost_price: float | None = None
    landing_rate: float | None = None
    mrp: float | None = None
    margin_percentage: float | None = None
    total_amount: float | None = None
    tax_value: float | None = None
    cgst_value: float | None = None
    sgst_value: float | None = None
    igst_value: float | None = None
    cess_value: float | None = None
    bucket_type: str | None = None
    created_at: datetime | None = None


class BlinkitPOSnapshot(SQLModel, table=True):
    __tablename__ = "blinkit_po_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    window_start: date
    scraped_at: datetime = Field(default_factory=now_ist)

    # ── Windowed PO summary counts (stored as-is from the Blinkit API) ──
    total_raised: int | None = None
    scheduled: int | None = None
    created: int | None = None
    cancelled: int | None = None
    expired_unfulfilled: int | None = None
    expired_partial: int | None = None
    po_amount: float | None = None
    items_delivered: int | None = None


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
    scraped_at: datetime = Field(default_factory=now_ist)


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
    scraped_at: datetime = Field(default_factory=now_ist)


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
    scraped_at: datetime = Field(default_factory=now_ist)


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
    scraped_at: datetime = Field(default_factory=now_ist)
