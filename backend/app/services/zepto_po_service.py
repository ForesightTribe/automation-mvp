"""Zepto-side reads for the dedicated Purchase Orders page.

Mirrors `po_service.py`'s four main functions (`insights_summary`, `insights`,
`sku_insights`, `get_po`) against `zepto_po`/`zepto_po_items` instead of
`blinkit_pos`/`blinkit_po_items`. `_priority()`/`_delta()` are imported from
`po_service` rather than re-implemented — pure functions, no Blinkit-specific
assumption in them.

WHY THIS READS FROM zepto_po_items, NOT zepto_po's OWN COLUMNS
================================================================
Verified live 2026-09-29 against the real scraped account (447 POs, this
tenant): `zepto_po.total_grn_qty` and `total_asn_qty` are NULL on every single
row, every status, no exceptions — the `/api/v1/po/filter` list endpoint never
actually returns them, despite the columns existing on the model. `total_qty`
and `total_value` ARE real and match the sum of their line items exactly
(spot-checked 3 POs, unit-for-unit). So "ordered"/"received"/"outstanding"
here are always computed from `zepto_po_items`' `po_qty`/`grn_qty`/
`remaining_qty`, never from the header — the opposite of Blinkit, whose
header totals are the trustworthy source.

WHY `remaining_qty`/`grn_qty` FALL BACK TO `po_qty`/0 WHEN NULL
================================================================
Verified live 2026-09-29: `grn_qty` and `remaining_qty` are null TOGETHER, and
only on lines belonging to POs that haven't reached a GRN step yet —
PENDING_ACKNOWLEDGEMENT, PO_ACKNOWLEDGED, PENDING_ASN_CREATION, ASN_CREATED,
and PENDING_GRN (100% of that tenant's PENDING_GRN and EXPIRED lines were
null; 0% of GRN_DONE's). Nothing has arrived yet in that state, so treating
the whole line as still outstanding (`remaining = po_qty`, `received = 0`)
matches reality rather than guessing. A small slice of COMPLETED POs (73 of
1701 lines, ~4%, this tenant) also carry a null `grn_qty` despite the PO being
closed — an apparent gap on Zepto's own side, not something recoverable here;
the same fallback applies and slightly overstates those specific lines'
shortfall.

OPEN VS CLOSED
================================================================
Verified live 2026-09-29 against the full account history: `status` moves
through PENDING_ACKNOWLEDGEMENT -> PO_ACKNOWLEDGED -> PENDING_ASN_CREATION ->
ASN_CREATED -> PENDING_GRN -> GRN_DONE -> COMPLETED, or EXPIRED if it lapses
first. Only COMPLETED and EXPIRED are terminal; everything else is still
open/in-flight — matching Blinkit's "anything not open is settled" split.

Per-unit cost IS stored directly (`unit_price`), unlike Instamart's derived
LINE-TOTAL-divided-by-qty — Zepto's own API already reports it per unit
(spot-checked: `po_qty * unit_price == total_value` on every sampled line).
"""
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.zepto_seller import ZeptoPO, ZeptoPOItem
from app.schemas.common import Page
from app.schemas.purchase_order import POInsightRow, POInsightsSummary, POSkuRow

# Deferred: po_service imports this module for dispatch, so importing it back
# at module load time would be circular. `_delta`/`_priority` are pure
# functions with no Blinkit-specific assumption, reused rather than duplicated.

OPEN_STATES = (
    "PENDING_ACKNOWLEDGEMENT", "PO_ACKNOWLEDGED", "PENDING_ASN_CREATION",
    "ASN_CREATED", "PENDING_GRN", "GRN_DONE",
)

# See the module docstring's second section for why these fall back rather
# than reading the raw (frequently null, pre-GRN) columns directly.
_SHORT_QTY = func.coalesce(ZeptoPOItem.remaining_qty, ZeptoPOItem.po_qty)
_RECEIVED_QTY = func.coalesce(ZeptoPOItem.grn_qty, 0)
_UNIT_COST = func.coalesce(ZeptoPOItem.unit_price, 0)


def _window(start: date, end: date):
    return [ZeptoPO.po_date >= start, ZeptoPO.po_date <= end]


