"""Instamart Brand Portal (partner.instamart.in) seller tables.

Shaped by what Instamart's Sales report actually gives — and it is a *finer*
grain than either Blinkit or Zepto:

* The daily sales report is one row per **date x store x item**. Instamart
  exposes the individual dark store (its `podId`), which is the same id the
  public search scraper stores as `search_listings.merchant_id`. So Instamart —
  unlike Zepto (city only) or Blinkit (city only) — lets private sales join to
  public price/stock *per store*.
* Alongside it the report carries a brand-metrics sheet, one row per
  **date x city**: impressions, orders, GMV and new-to-brand buyers for the whole
  brand. These are whole-brand-per-city totals, NOT a store split — so they live
  in their own table and are never summed with the store rows (the same rule the
  Zepto tables follow: `zepto_seller_sales` vs `zepto_seller_product_city_daily`).

Both come from ONE downloaded xlsx (portal Reports -> presigned S3), so both are
filled by the same scrape. Bookkeeping columns (tenant_id, platform, upsert_key,
scrape_job_id, scraped_at) match the Blinkit/Zepto tables so re-runs upsert the
same way.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class InstamartSellerStoreDaily(SQLModel, table=True):
    """One row per tenant per **store** per item per day — the report's
    "Sales Report" sheet, its finest grain and the reason to use Instamart's
    report at all.

    `store_id` is Instamart's podId, identical to the public scraper's
    `search_listings.merchant_id`, so this joins to per-store price/stock.
    `item_code` is Instamart's numeric product code; it maps to the public
    `spin_id` by product_name + variant (the text is identical on both sides).

    Never sum this against `InstamartBrandCityDaily` — that table holds the same
    money aggregated to city with extra marketing metrics; adding them
    double-counts, exactly like the Zepto sales-vs-product-city pair.
    """

    __tablename__ = "instamart_seller_store_daily"

    __table_args__ = (
        Index("idx_issd_tenant_date", "tenant_id", "date"),
        Index("idx_issd_store", "tenant_id", "store_id", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    city: str | None = None
    area_name: str | None = None
    # Instamart podId == public search_listings.merchant_id.
    store_id: str

    l1_category: str | None = None
    l2_category: str | None = None
    l3_category: str | None = None
    product_name: str | None = None
    variant: str | None = None
    # Instamart's numeric product code; maps to public spin_id by name+variant.
    item_code: str

    is_combo: bool = False
    combo_item_code: str | None = None
    combo_units_sold: int = 0

    base_mrp: float | None = None
    units_sold: int = 0
    gmv: float = 0.0

    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartBrandCityDaily(SQLModel, table=True):
    """One row per tenant per city per day — the report's "Brand Metrics" sheet.

    Whole-brand marketing figures per city (impressions, orders, GMV, new-to-brand
    buyers). A city can appear with impressions but no sales, so every metric is
    nullable. This is NOT a store split of the sales table — keep them apart.
    """

    __tablename__ = "instamart_brand_city_daily"

    __table_args__ = (Index("idx_ibcd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    city: str

    ntb_buyers: int | None = None
    brand_impressions: int | None = None
    brand_gmv: float | None = None
    brand_orders: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)
