from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import Page


class ProductPublicKeyword(BaseModel):
    keyword: str
    avg_position: float | None
    appearances: int


class ProductPublicResponse(BaseModel):
    """The public (scraped) picture for one SKU, bridged via sku_map. `mapped` is
    False when the SKU has no public mapping yet."""

    mapped: bool
    platform_product_id: str | None = None
    product_name: str | None = None
    as_of: datetime | None = None
    total_stores: int = 0
    in_stock_stores: int = 0
    distribution_pct: float | None = None
    price_min: float | None = None
    price_median: float | None = None
    price_max: float | None = None
    mrp: float | None = None
    avg_discount: float | None = None
    rating: float | None = None
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