async def insights_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date | None = None,
    prev_end: date | None = None,
) -> POInsightsSummary:
    is_open = ZeptoPO.status.in_(OPEN_STATES)
    short_value = _SHORT_QTY * _UNIT_COST

    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(ZeptoPO.total_value), 0.0),
                func.count(func.distinct(ZeptoPO.po_id)).filter(is_open),
                func.count(func.distinct(ZeptoPO.po_id)).filter(~is_open),
            ).where(ZeptoPO.tenant_id == tenant_id, *_window(start, end))
        )
    ).one()

    # Fill rate needs PER-PO ordered/received (a PO is short if ITS OWN lines
    # fell short, not the account-wide total) — a subquery grouped by po_id,
    # closed POs only.
    po_agg = (
        select(
            ZeptoPOItem.po_id.label("po_id"),
            func.sum(ZeptoPOItem.po_qty).label("ordered"),
            func.sum(_RECEIVED_QTY).label("received"),
        )
        .select_from(ZeptoPOItem)
        .join(
            ZeptoPO,
            (ZeptoPO.po_id == ZeptoPOItem.po_id)
            & (ZeptoPO.tenant_id == ZeptoPOItem.tenant_id),
        )
        .where(ZeptoPOItem.tenant_id == tenant_id, ~is_open, *_window(start, end))
        .group_by(ZeptoPOItem.po_id)
        .subquery()
    )
    filled = (
        await session.execute(
            select(
                func.coalesce(func.sum(po_agg.c.ordered), 0),
                func.coalesce(func.sum(po_agg.c.received), 0),
                func.count().filter(po_agg.c.received < po_agg.c.ordered),
            )
        )
    ).one()

    values = (
        await session.execute(
            select(
                func.coalesce(func.sum(short_value).filter(is_open), 0.0),
                func.coalesce(func.sum(short_value).filter(~is_open), 0.0),
            )
            .select_from(ZeptoPOItem)
            .join(
                ZeptoPO,
                (ZeptoPO.po_id == ZeptoPOItem.po_id)
                & (ZeptoPO.tenant_id == ZeptoPOItem.tenant_id),
            )
            .where(ZeptoPOItem.tenant_id == tenant_id, *_window(start, end))
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
        from app.services.po_service import _delta

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
) -> Page[POInsightRow]:
    short_units = func.coalesce(func.sum(_SHORT_QTY), 0)
    short_value = func.coalesce(func.sum(_SHORT_QTY * _UNIT_COST), 0.0)
    stmt = (
        select(
            ZeptoPO.po_id,
            ZeptoPO.location,
            ZeptoPO.city,
            ZeptoPO.status,
            func.sum(ZeptoPOItem.po_qty),
            func.sum(_RECEIVED_QTY),
            ZeptoPO.total_value,
            ZeptoPO.po_date,
            ZeptoPO.scheduled_date,
            ZeptoPO.expiry_date,
            func.count(ZeptoPOItem.id),
            func.count(ZeptoPOItem.id).filter(_SHORT_QTY > 0),
            short_units,
            short_value,
        )
        .select_from(ZeptoPO)
        .join(
            ZeptoPOItem,
            (ZeptoPOItem.po_id == ZeptoPO.po_id)
            & (ZeptoPOItem.tenant_id == ZeptoPO.tenant_id),
        )
        .where(ZeptoPO.tenant_id == tenant_id, *_window(start, end))
        .group_by(
            ZeptoPO.po_id, ZeptoPO.location, ZeptoPO.city, ZeptoPO.status,
            ZeptoPO.total_value, ZeptoPO.po_date, ZeptoPO.scheduled_date,
            ZeptoPO.expiry_date,
        )
    )
    if search:
        stmt = stmt.where(ZeptoPO.po_id.ilike(f"%{search.strip()}%"))
    if status:
        if status == "open":
            stmt = stmt.where(ZeptoPO.status.in_(OPEN_STATES))
        elif status == "closed":
            stmt = stmt.where(ZeptoPO.status.notin_(OPEN_STATES))
        else:
            stmt = stmt.where(ZeptoPO.status == status)
    if scope == "priority":
        stmt = stmt.where(ZeptoPO.status.in_(OPEN_STATES)).having(short_units > 0)

    rows = (await session.execute(stmt)).all()

    from app.services.po_service import _priority

    out = []
    today = date.today()
    for (po, facility, city, state, ordered, received, amount, issued, slot,
         expiry, lines, short_lines, s_units, s_value) in rows:
        ordered, received = ordered or 0, received or 0
        open_po = state in OPEN_STATES
        out.append(
            POInsightRow(
                po_number=po,
                facility_name=facility,
                city_name=city,
                po_state=state,
                is_open=open_po,
                priority=_priority(float(s_value or 0), open_po),
                lines=lines,
                short_lines=short_lines,
                units_ordered=ordered,
                units_received=received,
                fill_rate=round(received / ordered, 4) if ordered and not open_po else None,
                po_amount=amount,
                undelivered_value=round(float(s_value or 0), 2),
                delivery_days=None,  # no separate delivery-EVENT date in this data either
                issue_date=issued,
                delivery_date=None,
                schedule_date=slot,
                expiry_date=expiry,
                days_to_expiry=(expiry - today).days if expiry else None,
                # Same rule as Blinkit's: open, something still owed, no slot booked.
                needs_booking=bool(open_po and s_units and slot is None),
            )
        )

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
) -> Page[POSkuRow]:
    is_open = ZeptoPO.status.in_(OPEN_STATES)
    short_value = _SHORT_QTY * _UNIT_COST
    closed_ordered = func.sum(ZeptoPOItem.po_qty).filter(~is_open)
    closed_short = func.sum(_SHORT_QTY).filter(~is_open)

    stmt = (
        select(
            ZeptoPOItem.sku_code,
            func.max(ZeptoPOItem.sku_name),
            func.coalesce(func.sum(ZeptoPOItem.po_qty), 0),
            func.coalesce(func.sum(_SHORT_QTY), 0),
            func.coalesce(func.sum(short_value), 0.0),
            func.coalesce(func.sum(short_value).filter(is_open), 0.0),
            func.coalesce(func.sum(short_value).filter(~is_open), 0.0),
            func.count(func.distinct(ZeptoPOItem.po_id)),
            func.count(func.distinct(ZeptoPOItem.po_id)).filter(_SHORT_QTY > 0),
            func.count(func.distinct(ZeptoPO.city)),
            func.max(ZeptoPO.po_date),
            func.coalesce(closed_ordered, 0),
            func.coalesce(closed_short, 0),
        )
        .select_from(ZeptoPOItem)
        .join(
            ZeptoPO,
            (ZeptoPO.po_id == ZeptoPOItem.po_id)
            & (ZeptoPO.tenant_id == ZeptoPOItem.tenant_id),
        )
        .where(ZeptoPOItem.tenant_id == tenant_id, *_window(start, end))
        .group_by(ZeptoPOItem.sku_code)
    )
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            ZeptoPOItem.sku_name.ilike(term) | ZeptoPOItem.sku_code.ilike(term)
        )

    rows = (await session.execute(stmt)).all()

    out = [
        POSkuRow(
            item_id=item_id,
            name=name,
            units_ordered=ordered,
            units_short=round(float(short or 0)),
            fill_rate=round((c_ordered - c_short) / c_ordered, 4) if c_ordered else None,
            undelivered_value=round(float(value), 2),
            open_value=round(float(open_value), 2),
            missed_value=round(float(missed_value), 2),
            po_count=pos,
            short_po_count=short_pos,
            cities=cities,
            last_ordered=last,
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


async def get_po(session: AsyncSession, *, tenant_id: uuid.UUID, po_number: str):
    """PO header + line items, for the row drawer. Returns None if not found —
    caller (po_service.get_po) turns that into a 404."""
    from app.schemas.purchase_order import PODetailOut, POItemOut

    po = (
        await session.execute(
            select(ZeptoPO).where(
                ZeptoPO.tenant_id == tenant_id, ZeptoPO.po_id == po_number,
            )
        )
    ).scalar_one_or_none()
    if not po:
        return None
    items = (
        await session.execute(
            select(ZeptoPOItem).where(
                ZeptoPOItem.tenant_id == tenant_id, ZeptoPOItem.po_id == po_number,
            )
        )
    ).scalars().all()
    return PODetailOut(
        po_number=po.po_id,
        po_state=po.status,
        vendor_name=po.vendor,
        facility_name=po.location,
        city_name=po.city,
        issue_date=po.po_date,
        expiry_date=po.expiry_date,
        schedule_date=po.scheduled_date,
        total_units_ordered=po.total_qty,
        item_count=len(items),
        # Header total_grn_qty is always null (see module docstring) — summed
        # from the lines instead.
        total_grn_quantity=sum(it.grn_qty or 0 for it in items),
        total_po_amount=po.total_value,
        scraped_at=po.scraped_at,
        items=[
            POItemOut(
                po_number=po.po_id,
                item_id=it.sku_code,
                name=it.sku_name,
                units_ordered=it.po_qty,
                remaining_quantity=it.remaining_qty if it.remaining_qty is not None else it.po_qty,
                cost_price=it.unit_price,
                mrp=it.mrp,
            )
            for it in items
        ],
    )
