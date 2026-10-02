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
# Two tables: the order-level report (BlinkitSellerHubSalesOrderRO, the source
# for revenue, units, city, category and trends) and the by-product chart
# table, kept only for fields Blinkit computes that the report lacks. The
# day / city-day / category-day chart tables were dropped in migration
# 4b7e2c91d0a3 -- every number they held is a GROUP BY on the order table.


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
    matched the dashboard's own daily chart total for the same month to the
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
