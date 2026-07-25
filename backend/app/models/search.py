import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON, UniqueConstraint

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class SearchSnapshot(SQLModel, table=True):
    """Per-search header: one row per (tenant, marketplace, brand, keyword,
    location, scrape). Pre-aggregated rank/SoV for cheap trend queries; the
    per-product detail lives in `search_listings`."""

    __tablename__ = "search_snapshots"

    __table_args__ = (
        Index("idx_snap_tenant_kw", "tenant_id", "mp_slug", "keyword", "scraped_at"),
        Index("idx_snap_tenant_brand", "tenant_id", "brand_slug", "scraped_at"),
        Index("idx_snap_scraped", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    brand_slug: str = Field(foreign_key="brands.slug")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    keyword: str
    city: str = ""
    zone: str = ""
    pincode: str = ""
    lat: float | None = None
    lon: float | None = None
    # The EXPRESS store serving this coordinate — the location's identity, read back
    # off the response (not the config). "" when no express product was returned.
    # This row stays LOCATION-grain on purpose: rank/SoV are the blended list the
    # shopper sees across every tier, so re-keying them to a store would invent a
    # ranking nobody saw. Store grain lives on sku_snapshots. See docs/darkstores.md.
    merchant_id: str = ""
    scraped_at: datetime = Field(default_factory=now_ist)
    brand_rank: int | None = None
    brand_sov: float | None = None
    total_results: int | None = None


class SearchListing(SQLModel, table=True):
    """Per-product detail for a search: one row per stored product in the result
    page (own brand + named competitors; the unnamed tail is only counted in the
    snapshot's `total_results`). Carries competitor identity, discounts and stock.
    `mrp`/`discount_pct` are provisioned but stay NULL until the scraper captures
    MRP."""

    __tablename__ = "search_listings"

    __table_args__ = (
        Index("idx_listing_tenant_kw", "tenant_id", "mp_slug", "keyword", "scraped_at"),
        Index("idx_listing_snapshot", "snapshot_id"),
        Index("idx_listing_tenant_brand", "tenant_id", "brand_slug", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="search_snapshots.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    brand_slug: str | None = Field(default=None, foreign_key="brands.slug")
    keyword: str
    city: str = ""
    zone: str = ""
    pincode: str = ""
    scraped_at: datetime = Field(default_factory=now_ist)
    position: int | None = None
    product_name: str
    is_brand: bool = False
    price: float | None = None
    mrp: float | None = None
    discount_pct: float | None = None
    # Pack size, parsed from Blinkit's `unit` string (also kept raw in `extra.unit`).
    # `pack_raw` is the source verbatim; `pack_size`+`pack_uom` are the total content
    # normalized to one base unit ("1.2 ltr" and "1200 ml" → 1200.0/"ml"); `pack_count`
    # is the number of physical items. Per-unit price is DERIVED (price ÷ pack_size),
    # never stored. NULL size/"" uom = unparseable or a heterogeneous combo (no single
    # denominator). See scraper/utils/pack.py + docs/per-unit-price.md.
    pack_raw: str = ""
    pack_size: float | None = None
    pack_uom: str = ""
    pack_count: int | None = None
    in_stock: bool = True
    inventory: int | None = None
    platform_product_id: str | None = None
    # The dark store that fulfils THIS product and the tier it is served under —
    # both read per-product off the atc block. One response routinely spans several
    # stores and tiers, so these are per-row, never per-snapshot. `merchant_type` is
    # a property of the product's fulfilment tier, NOT of the store: the same store
    # can serve express to its own catchment and longtail to a neighbour, and can
    # serve two tiers at once. Never derive it from a store lookup.
    # Values: express | longtail | super_longtail | dummy ("" = pre-backfill unknown).
    # See docs/darkstores.md.
    merchant_id: str = ""
    merchant_type: str = ""
    # Combo/multipack vs singular SKU (own or competitor). Combos are stocked
    # selectively and priced higher, so price comparisons filter to singles.
    is_combo: bool = False
    extra: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class SkuSnapshot(SQLModel, table=True):
    """Targeted own-SKU probe: one row per (product × store × scrape), keyed on
    `platform_product_id` (the stable identity — names drift, ids don't). Fed by
    the brand-query scrape, which searches a tenant's brand name and paginates the
    whole catalog, so every own SKU is captured regardless of whether it surfaces
    in a category-keyword search. Append-only; group/query by `platform_product_id`.
    """

    __tablename__ = "sku_snapshots"

    __table_args__ = (
        Index("idx_sku_tenant_product", "tenant_id", "platform_product_id", "scraped_at"),
        Index("idx_sku_tenant_store", "tenant_id", "merchant_id", "scraped_at"),
        Index("idx_sku_scraped", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    brand_slug: str = Field(foreign_key="brands.slug")
    platform_product_id: str = ""
    product_name: str = ""          # denormalized display label; not the identity
    # The dark store fulfilling this product, and its tier — both per-product, off
    # the atc block. This is the store-grain fact table: group by `merchant_id` for
    # per-store inventory, and ALWAYS segment denominators by `merchant_type` (~2059
    # express stores vs ~510 shared hubs — mixing them is meaningless).
    # "" tier = pre-backfill or an ambiguous (product, store) pair.
    merchant_id: str = ""
    merchant_type: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None
    scraped_at: datetime = Field(default_factory=now_ist)
    price: float | None = None
    mrp: float | None = None
    discount_pct: float | None = None
    # Pack size parsed from Blinkit's `unit` string — see SearchListing for the field
    # semantics. Per-unit price is derived (price ÷ pack_size), never stored.
    pack_raw: str = ""
    pack_size: float | None = None
    pack_uom: str = ""
    pack_count: int | None = None
    in_stock: bool = True
    inventory: int | None = None
    rating: float | None = None
    # Combo/multipack vs singular main SKU — combos are stocked selectively, so the
    # availability views separate them (default view = main SKUs only).
    is_combo: bool = False


class MarketplaceLocation(SQLModel, table=True):
    """Shared serviceability reference — one row per **express** dark store, with the
    coordinate to probe it at. Objective (not tenant-specific); tenants pick which of
    these to track via `tenant_locations`.

    `lat`/`lon` is the **probe point** — the coordinate the scraper actually targets.
    `merchant_id` is the express store that coordinate resolves to; it is NOT a scrape
    input (we send lat/lon and read the merchant back off each product). It serves
    three jobs: the row's natural key, the label source for the UI, and a validation
    assertion — a scrape returning a different express id means the store moved,
    closed, or opened.

    Non-express stores (longtail / super_longtail hubs) are deliberately absent: they
    are shared across catchments, they are discovered from scrape responses, and no
    catalog can enumerate them. See docs/darkstores.md.
    """

    __tablename__ = "marketplace_locations"

    __table_args__ = (
        UniqueConstraint("mp_slug", "merchant_id", name="uq_mploc_mp_merchant"),
        Index("idx_mploc_mp_city", "mp_slug", "city"),
    )

    id: int | None = Field(default=None, primary_key=True)
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    # The express dark store's platform id — the natural key. See class docstring.
    merchant_id: str = ""
    city: str = ""
    state: str = ""
    region: str = ""
    pincode: str = ""
    # Human labels straight from the darkstore catalog — `location_name` is the
    # sub-city area ("Shahganj"), `address` the full street address.
    location_name: str = ""
    address: str = ""
    lat: float | None = None
    lon: float | None = None
    is_active: bool = True


class SkuMap(SQLModel, table=True):
    """Bridges private seller data (`item_id`) to public scrape data
    (`platform_product_id`) — the two Blinkit id systems share no key, so this is
    built by normalized name matching (auto) with manual confirmation for the rest.
    `platform_product_id` is NULL until matched. One row per (tenant, item_id).
    """

    __tablename__ = "sku_map"

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", name="uq_skumap_tenant_item"),
        Index("idx_skumap_tenant_pid", "tenant_id", "platform_product_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    item_id: str                                   # private seller id
    platform_product_id: str | None = None         # public id (NULL until matched)
    item_name: str = ""                            # private name (reference)
    product_name: str = ""                         # public name (reference)
    unit: str = ""
    match_method: str = ""                         # 'auto' | 'manual' | '' (unmatched)
    confidence: float | None = None
    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class TenantLocation(SQLModel, table=True):
    """Per-tenant location selection: which `marketplace_locations` a client
    tracks, per marketplace. Drives the orchestrator's scrape set together with
    the watchlist's keywords."""

    __tablename__ = "tenant_locations"

    __table_args__ = (
        UniqueConstraint("tenant_id", "location_id", name="uq_tenant_location"),
        Index("idx_tenloc_tenant_mp", "tenant_id", "mp_slug"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    mp_slug: str = Field(foreign_key="marketplaces.slug")
    location_id: int = Field(foreign_key="marketplace_locations.id")
    created_at: datetime = Field(default_factory=now_ist)


class InventoryDepth(SQLModel, table=True):
    """Deep per-SKU stock probe (max-quantity-in-cart trick). Distinct from the
    coarse in/out-of-stock on `search_listings`; its write path lands in a later
    phase. `tenant_id`/`job_id` provisioned for the per-tenant rewrite."""

    __tablename__ = "inventory_depth"

    __table_args__ = (
        Index("idx_inv_brand_sku", "brand_slug", "sku", "mp_slug", "city"),
        Index("idx_inv_time", "brand_slug", "scraped_at"),
        Index("idx_inv_tenant", "tenant_id", "scraped_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id")
    job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")
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
