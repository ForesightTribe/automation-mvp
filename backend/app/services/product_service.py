"""Per-SKU performance for a client. "Products" are derived from the client's
sales rows (blinkit_seller_sales), enriched with current stock (blinkit_soh).
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import BlinkitSOH, BlinkitSellerSale
from app.schemas.common import Page
from app.schemas.product import ProductListRow

Sale = BlinkitSellerSale


async def get_products(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    days: int = 30,
    search: str | None = None,
    category: str | None = None,
) -> Page[ProductListRow]:
    since = date.today() - timedelta(days=days)
    conditions = [Sale.tenant_id == tenant_id, Sale.date >= since]
    if search:
        conditions.append(Sale.item_name.ilike(f"%{search}%"))
    if category:
        conditions.append(Sale.category == category)

    total = (
        await session.execute(
            select(func.count(distinct(Sale.item_id))).where(*conditions)
        )
    ).scalar_one()

    revenue = func.coalesce(func.sum(Sale.mrp_value), 0.0)
    rows = (
        await session.execute(
            select(
                Sale.item_id,
                func.max(Sale.item_name),
                func.max(Sale.category),
                revenue,
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.max(Sale.date),
            )
            .where(*conditions)
            .group_by(Sale.item_id)
            .order_by(revenue.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).all()

    items = [
        ProductListRow(
            item_id=item_id,
            item_name=name,
            category=cat,
            revenue=round(float(rev), 2),
            units_sold=int(units),
            last_sold=last,
        )
        for item_id, name, cat, rev, units, last in rows
    ]
    return Page.build(items, total, pagination)


async def get_product_detail(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: str, days: int = 30
) -> dict | None:
    since = date.today() - timedelta(days=days)
    cond = [Sale.tenant_id == tenant_id, Sale.item_id == item_id, Sale.date >= since]

    name, cat, rev, units, count = (
        await session.execute(
            select(
                func.max(Sale.item_name),
                func.max(Sale.category),
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.count(),
            ).where(*cond)
        )
    ).one()

    if count == 0:
        return None  # no sales for this SKU in the window -> 404 at the route

    trend_rows = (
        await session.execute(
            select(
                Sale.date,
                func.coalesce(func.sum(Sale.qty_sold), 0),
                func.coalesce(func.sum(Sale.mrp_value), 0.0),
            )
            .where(*cond)
            .group_by(Sale.date)
            .order_by(Sale.date)
        )
    ).all()
    trend = [
        {"date": d, "units_sold": int(u), "revenue": round(float(r), 2)}
        for d, u, r in trend_rows
    ]

    # Latest stock-on-hand, summed across facilities for the most recent date.
    latest_date = (
        await session.execute(
            select(func.max(BlinkitSOH.date)).where(
                BlinkitSOH.tenant_id == tenant_id, BlinkitSOH.item_id == item_id
            )
        )
    ).scalar()
    stock = None
    if latest_date:
        backend, frontend = (
            await session.execute(
                select(
                    func.coalesce(func.sum(BlinkitSOH.backend_inv_qty), 0),
                    func.coalesce(func.sum(BlinkitSOH.frontend_inv_qty), 0),
                ).where(
                    BlinkitSOH.tenant_id == tenant_id,
                    BlinkitSOH.item_id == item_id,
                    BlinkitSOH.date == latest_date,
                )
            )
        ).one()
        stock = {
            "date": latest_date,
            "backend_qty": int(backend),
            "frontend_qty": int(frontend),
        }

    return {
        "item_id": item_id,
        "item_name": name,
        "category": cat,
        "period_days": days,
        "units_sold": int(units),
        "revenue": round(float(rev), 2),
        "stock": stock,
        "trend": trend,
    }
