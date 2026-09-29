"""Client-scoped purchase orders (blinkit_pos) and PO snapshots.

`marketplace=` on `insights_summary`/`insights`/`sku_insights`/`get_po` is
explicit-only, same convention as `scorecard_service._platform`: leaving it
unset keeps every existing Blinkit caller unaffected, and neither Instamart
nor Zepto is ever auto-detected. See `instamart_po_service` for what it can't
carry that Blinkit's PO data can (booking slots, a separate delivery date,
city); see `zepto_po_service` for why IT reads from line items instead of its
own PO header (the header's own received/asn totals are always null)."""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.blinkit_seller import BlinkitPO, BlinkitPOItem, BlinkitPOSnapshot
from app.schemas.common import Page
from app.schemas.purchase_order import (
    PODetailOut,
    POInsightRow,
    POSkuRow,
    POInsightsSummary,
    POItemOut,
    POSnapshotOut,
    PurchaseOrderOut,
)
from app.services import instamart_po_service, zepto_po_service

# A PO whose delivery window has not closed: the undelivered part is still to come,
# not lost. Anything else is settled, and its shortfall is a miss.
OPEN_STATES = ("Scheduled", "Unscheduled", "Created")
# Undelivered value bands (₹) behind the priority chip.
HIGH_RUPEES = 50_000
MEDIUM_RUPEES = 10_000


