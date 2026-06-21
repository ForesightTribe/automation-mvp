from datetime import date

from pydantic import BaseModel


class ProductListRow(BaseModel):
    item_id: str
    item_name: str | None
    category: str | None
    units_sold: int
    revenue: float
    last_sold: date | None


class ProductStock(BaseModel):
    date: date
    backend_qty: int
    frontend_qty: int


class SkuTrendPoint(BaseModel):
    date: date
    units_sold: int
    revenue: float


class ProductDetail(BaseModel):
    item_id: str
    item_name: str | None
    category: str | None
    period_days: int
    units_sold: int
    revenue: float
    stock: ProductStock | None
    trend: list[SkuTrendPoint]
