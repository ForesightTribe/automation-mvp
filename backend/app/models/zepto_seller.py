"""Zepto seller dashboard (brands.zepto.co.in) tables.

Shaped by what Zepto's Sales Analytics API actually returns, which is NOT the
same grain as Blinkit's seller data:

* Blinkit gives one row per item × city × day. Zepto gives a **daily total**
  (GMV/units for the whole brand, no item or city split) plus a **separate
  product breakdown aggregated over the requested window**. There is no
  per-city dimension anywhere in the responses we get, so nothing here has a
  city column — a Sales-by-City chart cannot be built from this source.
* The product endpoint returns one aggregate per SKU for the whole
  start→end window, not per day. `period_start`/`period_end` are therefore part
  of that table's grain (and its upsert key): scraping a one-day window gives
  daily rows, a 30-day window gives one 30-day snapshot.

Bookkeeping columns (tenant_id, platform, upsert_key, scrape_job_id,
scraped_at) match the Blinkit tables so both behave the same for re-runs.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class ZeptoSellerSalesDaily(SQLModel, table=True):
    """One row per tenant per calendar day — GMV and units for the brand."""

    __tablename__ = "zepto_seller_sales_daily"

    __table_args__ = (Index("idx_zssd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    brand_id: str
    brand_name: str | None = None

    # Zepto returns GMV already rounded to whole rupees in the daily series.
    gmv: float = 0.0
    units: int = 0

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoSellerProductPerf(SQLModel, table=True):
    """One row per tenant per SKU per scraped window.

    `stock_on_hand` is nullable and has been null for every row observed so far —
    Stock View is gated behind the "Zepto Atom" subscription on this account, so
    the field is returned but never populated. Kept because the API sends it.
    """

    __tablename__ = "zepto_seller_product_perf"

    __table_args__ = (
        Index("idx_zspp_tenant_period", "tenant_id", "period_start", "period_end"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    period_start: date
    period_end: date

    product_variant_id: str
    product_name: str | None = None
    sku_name: str | None = None
    pack_size: str | None = None
    unit_of_measure: str | None = None
    category_name: str | None = None
    subcategory_name: str | None = None

    gmv: float = 0.0
    qty_sold: int = 0
    # Percentages, as returned (e.g. 50.88 means 50.88%).
    sales_contribution: float | None = None
    available_stores: float | None = None
    week_on_week_growth: float | None = None
    month_on_month_growth: float | None = None
    stock_on_hand: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)