async def list_pos(
    session: AsyncSession, *, tenant_id: uuid.UUID, pagination: Pagination
) -> Page[PurchaseOrderOut]:
    cond = [BlinkitPO.tenant_id == tenant_id]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitPO).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitPO)
            .where(*cond)
            .order_by(BlinkitPO.scraped_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build(
        [PurchaseOrderOut.model_validate(r) for r in rows], total, pagination
    )


async def get_po(
    session: AsyncSession, *, tenant_id: uuid.UUID, po_number: str,
    marketplace: str | None = None,
) -> PODetailOut | None:
    if marketplace == "instamart":
        return await instamart_po_service.get_po(
            session, tenant_id=tenant_id, po_number=po_number
        )
    if marketplace == "zepto":
        return await zepto_po_service.get_po(
            session, tenant_id=tenant_id, po_number=po_number
        )
    po = (
        await session.execute(
            select(BlinkitPO).where(
                BlinkitPO.tenant_id == tenant_id, BlinkitPO.po_number == po_number
            )
        )
    ).scalar_one_or_none()
    if not po:
        return None
    items = (
        await session.execute(
            select(BlinkitPOItem).where(
                BlinkitPOItem.tenant_id == tenant_id,
                BlinkitPOItem.po_number == po_number,
            )
        )
    ).scalars().all()
    detail = PODetailOut.model_validate(po)
    detail.items = [POItemOut.model_validate(it) for it in items]
    return detail


async def list_snapshots(
    session: AsyncSession, *, tenant_id: uuid.UUID, pagination: Pagination
) -> Page[POSnapshotOut]:
    cond = [BlinkitPOSnapshot.tenant_id == tenant_id]
    total = (
        await session.execute(
            select(func.count()).select_from(BlinkitPOSnapshot).where(*cond)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(BlinkitPOSnapshot)
            .where(*cond)
            .order_by(BlinkitPOSnapshot.window_start.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
    ).scalars().all()
    return Page.build(
        [POSnapshotOut.model_validate(r) for r in rows], total, pagination
    )


def _priority(undelivered: float, is_open: bool) -> str:
    """How much money is riding on this PO. Bands are rupees of undelivered value;
    a settled PO is never "high" — nothing can be done about it now."""
    if not is_open:
        return "medium" if undelivered >= HIGH_RUPEES else "low"
    if undelivered >= HIGH_RUPEES:
        return "high"
    return "medium" if undelivered >= MEDIUM_RUPEES else "low"


def _window(start: date, end: date):
    return [BlinkitPO.issue_date >= start, BlinkitPO.issue_date < end + timedelta(days=1)]


def _delta(now: float | None, before: float | None) -> float | None:
    """Change as a fraction. None when there is no earlier figure to compare with —
    "up 100%" from nothing is a statement the data does not support."""
    if now is None or not before:
        return None
    return round((now - before) / before, 4)


async def insights_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date | None = None,
    prev_end: date | None = None,
    marketplace: str | None = None,
) -> POInsightsSummary:
    """The KPI tiles: what was ordered, how much of it arrived, and what is undelivered.

    Fill rate counts CLOSED POs only. An open PO has delivered nothing yet by
    definition, and averaging those in reads as a collapse in fill rate.
    """
    if marketplace == "instamart":
        return await instamart_po_service.insights_summary(
            session, tenant_id=tenant_id, start=start, end=end,
            prev_start=prev_start, prev_end=prev_end,
        )
    if marketplace == "zepto":
        return await zepto_po_service.insights_summary(
            session, tenant_id=tenant_id, start=start, end=end,
            prev_start=prev_start, prev_end=prev_end,
        )
    short_value = func.sum(
        BlinkitPOItem.remaining_quantity
        * func.coalesce(BlinkitPOItem.landing_rate, BlinkitPOItem.cost_price, 0)
    )
    is_open = BlinkitPO.po_state.in_(OPEN_STATES)

    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(BlinkitPO.total_po_amount), 0.0),
                func.count(func.distinct(BlinkitPO.po_number)).filter(is_open),
                func.count(func.distinct(BlinkitPO.po_number)).filter(~is_open),
            )
            .where(BlinkitPO.tenant_id == tenant_id, *_window(start, end))
        )
    ).one()

    filled = (
        await session.execute(
            select(
                func.coalesce(func.sum(BlinkitPO.total_units_ordered), 0),
                func.coalesce(func.sum(BlinkitPO.total_grn_quantity), 0),
                func.count().filter(
                    BlinkitPO.total_grn_quantity < BlinkitPO.total_units_ordered
                ),
            )
            .where(BlinkitPO.tenant_id == tenant_id, ~is_open, *_window(start, end))
        )
    ).one()

    values = (
        await session.execute(
            select(
                func.coalesce(short_value.filter(is_open), 0.0),
                func.coalesce(short_value.filter(~is_open), 0.0),
            )
            .select_from(BlinkitPOItem)
            .join(
                BlinkitPO,
                (BlinkitPO.po_number == BlinkitPOItem.po_number)
                & (BlinkitPO.tenant_id == BlinkitPOItem.tenant_id),
            )
            .where(BlinkitPOItem.tenant_id == tenant_id, *_window(start, end))
        )
    ).one()

    ordered, received, short_pos = filled
    out = POInsightsSummary(
        po_value=round(float(row[0]), 2),
        fill_rate=round(received / ordered, 4) if ordered else None,
        value_at_risk=round(float(values[0]), 2),
        value_missed=round(float(values[1]), 2),
        open_pos=row[1],
        closed_pos=row[2],
        short_pos=short_pos,
    )
    if prev_start and prev_end:
        before = await insights_summary(
            session, tenant_id=tenant_id, start=prev_start, end=prev_end
        )
        out.prev_po_value = before.po_value
        out.prev_fill_rate = before.fill_rate
        out.prev_value_missed = before.value_missed
        out.po_value_delta = _delta(out.po_value, before.po_value)
        out.fill_rate_delta = _delta(out.fill_rate, before.fill_rate)
        out.value_missed_delta = _delta(out.value_missed, before.value_missed)
    return out


