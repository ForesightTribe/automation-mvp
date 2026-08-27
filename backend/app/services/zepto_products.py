"""Zepto-side reads for the Products page.

Kept out of `product_service.py` for the same reason `zepto_analytics` is kept
out of `analytics_service`: the sources are shaped differently. Blinkit joins
sales (`blinkit_seller_sales`) to a separate stock snapshot (`blinkit_soh`);
Zepto carries both on one row of `zepto_seller_product_perf`, one row per SKU
per day.

These functions return **raw aggregates**, not `ProductListRow` objects, so
cover/status stay defined once in `product_service` (importing them back here
would make the two modules circular). The caller builds the rows.

Three deliberate mapping choices:

* `sku_name` over `product_name` — it carries the pack ("… 400.0 GRAM"), which
  is what Blinkit's `item_name` does too.
* `subcategory_name` over `category_name` for the Category column. Every Brik
  Oven SKU shares one `category_name` ("Dairy, Bread & Eggs"), which would make
  the column identical on every row; the subcategory actually splits them
  ("Breads & Buns" / "Cheese").
* `stock_on_hand` is read from the **latest day in the window**, never summed.
  It is a snapshot of stock now, not something that accrued over the window —
  summing 11 days of it reports Whole Wheat Sourdough at 5,667 units when the
  real figure is 268.

Deliberately absent: purchase orders and the scorecard signal. Zepto publishes
neither, so `get_product_pos` and `potential_loss` stay Blinkit-only rather
than returning an empty list that reads as "no POs" instead of "no such data".
"""
import uuid
from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zepto_seller import ZeptoSellerProductPerf as Prod
from app.models.zepto_seller import ZeptoSellerProductCityDaily as ProdCity
from app.models.zepto_seller import ZeptoPO, ZeptoPOItem

# Which marketplace slug routes to these tables.
SLUG = "zepto"


def wants_zepto(marketplaces: list[str] | None) -> bool:
    """`None` means "every marketplace", which includes Zepto."""
    return marketplaces is None or SLUG in marketplaces


def _conds(tenant_id: uuid.UUID, start: date, end: date) -> list:
    # period_start == period_end keeps any window-grain row (a range scraped in
    # one call) out of a day-scoped query, where it would double-count.
    return [
        Prod.tenant_id == tenant_id,
        Prod.period_start >= start,
        Prod.period_start <= end,
        Prod.period_start == Prod.period_end,
    ]


def _name(sku_name: str | None, product_name: str | None) -> str | None:
    return sku_name or product_name


def _category(sub: str | None, cat: str | None) -> str | None:
    return sub or cat


async def _latest_stock(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: date, end: date
) -> dict[str, int]:
    """product_variant_id -> stock_on_hand on its most recent day in the window.

    DISTINCT ON rather than an aggregate because stock is a snapshot: the newest
    reading is the answer, not the sum or the max. Rows where Zepto returned no
    stock value are skipped, so the caller sees 0 rather than a bogus number.
    """
    rows = (
        await session.execute(
            select(Prod.product_variant_id, Prod.stock_on_hand)
            .where(*_conds(tenant_id, start, end), Prod.stock_on_hand.is_not(None))
            .distinct(Prod.product_variant_id)
            .order_by(Prod.product_variant_id, Prod.period_start.desc())
        )
    ).all()
    return {pid: int(soh) for pid, soh in rows}


async def list_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    search: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """One dict per SKU with sales totals for the window plus current stock.

    Mirrors the shape `product_service.get_products` builds its rows from, so it
    can extend its own list with these and run one sort/paginate over both.

    A SKU with no sales in the window is absent, not zero: Zepto's
    product-performance response omits SKUs that sold nothing, and the scraper
    drops any row without a `gmv`. Same behaviour as Blinkit, whose list is
    likewise built from sales rows.
    """
    conds = _conds(tenant_id, start, end)
    if search:
        conds.append(Prod.sku_name.ilike(f"%{search}%"))
    if category:
        # Match whichever field feeds the Category column (see module docstring).
        conds.append(
            func.coalesce(Prod.subcategory_name, Prod.category_name) == category
        )

    rows = (
        await session.execute(
            select(
                Prod.product_variant_id,
                func.max(Prod.sku_name),
                func.max(Prod.product_name),
                func.max(Prod.subcategory_name),
                func.max(Prod.category_name),
                func.coalesce(func.sum(Prod.gmv), 0.0),
                func.coalesce(func.sum(Prod.qty_sold), 0),
                func.max(Prod.period_start),
            )
            .where(*conds)
            .group_by(Prod.product_variant_id)
        )
    ).all()

    stock = await _latest_stock(session, tenant_id=tenant_id, start=start, end=end)

    return [
        {
            "item_id": pid,
            "item_name": _name(sku_name, prod_name),
            "category": _category(sub, cat),
            "revenue": round(float(rev), 2),
            "units_sold": int(units),
            "last_sold": last,
            # Zepto reports one stock figure, with no backend/frontend split.
            # It maps to frontend (shelf) stock, which is what cover divides.
            "frontend_qty": stock.get(pid, 0),
            "backend_qty": 0,
        }
        for pid, sku_name, prod_name, sub, cat, rev, units, last in rows
    ]


