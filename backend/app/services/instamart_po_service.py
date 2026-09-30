"""Instamart-side reads for the dedicated Purchase Orders page.

Mirrors `po_service.py`'s three main functions (`insights_summary`,
`insights`, `sku_insights`) against `instamart_po`/`instamart_po_item`
instead of `blinkit_pos`/`blinkit_po_items`. `_priority()` and `_delta()` are
imported from `po_service` rather than re-implemented — they're pure
functions with no Blinkit-specific assumption in them.

TWO THINGS BLINKIT HAS THAT INSTAMART'S PO DATA STILL DOESN'T
================================================================
(A third — a booking-slot concept — was believed missing here too, but
`searchPurchaseOrder` was carrying `appointment_start_date` the whole time;
the field just wasn't parsed. Confirmed live 2026-09-28 by capturing the
Supply Portal's own "PO Booking" tab, whose "Schedule" action turned out to
be reading and writing this same endpoint's response, not a separate one.
`schedule_date`/`needs_booking` below are now real, mirroring Blinkit's.)

1. **A separate delivery date.** Blinkit tracks `delivery_date` distinctly
   from `issue_date`, so `delivery_days` is a real lead-time figure. Instamart
   only has `po_date` (raised) and `completed_date` (set once, on full
   completion) — no per-PO "when this actually arrived" date, so
   `delivery_days` stays null throughout. `appointment_start_date` is the
   PLANNED slot, not an arrival event, so it doesn't fill this gap either.
2. **A city field.** Blinkit's PO carries `city_name` separately from
   `facility_name`; Instamart's doesn't, so `city_name` is always null and
   the SKU table's `cities` count is always 0.

Per-unit cost is DERIVED, not stored — see `app/models/instamart_po.py`:
`instamart_po_item.line_cost_excluding_tax` is a LINE TOTAL despite its API
name, so every shortfall-value calculation here divides it by `qty` first.

OPEN VS CLOSED
==============
Verified live 2026-09-25 against the real scraped account: of 2053 saved
POs, the `status` values actually present are STATUS_COMPLETED (1864),
STATUS_EXPIRED (170), STATUS_CANCELLED (12), STATUS_CONFIRMED (7 — 6 not yet
received, 1 partially). Only STATUS_CONFIRMED represents a PO still awaiting
fulfillment; the other three are all settled, one way or another — matching
Blinkit's "anything not open is settled" split.

⚠️ `instamart_po_item.pending_qty` IS NOT TRUSTWORTHY ONCE A PO CLOSES
==========================================================================
Verified live 2026-09-25: for every one of the 675 closed POs (COMPLETED /
EXPIRED / CANCELLED) whose HEADER shows a real shortfall
(`grn_quantity < total_quantity`), EVERY line's `pending_qty` is 0 — 675/675,
no exceptions. Instamart resets it to 0 once a PO settles, regardless of
whether the full quantity was ever received. The header fields
(`total_quantity`, `grn_quantity`) stay correct historically; only the LINE
detail is lost.

For an OPEN po (STATUS_CONFIRMED), by contrast, `pending_qty` is real and
granular — checked HDFPO10795 (header short by 7 units): its 4 lines split
that unevenly (2, 3, 0, 2), not proportionally to each line's `qty`, so it
carries real information a proportional guess would destroy.

So `_line_short_qty()` below is a per-status split: trust `pending_qty`
directly while a PO is open, and for a closed PO fall back to allocating the
header's shortfall across lines by each line's share of `qty` — an
estimate, not the real distribution, but the only thing recoverable once
Instamart has thrown the line-level detail away.

⚠️ `instamart_po.po_date` IS NOT "WHEN THIS PO WAS RAISED"
==========================================================================
Verified live 2026-09-25 against all 2053 scraped POs: `po_date` is
EXACTLY one calendar day behind `created_at` (IST), 100% of the time, no
exceptions — a real Instamart business field (likely a batch/cutoff date),
not a wall-clock timestamp, and not what a human means by "when this PO was
created." A user cross-checked our "16 Sept" filter against Instamart's own
bulk-export CSV: POs we showed as raised on 16 Sept had `PoCreatedAt` of 17
Sept, and 4 genuinely-16-Sept POs were missing entirely. `created_at` (the
API's actual creation timestamp, converted to IST) is what matches the
portal's own `PoCreatedAt` column — `_RAISED_DATE` below is that conversion,
used everywhere this module answers "what date was this PO raised."
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import Pagination
from app.models.instamart_po import InstamartPO, InstamartPOItem
from app.schemas.common import Page
from app.schemas.purchase_order import POInsightRow, POInsightsSummary, POSkuRow

# Deferred: po_service imports this module for dispatch, so importing it back
# at module load time would be circular. `_delta`/`_priority` are pure
# functions with no Blinkit-specific assumption, reused rather than duplicated.

OPEN_STATES = ("STATUS_CONFIRMED",)

# A unit's per-line cost, derived from the LINE TOTAL every query needs this for.
_UNIT_COST = InstamartPOItem.line_cost_excluding_tax / func.nullif(InstamartPOItem.qty, 0)

# The calendar date this PO was actually raised, in IST — see the module
# docstring's warning on why this is `created_at` (UTC, offset-adjusted) and
# NOT `po_date`. Skipping the offset would put anything created after
# 18:30 UTC (00:00 IST) a day early.
_IST_OFFSET = timedelta(hours=5, minutes=30)
_RAISED_DATE = cast(InstamartPO.created_at + _IST_OFFSET, Date)

# Three-tier fallback, best source first: (1) `received_qty` from the bulk
# CSV export (real, per-line, survives a PO closing — populated by a
# separate scrape step, see InstamartPOItem's docstring; null until synced),
# (2) `pending_qty` while the PO is still open (real and granular then), (3)
# a proportional share of the header's shortfall once closed with no export
# data yet — an estimate, not the real distribution.
_LINE_SHORT_QTY = case(
    (InstamartPOItem.received_qty.isnot(None),
     InstamartPOItem.qty - InstamartPOItem.received_qty),
    (InstamartPO.status.in_(OPEN_STATES), InstamartPOItem.pending_qty),
    else_=(
        InstamartPOItem.qty
        * (InstamartPO.total_quantity - InstamartPO.grn_quantity)
        / func.nullif(InstamartPO.total_quantity, 0)
    ),
)


def _window(start: date, end: date):
    return [_RAISED_DATE >= start, _RAISED_DATE <= end]


async def insights_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    prev_start: date | None = None,
    prev_end: date | None = None,
) -> POInsightsSummary:
    is_open = InstamartPO.status.in_(OPEN_STATES)
    short_value = func.sum(_LINE_SHORT_QTY * _UNIT_COST)

    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(InstamartPO.value), 0.0),
                func.count(func.distinct(InstamartPO.purchase_order_id)).filter(is_open),
                func.count(func.distinct(InstamartPO.purchase_order_id)).filter(~is_open),
            ).where(InstamartPO.tenant_id == tenant_id, *_window(start, end))
        )
    ).one()

    filled = (
        await session.execute(
            select(
                func.coalesce(func.sum(InstamartPO.total_quantity), 0),
                func.coalesce(func.sum(InstamartPO.grn_quantity), 0),
                func.count().filter(InstamartPO.grn_quantity < InstamartPO.total_quantity),
            ).where(InstamartPO.tenant_id == tenant_id, ~is_open, *_window(start, end))
        )
    ).one()

    values = (
        await session.execute(
            select(
                func.coalesce(short_value.filter(is_open), 0.0),
                func.coalesce(short_value.filter(~is_open), 0.0),
            )
            .select_from(InstamartPOItem)
            .join(
                InstamartPO,
                (InstamartPO.purchase_order_id == InstamartPOItem.purchase_order_id)
                & (InstamartPO.tenant_id == InstamartPOItem.tenant_id),
            )
            .where(
                InstamartPOItem.tenant_id == tenant_id,
                InstamartPOItem.qty > 0,
                *_window(start, end),
            )
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
    short_units = func.coalesce(func.sum(_LINE_SHORT_QTY), 0)
    short_value = func.coalesce(func.sum(_LINE_SHORT_QTY * _UNIT_COST), 0.0)
    stmt = (
        select(
            InstamartPO.purchase_order_id,
            InstamartPO.facility_name,
            InstamartPO.status,
            InstamartPO.total_quantity,
            InstamartPO.grn_quantity,
            InstamartPO.value,
            _RAISED_DATE,
            InstamartPO.expiry_date,
            InstamartPO.appointment_start_date,
            func.count(InstamartPOItem.id),
            func.count(InstamartPOItem.id).filter(_LINE_SHORT_QTY > 0),
            short_units,
            short_value,
        )
        .select_from(InstamartPO)
        .join(
            InstamartPOItem,
            (InstamartPOItem.purchase_order_id == InstamartPO.purchase_order_id)
            & (InstamartPOItem.tenant_id == InstamartPO.tenant_id),
        )
        .where(InstamartPO.tenant_id == tenant_id, *_window(start, end))
        .group_by(
            InstamartPO.purchase_order_id, InstamartPO.facility_name, InstamartPO.status,
            InstamartPO.total_quantity, InstamartPO.grn_quantity, InstamartPO.value,
            _RAISED_DATE, InstamartPO.expiry_date, InstamartPO.appointment_start_date,
        )
    )
    if search:
        stmt = stmt.where(InstamartPO.purchase_order_id.ilike(f"%{search.strip()}%"))
    if status:
        if status == "open":
            stmt = stmt.where(InstamartPO.status.in_(OPEN_STATES))
        elif status == "closed":
            stmt = stmt.where(InstamartPO.status.notin_(OPEN_STATES))
        else:
            stmt = stmt.where(InstamartPO.status == status)
    if scope == "priority":
        stmt = stmt.where(InstamartPO.status.in_(OPEN_STATES)).having(short_units > 0)

    rows = (await session.execute(stmt)).all()

    from app.services.po_service import _priority

    out = []
    today = date.today()
    for (po, facility, state, ordered, received, amount, issued, expiry, slot,
         lines, short_lines, s_units, s_value) in rows:
        ordered, received = ordered or 0, received or 0
        open_po = state in OPEN_STATES
        out.append(
            POInsightRow(
                po_number=po,
                facility_name=facility,
                city_name=None,
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
                delivery_days=None,  # still no separate delivery-EVENT date in this data
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
    is_open = InstamartPO.status.in_(OPEN_STATES)
    short_value = _LINE_SHORT_QTY * _UNIT_COST
    closed_ordered = func.sum(InstamartPOItem.qty).filter(~is_open)
    closed_short = func.sum(_LINE_SHORT_QTY).filter(~is_open)
    # Units still owed on OPEN POs — not a shortfall yet, since the PO hasn't
    # closed. Same "not due" concept as Blinkit's open_units.
    open_units = func.sum(_LINE_SHORT_QTY).filter(is_open)

    stmt = (
        select(
            InstamartPOItem.external_item_code,
            func.max(InstamartPOItem.description),
            func.coalesce(func.sum(InstamartPOItem.qty), 0),
            func.coalesce(func.sum(_LINE_SHORT_QTY), 0),
            func.coalesce(func.sum(short_value), 0.0),
            func.coalesce(func.sum(short_value).filter(is_open), 0.0),
            func.coalesce(func.sum(short_value).filter(~is_open), 0.0),
            func.count(func.distinct(InstamartPOItem.purchase_order_id)),
            func.count(func.distinct(InstamartPOItem.purchase_order_id)).filter(
                _LINE_SHORT_QTY > 0
            ),
            func.max(_RAISED_DATE),
            func.coalesce(closed_ordered, 0),
            func.coalesce(closed_short, 0),
            func.coalesce(open_units, 0),
            func.count(func.distinct(InstamartPOItem.purchase_order_id)).filter(is_open),
        )
        .select_from(InstamartPOItem)
        .join(
            InstamartPO,
            (InstamartPO.purchase_order_id == InstamartPOItem.purchase_order_id)
            & (InstamartPO.tenant_id == InstamartPOItem.tenant_id),
        )
        .where(
            InstamartPOItem.tenant_id == tenant_id,
            InstamartPOItem.qty > 0,
            *_window(start, end),
        )
        .group_by(InstamartPOItem.external_item_code)
    )
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            InstamartPOItem.description.ilike(term)
            | InstamartPOItem.external_item_code.ilike(term)
        )

    rows = (await session.execute(stmt)).all()

    out = [
        POSkuRow(
            item_id=item_id,
            name=name,
            units_ordered=ordered,
            # short (and c_short below) can be fractional now: closed POs'
            # shortfall is a proportional estimate, not a whole-unit count.
            units_short=round(float(short or 0)),
            units_not_due=round(float(not_due or 0)),
            units_received=max(0, round(float(c_ordered or 0) - float(c_short or 0))),
            fill_rate=round((c_ordered - c_short) / c_ordered, 4) if c_ordered else None,
            undelivered_value=round(float(value), 2),
            open_value=round(float(open_value), 2),
            missed_value=round(float(missed_value), 2),
            po_count=pos,
            open_po_count=open_pos,
            short_po_count=short_pos,
            cities=0,  # no city data for Instamart
            last_ordered=last,
        )
        for (item_id, name, ordered, short, value, open_value, missed_value,
             pos, short_pos, last, c_ordered, c_short, not_due, open_pos) in rows
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
            select(InstamartPO).where(
                InstamartPO.tenant_id == tenant_id,
                InstamartPO.purchase_order_id == po_number,
            )
        )
    ).scalar_one_or_none()
    if not po:
        return None
    items = (
        await session.execute(
            select(InstamartPOItem).where(
                InstamartPOItem.tenant_id == tenant_id,
                InstamartPOItem.purchase_order_id == po_number,
            )
        )
    ).scalars().all()
    return PODetailOut(
        po_number=po.purchase_order_id,
        po_state=po.status,
        facility_name=po.facility_name,
        vendor_name=po.vendor_name,
        # created_at (IST), not po_date — see module docstring's warning.
        issue_date=(po.created_at + _IST_OFFSET) if po.created_at else None,
        expiry_date=po.expiry_date,
        total_units_ordered=po.total_quantity,
        item_count=len(items),
        total_grn_quantity=po.grn_quantity,
        total_po_amount=po.value,
        created_at=po.created_at,
        scraped_at=po.scraped_at,
        items=[
            POItemOut(
                po_number=po.purchase_order_id,
                item_id=it.external_item_code,
                name=it.description,
                units_ordered=it.qty,
                remaining_quantity=it.pending_qty,
                cost_price=(
                    round(it.line_cost_excluding_tax / it.qty, 4)
                    if it.line_cost_excluding_tax is not None and it.qty
                    else None
                ),
                mrp=it.mrp,
            )
            for it in items
        ],
    )