async def insights(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    scope: str = "priority",
    search: str | None = None,
    status: str | None = None,
    marketplace: str | None = None,
) -> Page[POInsightRow]:
    """The PO table. `scope="priority"` keeps the POs still worth acting on — open,
    with something undelivered — biggest money first; `"all"` is every PO in the window.
    """
    if marketplace == "instamart":
        return await instamart_po_service.insights(
            session, tenant_id=tenant_id, pagination=pagination, start=start,
            end=end, scope=scope, search=search, status=status,
        )
    if marketplace == "zepto":
        return await zepto_po_service.insights(
            session, tenant_id=tenant_id, pagination=pagination, start=start,
            end=end, scope=scope, search=search, status=status,
        )
    short_units = func.coalesce(func.sum(BlinkitPOItem.remaining_quantity), 0)
    short_value = func.coalesce(
        func.sum(
            BlinkitPOItem.remaining_quantity
            * func.coalesce(BlinkitPOItem.landing_rate, BlinkitPOItem.cost_price, 0)
        ),
        0.0,
    )
    stmt = (
        select(
            BlinkitPO.po_number,
            BlinkitPO.facility_name,
            BlinkitPO.city_name,
            BlinkitPO.po_state,
            BlinkitPO.total_units_ordered,
            BlinkitPO.total_grn_quantity,
            BlinkitPO.total_po_amount,
            BlinkitPO.issue_date,
            BlinkitPO.delivery_date,
            BlinkitPO.schedule_date,
            BlinkitPO.expiry_date,
            func.count(BlinkitPOItem.id),
            func.count(BlinkitPOItem.id).filter(BlinkitPOItem.remaining_quantity > 0),
            short_units,
            short_value,
        )
        .select_from(BlinkitPO)
        .join(
            BlinkitPOItem,
            (BlinkitPOItem.po_number == BlinkitPO.po_number)
            & (BlinkitPOItem.tenant_id == BlinkitPO.tenant_id),
        )
        .where(BlinkitPO.tenant_id == tenant_id, *_window(start, end))
        .group_by(BlinkitPO.po_number, BlinkitPO.facility_name, BlinkitPO.city_name,
                  BlinkitPO.po_state, BlinkitPO.total_units_ordered,
                  BlinkitPO.total_grn_quantity, BlinkitPO.total_po_amount,
                  BlinkitPO.issue_date, BlinkitPO.delivery_date,
                  BlinkitPO.schedule_date, BlinkitPO.expiry_date)
    )
    if search:
        stmt = stmt.where(BlinkitPO.po_number.ilike(f"%{search.strip()}%"))
    if status:
        # "open" and "closed" group the marketplace's own words; anything else is one
        # of those words, matched as given.
        if status == "open":
            stmt = stmt.where(BlinkitPO.po_state.in_(OPEN_STATES))
        elif status == "closed":
            stmt = stmt.where(BlinkitPO.po_state.notin_(OPEN_STATES))
        else:
            stmt = stmt.where(BlinkitPO.po_state == status)
    if scope == "priority":
        stmt = stmt.where(BlinkitPO.po_state.in_(OPEN_STATES)).having(short_units > 0)

    rows = (await session.execute(stmt)).all()

    out = []
    today = date.today()
    for (po, facility, city, state, ordered, received, amount, issued, delivery,
         slot, expiry, lines, short_lines, s_units, s_value) in rows:
        ordered, received = ordered or 0, received or 0
        open_po = state in OPEN_STATES
        expiry_date = expiry.date() if expiry else None
        out.append(
            POInsightRow(
                po_number=po,
                facility_name=facility,
                city_name=city,
                po_state=state,
                is_open=open_po,
                priority=_priority(float(s_value), open_po),
                lines=lines,
                short_lines=short_lines,
                units_ordered=ordered,
                units_received=received,
                fill_rate=round(received / ordered, 4) if ordered and not open_po else None,
                po_amount=amount,
                undelivered_value=round(float(s_value), 2),
                delivery_days=(delivery.date() - issued.date()).days
                if delivery and issued else None,
                issue_date=issued.date() if issued else None,
                delivery_date=delivery.date() if delivery else None,
                schedule_date=slot,
                expiry_date=expiry_date,
                days_to_expiry=(expiry_date - today).days if expiry_date else None,
                # A PO with stock still owed and no slot in the diary: the deadline is
                # running and nothing is booked against it.
                needs_booking=bool(open_po and s_units and slot is None),
            )
        )

    # POs that can still be acted on (open, something undelivered) sit above settled
    # ones, then unbooked before booked, then the money.
    # Unbooked first inside the actionable group: value can be chased any day this
    # week, a missing slot cannot.
    out.sort(
        key=lambda r: (
            0 if (r.is_open and r.undelivered_value > 0) else 1,
            0 if r.needs_booking else 1,
            -r.undelivered_value,
            -(r.issue_date.toordinal() if r.issue_date else 0),
        )
    )
    total = len(out)
    page = out[pagination.offset : pagination.offset + pagination.limit]
    return Page.build(page, total, pagination)


