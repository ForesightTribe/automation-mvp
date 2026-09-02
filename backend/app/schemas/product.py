from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import Page


class ProductPublicKeyword(BaseModel):
    keyword: str
    avg_position: float | None
    stores: int             # distinct dark stores it ranked in


class ProductPublicResponse(BaseModel):
    """The public (scraped) picture for one SKU, bridged via sku_map. `mapped` is
    False when the SKU has no public mapping yet.

    Counts are distinct DARK STORES (`merchant_id`), read per product off the scrape.
    `stores_scraped` — the reach denominator — is the stores that actually answered in
    the window, not a configured catalog count: a store we failed to reach is excluded
    rather than counted as a miss. Rows predating 2026-07-18 have no store id and are
    excluded. See docs/darkstores.md."""

    mapped: bool
    platform_product_id: str | None = None
    product_name: str | None = None
    as_of: datetime | None = None
    stores_listed: int = 0          # stores where the SKU was on the shelf
    stores_in_stock: int = 0
    distribution_pct: float | None = None  # in stock ÷ listed
    stores_scraped: int = 0         # stores that answered (reach denominator)
    reach_pct: float | None = None  # listed ÷ scraped
    price_min: float | None = None
    price_median: float | None = None
    price_max: float | None = None
    mrp: float | None = None
    avg_discount: float | None = None
    rating: float | None = None
    # Pack + per-unit band (₹ per 100 ml / 100 g / piece per `pack_uom`). `pack_uom`
    # is "" and unit_price_* are None when the pack couldn't be parsed.
    pack_size: float | None = None
    pack_uom: str = ""
    unit_price_min: float | None = None
    unit_price_median: float | None = None
    unit_price_max: float | None = None
    keywords: list[ProductPublicKeyword] = []


# SKU health states (derived from current stock + window velocity).
STATUS_OUT_OF_STOCK = "out_of_stock"
STATUS_LOW_COVER = "low_cover"
STATUS_NO_SALES = "no_sales"
STATUS_HEALTHY = "healthy"


class ProductListRow(BaseModel):
    item_id: str
    item_name: str | None
    category: str | None
    # Which marketplace produced this row. The table needs it per ROW, not per
    # page: with both platforms selected the list interleaves them, so a
    # page-level flag would mislabel half the rows. Used to hide the
    # frontend/backend stock split on Zepto, which reports one figure and no
    # split — rendering "98 / 0" there reads as an empty back room rather than
    # "not reported".
    marketplace: str = "blinkit"
    units_sold: int
    revenue: float
    avg_price: float | None
    last_sold: date | None
    # Current stock (latest SOH snapshot, summed across facilities).
    backend_qty: int
    frontend_qty: int
    # Velocity + cover (window-length basis); cover is null when there's no
    # velocity to divide by (can't project days of cover for a non-mover).
    avg_daily_units: float
    days_of_cover: float | None
    status: str


class ProductListSummary(BaseModel):
    """KPI strip for the SKU list — reflects the current search/category/window
    scope (ignores pagination and the status drill-down filter)."""

    active_skus: int
    revenue: float
    units_sold: int
    avg_price: float | None
    out_of_stock: int
    low_cover: int


class ProductListResponse(BaseModel):
    summary: ProductListSummary
    products: Page[ProductListRow]


class ProductStock(BaseModel):
    date: date
    backend_qty: int
    frontend_qty: int


class FacilityStock(BaseModel):
    facility_id: str
    facility_name: str | None
    backend_qty: int
    frontend_qty: int


class StockTrendPoint(BaseModel):
    date: date
    backend_qty: int
    frontend_qty: int


class SkuTrendPoint(BaseModel):
    date: date
    units_sold: int
    revenue: float


class CityShare(BaseModel):
    city: str
    units_sold: int
    revenue: float


class ProductDetail(BaseModel):
    item_id: str
    item_name: str | None
    category: str | None
    # Which marketplace produced this row. The detail page uses it to say why a
    # section is empty — "Zepto doesn't report stock by facility" is a different
    # statement from "this SKU has no stock", and the UI must not conflate them.
    marketplace: str = "blinkit"
    period_days: int
    units_sold: int
    revenue: float
    avg_price: float | None
    # Current stock + cover.
    stock: ProductStock | None
    avg_daily_units: float
    days_of_cover: float | None
    status: str
    # Blinkit scorecard signal for this SKU, when present in the latest week.
    potential_loss: float | None
    # Breakdowns.
    trend: list[SkuTrendPoint]
    stock_trend: list[StockTrendPoint]
    facilities: list[FacilityStock]
    cities: list[CityShare]


class ProductPoRow(BaseModel):
    po_number: str
    po_state: str | None
    issue_date: datetime | None
    facility_name: str | None
    units_ordered: int | None
    received_qty: int | None
    remaining_quantity: int | None
    cost_price: float | None
    total_amount: float | None
