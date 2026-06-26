"""Per-SKU performance for a client. "Products" are derived from the client's
sales rows (blinkit_seller_sales), enriched with current stock (blinkit_soh),
PO history (blinkit_po_items), and the Blinkit scorecard signal
(blinkit_scorecard_key_skus). Private plane only — keyed on `item_id`.
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination, Period
from app.models.blinkit_seller import (
    BlinkitPO,
    BlinkitPOItem,
    BlinkitScorecardKeySku,
    BlinkitSOH,
    BlinkitSellerSale,
)
from app.schemas.common import Page
from app.schemas.product import (
    STATUS_HEALTHY,
    STATUS_LOW_COVER,
    STATUS_NO_SALES,
    STATUS_OUT_OF_STOCK,
    CityShare,
    FacilityStock,
    ProductListResponse,
    ProductListRow,
    ProductListSummary,
    ProductPoRow,
)

Sale = BlinkitSellerSale
SOH = BlinkitSOH
POItem = BlinkitPOItem
KeySku = BlinkitScorecardKeySku

# A SKU with fewer than this many days of projected cover is flagged "low".
# Shared by the list status, the summary counts, and the detail view — and the
# same helpers will back /inventory/cover when that page is built.
LOW_COVER_DAYS = 7


# --- Cover / status helpers (reused by list + detail; later /inventory/cover) -

def cover_metrics(
    frontend_qty: int, units: int, window_days: int
) -> tuple[float, float | None]:
    """(avg_daily_units, days_of_cover). Cover is None when there's no velocity
    to divide by — you can't project days of cover for a non-mover."""
    avg_daily = units / window_days if window_days else 0.0
    cover = frontend_qty / avg_daily if avg_daily > 0 else None
    return round(avg_daily, 3), (round(cover, 1) if cover is not None else None)


def cover_status(frontend_qty: int, units: int, days_of_cover: float | None) -> str:
    if frontend_qty <= 0:
        return STATUS_OUT_OF_STOCK
    if units <= 0:
        return STATUS_NO_SALES
    if days_of_cover is not None and days_of_cover < LOW_COVER_DAYS:
        return STATUS_LOW_COVER
    return STATUS_HEALTHY


def _avg_price(revenue: float, units: int) -> float | None:
    return round(revenue / units, 2) if units else None


async def _latest_stock_map(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    marketplaces: list[str] | None,
) -> dict[str, tuple[int, int]]:
    """item_id -> (backend_qty, frontend_qty) on the most recent SOH snapshot
    date for this tenant. SOH is forward-only, so "current" = latest date."""
    cond = [SOH.tenant_id == tenant_id]
    if marketplaces is not None:
        cond.append(SOH.platform.in_(marketplaces))
    latest = (
        await session.execute(select(func.max(SOH.date)).where(*cond))
    ).scalar()
    if latest is None:
        return {}
    rows = (
        await session.execute(
            select(
                SOH.item_id,
                func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                func.coalesce(func.sum(SOH.frontend_inv_qty), 0),
            )
            .where(*cond, SOH.date == latest)
            .group_by(SOH.item_id)
        )
    ).all()
    return {i: (int(b), int(f)) for i, b, f in rows}


# --- List ------------------------------------------------------------------

# Sort key per `sort` param. Cover sorts ascending with None (no velocity) last,
# so the "needs attention" SKUs surface first.
_SORTERS = {
    "revenue": lambda r: -r.revenue,
    "units": lambda r: -r.units_sold,
    "price": lambda r: -(r.avg_price or 0.0),
    "cover": lambda r: (r.days_of_cover is None, r.days_of_cover or 0.0),
}


