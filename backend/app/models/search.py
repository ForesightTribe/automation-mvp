import uuid
from datetime import datetime, date
from typing import Any

from sqlalchemy import Column, Index, JSON, Numeric

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class SearchResult(SQLModel, table=True):
    __tablename__ = "search_results"

    __table_args__ = (
        Index("idx_sr_brand_mp", "brand_slug", "mp_slug"),
        Index("idx_sr_city", "brand_slug", "city"),
        Index("idx_sr_zone", "brand_slug", "city", "zone"),
        Index("idx_sr_scraped", "scraped_at"),
        Index("idx_sr_keyword", "brand_slug", "keyword", "city"),
    )

    id: int | None = Field(default=None, primary_key=True)
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    city: str = "bengaluru"
    zone: str = ""
    pincode: str = ""
    keyword: str
    merchant_id: str = ""
    store_type: str = ""
    scraped_at: datetime = Field(default_factory=now_ist)
    brand_rank: int | None = None
    brand_sov: float | None = None
    total_results: int | None = None
    products: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    competitors: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class CompetitorRanking(SQLModel, table=True):
    __tablename__ = "competitor_rankings"

    __table_args__ = (
        Index("idx_cr_brand", "brand_slug", "city", "keyword"),
        Index("idx_cr_competitor", "competitor", "city", "mp_slug"),
    )

    id: int | None = Field(default=None, primary_key=True)
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    city: str
    zone: str = ""
    pincode: str = ""
    keyword: str
    scraped_at: datetime = Field(default_factory=now_ist)
    competitor: str
    position: int | None = None
    price: float | None = None


class BrandSnapshot(SQLModel, table=True):
    __tablename__ = "brand_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    date: date
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class ScrapedProduct(SQLModel, table=True):
    __tablename__ = "scraped_products"

    id: int | None = Field(default=None, primary_key=True)
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    scraped_at: datetime = Field(default_factory=now_ist)
    name: str | None = None
    sku: str | None = None
    price: float | None = None
    position: int | None = None
    keyword: str | None = None
    in_stock: bool = True


class InventoryDepth(SQLModel, table=True):
    __tablename__ = "inventory_depth"

    __table_args__ = (
        Index("idx_inv_brand_sku", "brand_slug", "sku", "mp_slug", "city"),
        Index("idx_inv_time", "brand_slug", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    city: str
    zone: str = ""
    pincode: str = ""
    sku: str
    product_name: str | None = None
    scraped_at: datetime = Field(default_factory=now_ist)
    depth: int | None = None
    max_allowed: int | None = None
    in_stock: bool = True
    stock_msg: str | None = None
    method: str = "api"
    price: float | None = None
    platform_product_id: str | None = None
