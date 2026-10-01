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
# NOT reused from blinkit_seller.py's BlinkitSellerSale/BlinkitSellerSalesSummary:
# the new dashboard's sales API cannot produce that table's grain (item x city x
# day on one row) — one endpoint gives a day total with every item summed
# together, the other gives an item total for a rolling window with no real day
# attached, and neither ever carries a city. Confirmed against the live API,
# not assumed from field names — see docs/platform-auth.md's note on
# blinkit_seller_new for the auth side of this split.


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