async def get_products(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    period: Period,
    marketplaces: list[str] | None = None,
    search: str | None = None,
    category: str | None = None,
    sort: str = "revenue",
    status: str | None = None,
) -> ProductListResponse:
    """SKU list joining window sales with the latest stock snapshot, carrying
    cover + a health status per row. Sales are aggregated in SQL; stock/cover are
    composed in Python (stock comes from a separate snapshot date), so sorting,
    the status filter, the summary counts, and pagination all run over the full
    in-memory set — the distinct-SKU count per tenant is small."""
    conds = [
        Sale.tenant_id == tenant_id,
        Sale.date >= period.start,
        Sale.date <= period.end,
    ]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))
    if search:
        conds.append(Sale.item_name.ilike(f"%{search}%"))
    if category:
        conds.append(Sale.category == category)

    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    sale_rows = (
        await session.execute(
            select(
                Sale.item_id,
                func.max(Sale.item_name),
                func.max(Sale.category),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.max(Sale.date),
            )
            .where(*conds)
            .group_by(Sale.item_id)
        )
    ).all()

    stock_map = await _latest_stock_map(
        session, tenant_id=tenant_id, marketplaces=marketplaces
    )
    window_days = period.length_days

    rows: list[ProductListRow] = []
    for item_id, name, cat, rev, units, last in sale_rows:
        units = int(units)
        rev = round(float(rev), 2)
        backend, frontend = stock_map.get(item_id, (0, 0))
        avg_daily, cover = cover_metrics(frontend, units, window_days)
        rows.append(
            ProductListRow(
                item_id=item_id,
                item_name=name,
                category=cat,
                units_sold=units,
                revenue=rev,
                avg_price=_avg_price(rev, units),
                last_sold=last,
                backend_qty=backend,
                frontend_qty=frontend,
                avg_daily_units=avg_daily,
                days_of_cover=cover,
                status=cover_status(frontend, units, cover),
            )
        )

    # Summary reflects the search/category/window scope (pre status-filter).
    summary = ProductListSummary(
        active_skus=len(rows),
        revenue=round(sum(r.revenue for r in rows), 2),
        units_sold=sum(r.units_sold for r in rows),
        avg_price=_avg_price(
            sum(r.revenue for r in rows), sum(r.units_sold for r in rows)
        ),
        out_of_stock=sum(1 for r in rows if r.status == STATUS_OUT_OF_STOCK),
        low_cover=sum(1 for r in rows if r.status == STATUS_LOW_COVER),
    )

    if status:
        rows = [r for r in rows if r.status == status]
    rows.sort(key=_SORTERS.get(sort, _SORTERS["revenue"]))

    total = len(rows)
    page_rows = rows[pagination.offset : pagination.offset + pagination.limit]
    return ProductListResponse(
        summary=summary, products=Page.build(page_rows, total, pagination)
    )


# --- Detail ----------------------------------------------------------------

