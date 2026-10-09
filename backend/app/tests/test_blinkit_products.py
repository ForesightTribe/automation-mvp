"""Blinkit rows on the Products page — a SKU with no stock reading (BLINKIT-NOTES B2).

Blinkit's SOH report lists genuine zeros, so a SKU it does not list at all has NO reading.
It used to show "Out of stock" (2026-10-07: Brik Oven's Honey & Oats Sourdough, 192 units in
7 days, has never appeared in SOH). Now it is "No stock data", with no cover — the rule
seller-hub SKUs and Zepto already followed.

No database: the session answers each query in turn.

    python -m pytest app/tests/test_blinkit_products.py
"""
import asyncio
import uuid
from datetime import date

from app.dependencies import Pagination, Period
from app.schemas.product import STATUS_HEALTHY, STATUS_NO_STOCK_DATA, STATUS_OUT_OF_STOCK
from app.services import product_service as ps

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
PERIOD = Period(start=date(2026, 10, 1), end=date(2026, 10, 7),
                prev_start=date(2026, 9, 24), prev_end=date(2026, 9, 30))


class _Result:
    def __init__(self, value):
        self.value = value

    def all(self):
        return self.value

    def scalar(self):
        return self.value


class _Queued:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def execute(self, *_a, **_k):
        return _Result(self.answers.pop(0))


def test_a_sku_missing_from_soh_is_no_stock_data_and_a_listed_zero_is_out_of_stock():
    sales = [  # item_id, name, category, revenue, units, last sold
        ("10307810", "Honey & Oats Sourdough", "Bread", 19200.0, 192, date(2026, 10, 6)),
        ("10304188", "Rosemary & Cheddar", "Bread", 1900.0, 19, date(2026, 10, 6)),
        ("111", "Sour Cream", "Dairy", 800.0, 8, date(2026, 10, 6)),
    ]
    soh_rows = [("10304188", 0, 0), ("111", 5, 40)]          # listed: one zero, one stocked
    session = _Queued(sales, date(2026, 10, 7), soh_rows)

    async def no_hub(*_a, **_k):
        return []

    real = ps.seller_hub.product_list_agg
    ps.seller_hub.product_list_agg = no_hub
    try:
        res = asyncio.run(ps.get_products(session, tenant_id=TENANT,
                                          pagination=Pagination(page=1, limit=50),
                                          period=PERIOD, marketplaces=["blinkit"]))
    finally:
        ps.seller_hub.product_list_agg = real
    rows = {r.item_id: r for r in res.products.items}
    assert rows["10307810"].status == STATUS_NO_STOCK_DATA and rows["10307810"].days_of_cover is None
    assert rows["10304188"].status == STATUS_OUT_OF_STOCK, "a zero SOH lists is a real zero"
    assert rows["111"].status == STATUS_HEALTHY
    assert res.summary.out_of_stock == 1