async def sku_insights(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    pagination: Pagination,
    start: date,
    end: date,
    search: str | None = None,
    marketplace: str | None = None,
) -> Page[POSkuRow]:
    """The same shortfall, read per SKU instead of per PO — which products Blinkit
    keeps ordering and not receiving, across every warehouse in the window.

    Open and settled value stay apart: one is still to come, the other is gone.
    """
    if marketplace == "instamart":
        return await instamart_po_service.sku_insights(
            session, tenant_id=tenant_id, pagination=pagination, start=start,
            end=end, search=search,
        )
    if marketplace == "zepto":
        return await zepto_po_service.sku_insights(
            session, tenant_id=tenant_id, pagination=pagination, start=start,
            end=end, search=search,
        )
    is_open = BlinkitPO.po_state.in_(OPEN_STATES)
    short_value = BlinkitPOItem.remaining_quantity * func.coalesce(
        BlinkitPOItem.landing_rate, BlinkitPOItem.cost_price, 0
    )
    # Fill rate is a closed-PO measure: an open PO has received nothing yet.
    closed_ordered = func.sum(BlinkitPOItem.units_ordered).filter(~is_open)
    closed_short = func.sum(BlinkitPOItem.remaining_quantity).filter(~is_open)

    stmt = (
        select(
            BlinkitPOItem.item_id,
            func.max(BlinkitPOItem.name),
            func.coalesce(func.sum(BlinkitPOItem.units_ordered), 0),
            func.coalesce(func.sum(BlinkitPOItem.remaining_quantity), 0),
            func.coalesce(func.sum(short_value), 0.0),
            func.coalesce(func.sum(short_value).filter(is_open), 0.0),
            func.coalesce(func.sum(short_value).filter(~is_open), 0.0),
            func.count(func.distinct(BlinkitPOItem.po_number)),
            func.count(func.distinct(BlinkitPOItem.po_number)).filter(
                BlinkitPOItem.remaining_quantity > 0
            ),
            func.count(func.distinct(BlinkitPO.city_name)),
            func.max(BlinkitPO.issue_date),
            func.coalesce(closed_ordered, 0),
            func.coalesce(closed_short, 0),
        )
        .select_from(BlinkitPOItem)
        .join(
            BlinkitPO,
            (BlinkitPO.po_number == BlinkitPOItem.po_number)
            & (BlinkitPO.tenant_id == BlinkitPOItem.tenant_id),
        )
        .where(BlinkitPOItem.tenant_id == tenant_id, *_window(start, end))
        .group_by(BlinkitPOItem.item_id)
    )
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            BlinkitPOItem.name.ilike(term) | BlinkitPOItem.item_id.ilike(term)
        )

    rows = (await session.execute(stmt)).all()

    out = [
        POSkuRow(
            item_id=item_id,
            name=name,
            units_ordered=ordered,
            units_short=short,
            fill_rate=round((c_ordered - c_short) / c_ordered, 4) if c_ordered else None,
            undelivered_value=round(float(value), 2),
            open_value=round(float(open_value), 2),
            missed_value=round(float(missed_value), 2),
            po_count=pos,
            short_po_count=short_pos,
            cities=cities,
            last_ordered=last.date() if last else None,
        )
        for (item_id, name, ordered, short, value, open_value, missed_value, pos,
             short_pos, cities, last, c_ordered, c_short) in rows
    ]
    out.sort(key=lambda r: -r.undelivered_value)
    return Page.build(
        out[pagination.offset : pagination.offset + pagination.limit],
        len(out),
        pagination,
    )