async def get_product_detail(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    period: Period,
    marketplaces: list[str] | None = None,
) -> dict | None:
    conds = [
        Sale.tenant_id == tenant_id,
        Sale.item_id == item_id,
        Sale.date >= period.start,
        Sale.date <= period.end,
    ]
    if marketplaces is not None:
        conds.append(Sale.platform.in_(marketplaces))

    name, cat, rev, units, count = (
        await session.execute(
            select(
                func.max(Sale.item_name),
                func.max(Sale.category),
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.count(),
            ).where(*conds)
        )
    ).one()

    if count == 0:
        return None  # no sales for this SKU in the window -> 404 at the route

    rev = round(float(rev), 2)
    units = int(units)

    # Daily sales trend.
    trend_rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
            )
            .where(*conds)
            .group_by(Sale.date)
            .order_by(Sale.date)
        )
    ).all()
    trend = [
        {"date": d, "units_sold": int(u), "revenue": round(float(r), 2)}
        for d, u, r in trend_rows
    ]

    # Units/revenue split by city.
    city_rows = (
        await session.execute(
            select(
                func.coalesce(Sale.city_name, Sale.city_id),
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
            )
            .where(*conds)
            .group_by(func.coalesce(Sale.city_name, Sale.city_id))
            .order_by(func.coalesce(func.sum(Sale.mrp_value), 0.0).desc())
        )
    ).all()
    cities = [
        CityShare(city=c, units_sold=int(u), revenue=round(float(r), 2))
        for c, u, r in city_rows
    ]

    # Stock: current snapshot (summed + per-facility) and the in-window trend.
    soh_cond = [SOH.tenant_id == tenant_id, SOH.item_id == item_id]
    if marketplaces is not None:
        soh_cond.append(SOH.platform.in_(marketplaces))
    latest_date = (
        await session.execute(select(func.max(SOH.date)).where(*soh_cond))
    ).scalar()

    stock = None
    facilities: list[FacilityStock] = []
    frontend_now = 0
    if latest_date:
        backend, frontend_now = (
            await session.execute(
                select(
                    func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                    func.coalesce(func.sum(SOH.frontend_inv_qty), 0),
                ).where(*soh_cond, SOH.date == latest_date)
            )
        ).one()
        backend, frontend_now = int(backend), int(frontend_now)
        stock = {
            "date": latest_date,
            "backend_qty": backend,
            "frontend_qty": frontend_now,
        }
        fac_rows = (
            await session.execute(
                select(
                    SOH.backend_facility_id,
                    func.max(SOH.backend_facility_name),
                    func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                    func.coalesce(func.sum(SOH.frontend_inv_qty), 0),
                )
                .where(*soh_cond, SOH.date == latest_date)
                .group_by(SOH.backend_facility_id)
                .order_by(func.coalesce(func.sum(SOH.frontend_inv_qty), 0).asc())
            )
        ).all()
        facilities = [
            FacilityStock(
                facility_id=fid,
                facility_name=fname,
                backend_qty=int(b),
                frontend_qty=int(f),
            )
            for fid, fname, b, f in fac_rows
        ]

    stock_trend_rows = (
        await session.execute(
            select(
                SOH.date,
                func.coalesce(func.sum(SOH.backend_inv_qty), 0),
                func.coalesce(func.sum(SOH.frontend_inv_qty), 0),
            )
            .where(*soh_cond, SOH.date >= period.start, SOH.date <= period.end)
            .group_by(SOH.date)
            .order_by(SOH.date)
        )
    ).all()
    stock_trend = [
        {"date": d, "backend_qty": int(b), "frontend_qty": int(f)}
        for d, b, f in stock_trend_rows
    ]

    # Latest Blinkit scorecard signal for this SKU (potential fill loss), if any.
    potential_loss = (
        await session.execute(
            select(KeySku.potential_loss)
            .where(KeySku.tenant_id == tenant_id, KeySku.item_id == item_id)
            .order_by(KeySku.from_date_ist.desc())
            .limit(1)
        )
    ).scalar()

    avg_daily, cover = cover_metrics(frontend_now, units, period.length_days)

    return {
        "item_id": item_id,
        "item_name": name,
        "category": cat,
        "period_days": period.length_days,
        "units_sold": units,
        "revenue": rev,
        "avg_price": _avg_price(rev, units),
        "stock": stock,
        "avg_daily_units": avg_daily,
        "days_of_cover": cover,
        "status": cover_status(frontend_now, units, cover),
        "potential_loss": (
            round(float(potential_loss), 2) if potential_loss is not None else None
        ),
        "trend": trend,
        "stock_trend": stock_trend,
        "facilities": facilities,
        "cities": cities,
    }


# --- PO history ------------------------------------------------------------

async def get_product_pos(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: str,
    pagination: Pagination,
) -> Page[ProductPoRow]:
    """This SKU's purchase-order line history, newest first. Each line is joined
    to its PO header for date/state/facility; received = ordered − remaining."""
    cond = [POItem.tenant_id == tenant_id, POItem.item_id == item_id]

    total = (
        await session.execute(
            select(func.count()).select_from(POItem).where(*cond)
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                POItem.po_number,
                BlinkitPO.po_state,
                BlinkitPO.issue_date,
                BlinkitPO.facility_name,
                POItem.units_ordered,
                POItem.remaining_quantity,
                POItem.cost_price,
                POItem.total_amount,
            )
            .join(
                BlinkitPO,
                (BlinkitPO.tenant_id == POItem.tenant_id)
                & (BlinkitPO.po_number == POItem.po_number),
                isouter=True,
            )
            .where(*cond)
            .order_by(BlinkitPO.issue_date.desc().nullslast(), POItem.po_number)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).all()

    items = [
        ProductPoRow(
            po_number=po_number,
            po_state=state,
            issue_date=issue,
            facility_name=facility,
            units_ordered=ordered,
            received_qty=(
                ordered - remaining
                if ordered is not None and remaining is not None
                else None
            ),
            remaining_quantity=remaining,
            cost_price=cost,
            total_amount=total_amt,
        )
        for (
            po_number,
            state,
            issue,
            facility,
            ordered,
            remaining,
            cost,
            total_amt,
        ) in rows
    ]
    return Page.build(items, total, pagination)
