from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SohRow(BaseModel):
    item_id: str
    item_name: str | None
    backend_qty: int
    frontend_qty: int
    facilities: int
    date: date


class FillRateSummary(BaseModel):
    from_date: date | None
    total_po_quantity: int
    total_grn_quantity: int
    fill_rate: float
    potential_loss: float
    facilities_count: int


# ── Public (scraped) availability — STORE grain ──────────────────────────────
# The unit is the dark store (`merchant_id`), read per product off the response;
# `lat`/`lon` is only the coordinate we probed. See docs/darkstores.md.
#
# Two denominators, both "observed in the selected window", carried on every
# response so the UI can render "X of N" rather than a bare percentage:
#   stores_scraped  — distinct stores that answered
#   active_range    — distinct SKUs seen at >=1 store (the live range)
# A store that failed to answer is EXCLUDED, never counted as a zero.


class StoreRef(BaseModel):
    """How a dark store is identified everywhere in the public API."""

    merchant_id: str
    store_name: str | None = None      # marketplace_locations.location_name
    city: str | None = None
    merchant_type: str | None = None   # express | longtail | super_longtail | dummy


class AvailabilityRow(BaseModel):
    """Public availability/stock-out for the client's own brand (sku_snapshots),
    latest row per (product × store)."""

    model_config = ConfigDict(from_attributes=True)

    platform_product_id: str
    product_name: str | None
    merchant_id: str
    store_name: str | None = None
    merchant_type: str | None = None
    city: str
    lat: float | None
    lon: float | None
    mp_slug: str = Field(serialization_alias="marketplace")
    in_stock: bool
    inventory: int | None
    price: float | None
    scraped_at: datetime


class DistributionRow(BaseModel):
    """Per own SKU: how widely it is on-shelf across dark stores.

    reach_pct        = stores_listed   / stores_scraped  (breadth: is it on the shelf)
    distribution_pct = stores_in_stock / stores_listed   (health: is it in stock)
    """

    platform_product_id: str
    product_name: str | None
    stores_listed: int
    stores_in_stock: int
    stores_out_of_stock: int
    stores_low_stock: int = 0
    stores_with_qty: int = 0
    low_stock_pct: float | None = None
    reach_pct: float
    distribution_pct: float
    avg_price: float | None
    avg_discount: float | None


class DistributionResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    stores_scraped: int          # the reach denominator
    active_range: int            # distinct SKUs observed
    tiers: dict[str, int] = {}   # merchant_type -> distinct stores (UI shows a split
                                 # only when >1 tier is present)
    marketplaces: list[str] = []
    skus: list[DistributionRow]


class AvailabilityHistoryPoint(BaseModel):
    week: date
    availability_pct: float
    low_stock_pct: float | None = None
    oos_pct: float
    stores: int                  # distinct stores sampled that week


class AvailabilityHistoryResponse(BaseModel):
    period_days: int
    marketplaces: list[str] = []
    points: list[AvailabilityHistoryPoint]


class SkuPricingRow(BaseModel):
    platform_product_id: str
    product_name: str | None
    stores: int
    min_price: float | None
    median_price: float | None
    max_price: float | None
    avg_discount: float | None
    # Pack + per-unit band (₹ per 100 ml / 100 g / piece per `pack_uom`). `pack_uom`
    # is "" and unit_price_* are None when the pack couldn't be parsed.
    pack_size: float | None = None
    pack_uom: str = ""
    unit_price_min: float | None = None
    unit_price_median: float | None = None
    unit_price_max: float | None = None


class SkuPricingResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    stores_scraped: int
    skus: list[SkuPricingRow]


# ── Store-grain views ────────────────────────────────────────────────────────

class StoreAvailabilityRow(BaseModel):
    """One dark store: how much of the brand's active range it carries and stocks."""

    merchant_id: str
    store_name: str | None
    merchant_type: str | None
    city: str | None
    skus_listed: int
    skus_in_stock: int
    skus_out_of_stock: int
    skus_not_listed: int
    # Shelves down to their last unit, and how many carry a quantity reading at
    # all. Kept apart from in-stock: a marketplace can report quantity while
    # being unable to report a stockout (see inventory_service.get_stores).
    skus_low_stock: int = 0
    skus_with_qty: int = 0
    low_stock_pct: float | None = None
    reach_pct: float
    distribution_pct: float


class StoresResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    stores_scraped: int
    active_range: int
    tiers: dict[str, int] = {}
    marketplaces: list[str] = []
    stores: list[StoreAvailabilityRow]


class CityAvailabilityRow(BaseModel):
    city: str | None
    stores: int
    skus_listed: int
    skus_in_stock: int
    skus_out_of_stock: int
    skus_not_listed: int
    skus_low_stock: int = 0
    skus_with_qty: int = 0
    low_stock_pct: float | None = None
    reach_pct: float
    distribution_pct: float


class CitiesResponse(BaseModel):
    period_days: int
    as_of: datetime | None
    stores_scraped: int
    active_range: int
    marketplaces: list[str] = []
    cities: list[CityAvailabilityRow]


class ActionRow(BaseModel):
    """One problem to fix, naming a store and a product.

    `issue` is either `out-of-stock` (listed but empty -> replenishment) or
    `not-listed` (absent from the shelf -> range). Kept apart on purpose: they are
    different teams' work.
    """

    merchant_id: str
    store_name: str | None
    merchant_type: str | None
    city: str | None
    platform_product_id: str
    product_name: str | None
    issue: str
    inventory: int | None = None
    price: float | None = None
    scraped_at: datetime | None = None


class StoreSkuRow(BaseModel):
    platform_product_id: str
    product_name: str | None
    listed: bool
    in_stock: bool
    inventory: int | None
    price: float | None
    discount_pct: float | None


class StoreDetailResponse(BaseModel):
    """One store's whole shelf — absent SKUs included, with `listed=False`."""

    merchant_id: str
    store_name: str | None
    city: str | None
    merchant_type: str | None
    as_of: datetime | None
    active_range: int
    skus: list[StoreSkuRow]


class ProductStoreRow(BaseModel):
    """One store's status for a single product — the product drawer's rows."""

    merchant_id: str
    store_name: str | None
    city: str | None
    merchant_type: str | None
    listed: bool
    in_stock: bool
    inventory: int | None
    price: float | None


class ProductDetailResponse(BaseModel):
    """One product across every store — the mirror of StoreDetailResponse."""

    platform_product_id: str
    product_name: str | None
    as_of: datetime | None
    stores_scraped: int
    stores_listed: int
    stores_in_stock: int
    stores: list[ProductStoreRow]
