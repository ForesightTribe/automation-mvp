"""Zepto rows on the Products page — cover and status (P11, 2026-10-07).

  * days of cover divides by the days Zepto HAS data for, not the window's calendar length:
    every navbar preset ends today while the newest Zepto day is yesterday, so the default
    7-day view used to overstate cover by 7/6, and "yesterday + today" doubled it;
  * a SKU with no stock reading is "No stock data", not "Out of stock".

No database: the Zepto reads are faked, and the Blinkit queries `get_products` still runs
(scoped to Zepto, so they return nothing) answer empty.

    python -m pytest app/tests/test_zepto_products.py
"""
import asyncio
import uuid
from datetime import date

from app.dependencies import Pagination, Period
from app.schemas.product import STATUS_HEALTHY, STATUS_NO_STOCK_DATA
from app.services import product_service as ps
from app.services import zepto_products as zp

TENANT = uuid.UUID("fa53082e-7e83-424d-aab9-086fe1b4c680")
# A 7-day navbar window ending "today" — Zepto has data for 6 of its days.
PERIOD = Period(start=date(2026, 10, 1), end=date(2026, 10, 7),
                prev_start=date(2026, 9, 24), prev_end=date(2026, 9, 30))


class _Empty:
    def all(self):
        return []

    def scalar(self):
        return None


class _Session:
    async def execute(self, *_a, **_k):
        return _Empty()


def _row(item_id: str, *, units: int, stock: int, known: bool = True) -> dict:
    return {"item_id": item_id, "item_name": item_id, "category": "Bread",
            "revenue": units * 100.0, "units_sold": units, "last_sold": date(2026, 10, 6),
            "frontend_qty": stock, "backend_qty": 0, "stock_known": known}


def _patched(**fakes):
    saved = {k: getattr(ps.zepto_products, k) for k in fakes}
    for k, v in fakes.items():
        setattr(ps.zepto_products, k, v)
    return saved


def _restore(saved):
    for k, v in saved.items():
        setattr(ps.zepto_products, k, v)


def _list(rows: list[dict], days_with_data: int):
    async def list_agg(*_a, **_k):
        return rows

    async def data_days(*_a, **_k):
        return days_with_data

    saved = _patched(list_agg=list_agg, data_days=data_days)
    try:
        res = asyncio.run(ps.get_products(_Session(), tenant_id=TENANT,
                                          pagination=Pagination(page=1, limit=50),
                                          period=PERIOD, marketplaces=["zepto"]))
    finally:
        _restore(saved)
    return {r.item_id: r for r in res.products.items}, res.summary


def test_cover_divides_by_the_days_zepto_has_data_for():
    """60 units over the 6 days with data = 10 a day; 100 in stock = 10 days of cover.
    Dividing by the 7-day window said 8.57 a day and 11.7 days."""
    rows, _ = _list([_row("pv1", units=60, stock=100)], days_with_data=6)
    assert rows["pv1"].avg_daily_units == 10.0
    assert rows["pv1"].days_of_cover == 10.0
    assert rows["pv1"].status == STATUS_HEALTHY


def test_a_sku_without_a_stock_reading_is_no_stock_data_not_out_of_stock():
    rows, summary = _list([_row("pv1", units=60, stock=0, known=False)], days_with_data=6)
    assert rows["pv1"].status == STATUS_NO_STOCK_DATA
    assert rows["pv1"].days_of_cover is None
    assert summary.out_of_stock == 0, "an unknown stock must not count as out of stock"


def test_a_real_zero_is_still_out_of_stock():
    rows, summary = _list([_row("pv1", units=60, stock=0)], days_with_data=6)
    assert rows["pv1"].status == "out_of_stock" and summary.out_of_stock == 1


def _detail(stock_known: bool, frontend: int, days_with_data: int) -> dict:
    async def detail_agg(*_a, **_k):
        return {"item_id": "pv1", "item_name": "pv1", "category": "Bread", "revenue": 6000.0,
                "units_sold": 60, "stock": None, "frontend_qty": frontend,
                "stock_known": stock_known, "trend": [], "stock_trend": [],
                "facilities": []}

    async def cities(*_a, **_k):
        return []

    async def data_days(*_a, **_k):
        return days_with_data

    saved = _patched(detail_agg=detail_agg, cities=cities, data_days=data_days)
    try:
        return asyncio.run(ps._zepto_detail(_Session(), tenant_id=TENANT, item_id="pv1",
                                            period=PERIOD))
    finally:
        _restore(saved)


