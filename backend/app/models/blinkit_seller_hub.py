import uuid
from datetime import datetime, date

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel

# Data from Blinkit's NEW seller dashboard (seller.blinkit.com/seller-hub), as
# opposed to app/models/blinkit_seller.py which is the OLD partnersbiz.com
# dashboard. Named after the real API path (seller-hub), not any one tenant's
# brand — so the next brand Blinkit migrates lands in these same tables,
# scoped by tenant_id, with no rename needed.
#
# NOT reused from blinkit_seller.py's BlinkitSellerSale/BlinkitSellerSalesSummary
# for the chart-backed tables below (Daily/CityDaily/CategoryDaily/ByProduct):
# those four come from the dashboard's own CHART endpoints, which never put
# item + city + day on one row. CORRECTED 2026-10-01: that grain DOES exist on
# this domain after all — see BlinkitSellerHubSalesOrderRO below, from the
# separate "Download sales sheet" REPORT export (reports/download, a different
# endpoint family entirely), which is genuine order-level data: item, real
# date, AND both supply/customer city on one row. Verified live: its total
# matched BlinkitSellerHubSalesDailyRO's total for the same range to the rupee
# (Rs 3,36,604, September 2026).


class BlinkitSellerHubSalesDailyRO(SQLModel, table=True):
    """Day-grain, ALL PRODUCTS COMBINED — seller-hub/api/sales/performance/metrics.

    One row = total sales across every item for one calendar day. There is no
    item on this row and never will be; the endpoint does not return one.
    """
    __tablename__ = "blinkit_seller_hub_sales_daily_ro"

    __table_args__ = (Index("idx_bshsd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    date: date
    sales_amount: float = 0.0
    units_sold: int = 0
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitSellerHubSalesCityDailyRO(SQLModel, table=True):
    """Day-grain, PER CITY — same endpoint as the plain daily table
    (seller-hub/api/sales/performance/metrics), called once per city with
    `filters.city_filter: [<city>]`.

    The response carries no city field of its own — verified live (Sereko,
    2026-10-01): filtering to "Bengaluru" dropped the day totals from
    Rs 1,17,568/264u (all cities) to Rs 24,339/57u, and the 7-day histogram
    summed back to that same filtered total. So each row here is tagged with
    whichever city was REQUESTED, same pattern as Zepto's per-city scrape —
    not a field Blinkit returns itself.

    Real calendar date, one city's total per day — safe to sum across any
    date range or across cities, unlike the rolling-window by-product table.
    """
    __tablename__ = "blinkit_seller_hub_sales_city_daily_ro"

    __table_args__ = (
        Index("idx_bshscd_tenant_date", "tenant_id", "date"),
        Index("idx_bshscd_tenant_city", "tenant_id", "city"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    city: str
    date: date
    sales_amount: float = 0.0
    units_sold: int = 0
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitSellerHubSalesCategoryDailyRO(SQLModel, table=True):
    """Day-grain, PER BUSINESS CATEGORY — same endpoint as the plain daily
    table, called once per category with `filters.business_category_filter:
    [<category_id>]`.

    Verified live (Sereko, 2026-10-01): filtering to category_id 4766
    ("Beauty - Face Care") dropped the day totals from Rs 1,17,568/264u (all
    categories) to Rs 1,14,968/259u, matching the by-product table's own
    category breakdown for the same category exactly — two independent
    sources agreeing. Only 3 categories for Sereko (vs 29 cities), so this
    scrape has none of the rate-limit handling the city table's scraper
    needed.

    Real calendar date, one category's total per day — safe to sum across any
    date range, unlike the rolling-window by-product table's category field.
    """
    __tablename__ = "blinkit_seller_hub_sales_category_daily_ro"

    __table_args__ = (
        Index("idx_bshscatd_tenant_date", "tenant_id", "date"),
        Index("idx_bshscatd_tenant_category", "tenant_id", "category"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    category: str
    date: date
    sales_amount: float = 0.0
    units_sold: int = 0
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitSellerHubSalesByProductRO(SQLModel, table=True):
    """Item-grain, ROLLING WINDOW total — seller-hub/api/sales/products/performance.

    One row = one item's total over whatever window was selected ("Last 7
    days", "Current Month", ...) at the time of the scrape. There is no real
    calendar date on this row — `as_of_date` is the day it was CHECKED, not a
    day the sales happened on, and is part of the key so a daily rescrape
    APPENDS a new snapshot rather than overwriting the previous one (the only
    way to ever see a trend out of a rolling-window number).
    """
    __tablename__ = "blinkit_seller_hub_sales_by_product_ro"

    __table_args__ = (
        Index("idx_bshsbp_tenant_item", "tenant_id", "item_id"),
        Index("idx_bshsbp_tenant_asof", "tenant_id", "as_of_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    window_label: str
    as_of_date: date
    product_id: str | None = None
    item_id: str
    upc: str | None = None
    product_name: str | None = None
    unit: str | None = None
    business_category_name: str | None = None
    units_sold: int = 0
    sales_amount: float = 0.0
    sales_contribution_pct: float | None = None
    is_transitioned: bool | None = None
    transition_date: str | None = None
    scraped_at: datetime = Field(default_factory=now_ist)


class BlinkitSellerHubSalesOrderRO(SQLModel, table=True):
    """Order-level grain — seller-hub/api/reports/download (report_type
    SALES_SUMMARY), a DIFFERENT endpoint family from the chart-backed tables
    above: POST to start generating, poll reports/poll until SUCCESS, GET the
    resulting presigned S3 link for the real XLSX. One row per (order_id,
    item_id) pair — an order with 2 different items is 2 rows.

    This is the real item x city x day grain the chart endpoints can't give —
    discovered 2026-10-01 after wrongly concluding twice that it didn't exist
    on this domain at all. Verified live: its total for September 2026
    matched BlinkitSellerHubSalesDailyRO's total for the same month to the
    rupee (Rs 3,36,604), confirming it's the same real sales, not a different
    number needing reconciliation.

    Kept at full order grain rather than pre-aggregated to item x city x day —
    aggregation is a query away from here and never recoverable the other
    direction, and `order_id` is itself useful (e.g. matching a customer
    complaint to the exact sale).
    """
    __tablename__ = "blinkit_seller_hub_sales_order_ro"

    __table_args__ = (
        Index("idx_bshso_tenant_date", "tenant_id", "order_date"),
        Index("idx_bshso_tenant_item", "tenant_id", "item_id"),
        Index("idx_bshso_tenant_city", "tenant_id", "supply_city"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    order_id: str
    order_date: date
    item_id: str
    product_name: str | None = None
    brand_name: str | None = None
    upc: str | None = None
    variant_description: str | None = None
    consumer_app_mapping: str | None = None
    business_category: str | None = None
    expansion_level: str | None = None
    supply_city: str | None = None
    supply_state: str | None = None
    supply_state_gst: str | None = None
    customer_city: str | None = None
    customer_state: str | None = None
    order_status: str | None = None
    hsn_code: str | None = None
    igst_pct: float | None = None
    cgst_pct: float | None = None
    sgst_pct: float | None = None
    cess_pct: float | None = None
    quantity: int = 0
    mrp: float = 0.0
    selling_price: float = 0.0
    igst_value: float = 0.0
    cgst_value: float = 0.0
    sgst_value: float = 0.0
    cess_value: float = 0.0
    total_tax: float = 0.0
    total_gross_amount: float = 0.0
    scraped_at: datetime = Field(default_factory=now_ist)