async def detail_agg(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    start: date,
    end: date,
) -> dict | None:
    """Totals, daily trend and stock trend for one SKU. None when it had no
    sales in the window, so the route can 404 exactly as it does for Blinkit."""
    conds = [*_conds(tenant_id, start, end), Prod.product_variant_id == item_id]

    sku_name, prod_name, sub, cat, rev, units, count = (
        await session.execute(
            select(
                func.max(Prod.sku_name),
                func.max(Prod.product_name),
                func.max(Prod.subcategory_name),
                func.max(Prod.category_name),
                func.coalesce(func.sum(Prod.gmv), 0.0),
                func.coalesce(func.sum(Prod.qty_sold), 0),
                func.count(),
            ).where(*conds)
        )
    ).one()
    if count == 0:
        return None

    day_rows = (
        await session.execute(
            select(Prod.period_start, Prod.qty_sold, Prod.gmv, Prod.stock_on_hand)
            .where(*conds)
            .order_by(Prod.period_start)
        )
    ).all()

    trend = [
        {"date": d, "units_sold": int(u or 0), "revenue": round(float(g or 0.0), 2)}
        for d, u, g, _ in day_rows
    ]
    # Only the frontend series is real; Zepto has no backend/warehouse figure,
    # so backend_qty is 0 throughout rather than a guess.
    stock_trend = [
        {"date": d, "backend_qty": 0, "frontend_qty": int(soh)}
        for d, _, _, soh in day_rows
        if soh is not None
    ]
    stock = None
    if stock_trend:
        last = stock_trend[-1]
        stock = {
            "date": last["date"],
            "backend_qty": 0,
            "frontend_qty": last["frontend_qty"],
        }

    return {
        "item_id": item_id,
        "item_name": _name(sku_name, prod_name),
        "category": _category(sub, cat),
        "revenue": round(float(rev), 2),
        "units_sold": int(units),
        "stock": stock,
        "frontend_qty": stock["frontend_qty"] if stock else 0,
        "trend": trend,
        "stock_trend": stock_trend,
        # No Zepto source for either — see module docstring.
        "facilities": [],
        "potential_loss": None,
    }


async def cities(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    start: date,
    end: date,
) -> list[dict]:
    """Units/revenue per city **for one SKU**.

    Reads `zepto_seller_product_city_daily`, which is scraped one call per city
    because no single Zepto response carries city and product together. Before
    that table existed this could only be answered at brand level, so the card
    was left empty rather than showing the brand split under a per-SKU heading.

    Returns [] for a window scraped before the per-city breakdown was added —
    the card then says so instead of implying the SKU sold nowhere.
    """
    rows = (
        await session.execute(
            select(
                ProdCity.city_name,
                func.coalesce(func.sum(ProdCity.qty_sold), 0),
                func.coalesce(func.sum(ProdCity.gmv), 0.0),
            )
            .where(
                ProdCity.tenant_id == tenant_id,
                ProdCity.product_variant_id == item_id,
                ProdCity.date >= start,
                ProdCity.date <= end,
            )
            .group_by(ProdCity.city_name)
            .order_by(func.coalesce(func.sum(ProdCity.gmv), 0.0).desc())
        )
    ).all()
    return [
        {"city": city, "units_sold": int(u), "revenue": round(float(r), 2)}
        for city, u, r in rows
    ]


async def po_lines(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: str,
    offset: int = 0, limit: int = 10,
) -> tuple[list[dict], int]:
    """(rows, total) of PO lines for one SKU, newest order first.

    Joined to `zepto_po` for the header fields the row needs — order date,
    status and warehouse — which the line itself does not carry.

    Matched on `product_variant_id`, which is Zepto's `pvId` and the SAME id
    `zepto_seller_product_perf` keys on. So this needs no name matching and no
    `sku_map` bridge, unlike Blinkit where the private and public id systems
    share no key.

    Field names mirror Blinkit's `ProductPoRow` so the same table renders both:
    `unit_price` -> cost_price, `grn_qty` -> received_qty, and so on.
    """
    conds = [
        ZeptoPOItem.tenant_id == tenant_id,
        ZeptoPOItem.product_variant_id == item_id,
    ]
    total = (
        await session.execute(
            select(func.count()).select_from(ZeptoPOItem).where(*conds)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                ZeptoPOItem.po_id,
                ZeptoPO.status,
                ZeptoPO.po_date,
                ZeptoPO.location,
                ZeptoPOItem.po_qty,
                ZeptoPOItem.grn_qty,
                ZeptoPOItem.remaining_qty,
                ZeptoPOItem.unit_price,
                ZeptoPOItem.total_value,
            )
            .join(
                ZeptoPO,
                (ZeptoPO.tenant_id == ZeptoPOItem.tenant_id)
                & (ZeptoPO.po_id == ZeptoPOItem.po_id),
                isouter=True,
            )
            .where(*conds)
            .order_by(ZeptoPO.po_date.desc().nullslast(), ZeptoPOItem.po_id)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    return (
        [
            {
                "po_number": po_id,
                "po_state": status,
                # The schema wants a datetime; the PO carries a calendar day.
                "issue_date": (
                    datetime.combine(po_date, time.min) if po_date else None
                ),
                "facility_name": location,
                "units_ordered": po_qty,
                "received_qty": grn_qty,
                "remaining_quantity": remaining_qty,
                "cost_price": unit_price,
                "total_amount": total_value,
            }
            for (po_id, status, po_date, location, po_qty, grn_qty,
                 remaining_qty, unit_price, total_value) in rows
        ],
        int(total),
    )