def test_product_page_uses_the_same_divisor_and_hides_the_flag():
    d = _detail(stock_known=True, frontend=100, days_with_data=6)
    assert d["avg_daily_units"] == 10.0 and d["days_of_cover"] == 10.0
    assert d["period_days"] == 7, "the window shown is still the one picked"
    assert "stock_known" not in d, "internal flag must not leak into the response"


def test_product_page_without_a_reading_is_no_stock_data():
    d = _detail(stock_known=False, frontend=0, days_with_data=6)
    assert d["status"] == STATUS_NO_STOCK_DATA and d["days_of_cover"] is None


# ── P41 step 2: stock from zepto_soh, the old column only as a fallback ───────

class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Queued:
    """Answers each execute() with the next queued result set, recording the SQL."""

    def __init__(self, *results):
        self.results, self.sql = list(results), []

    async def execute(self, stmt, *_a, **_k):
        from sqlalchemy.dialects import postgresql
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        return _Rows(self.results.pop(0))


def test_latest_stock_prefers_zepto_soh_and_falls_back_per_product():
    """pv1 has a zepto_soh reading (wins over the old column); pv2 has only the old
    column (the days before the deploy); pv3 has neither (absent = no reading)."""
    session = _Queued([("pv1", 50), ("pv2", 7)],      # old: zepto_seller_sales.stock_on_hand
                      [("pv1", 102)])                  # new: zepto_soh
    got = asyncio.run(zp._latest_stock(session, tenant_id=TENANT,
                                       start=date(2026, 10, 1), end=date(2026, 10, 7)))
    assert got == {"pv1": 102, "pv2": 7}
    assert "zepto_soh" in session.sql[1] and "zepto_seller_sales" in session.sql[0]


def test_soh_readings_run_to_the_morning_after_the_window():
    """A reading is dated the day the scrape asked; the morning after the last day is
    that day's closing stock, so it belongs to the window."""
    from sqlalchemy.dialects import postgresql
    conds = zp._soh_conds(TENANT, date(2026, 9, 1), date(2026, 9, 30))
    sql = " ".join(str(c.compile(dialect=postgresql.dialect(),
                                 compile_kwargs={"literal_binds": True})) for c in conds)
    assert "'2026-09-01'" in sql and "'2026-10-01'" in sql


def test_stock_trend_uses_zepto_soh_points_when_it_has_any():
    totals = [("SKU", "P", "Bread", "Bakery", 600.0, 6, 3)]
    day_rows = [(date(2026, 10, d), 2, 200.0, 102) for d in (4, 5, 6)]   # old: one flat line
    soh = [(date(2026, 10, 5), 120), (date(2026, 10, 6), 110), (date(2026, 10, 7), 102)]

    class _S(_Queued):
        async def execute(self, stmt, *_a, **_k):
            r = await super().execute(stmt)
            return _One(r._rows) if len(self.sql) == 1 else r

    class _One(_Rows):
        def one(self):
            return self._rows[0]

    d = asyncio.run(zp.detail_agg(_S(totals, day_rows, soh), tenant_id=TENANT, item_id="pv1",
                                  start=date(2026, 10, 1), end=date(2026, 10, 7)))
    # 10-04 is before the first real reading (10-05) → kept from the old series; from 10-05 on,
    # only real readings.
    assert [(p["date"].day, p["frontend_qty"]) for p in d["stock_trend"]] == [
        (4, 102), (5, 120), (6, 110), (7, 102)]
    assert d["stock"]["frontend_qty"] == 102 and d["stock"]["date"] == date(2026, 10, 7)

    one = asyncio.run(zp.detail_agg(_S(totals, day_rows, [(date(2026, 10, 7), 99)]),
                                    tenant_id=TENANT, item_id="pv1", start=date(2026, 10, 1),
                                    end=date(2026, 10, 7)))
    assert [p["frontend_qty"] for p in one["stock_trend"]] == [102, 102, 102, 99], \
        "one real reading must not wipe the older days (deploy day)"

    old_only = asyncio.run(zp.detail_agg(_S(totals, day_rows, []), tenant_id=TENANT,
                                         item_id="pv1", start=date(2026, 10, 1),
                                         end=date(2026, 10, 7)))
    assert [p["frontend_qty"] for p in old_only["stock_trend"]] == [102, 102, 102], \
        "no zepto_soh reading yet → the old series, unchanged"
