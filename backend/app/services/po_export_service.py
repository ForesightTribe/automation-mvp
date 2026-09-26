"""Downloading the purchase-order section — the same numbers, as an .xlsx.

Every figure comes from `po_service`, the code that feeds the screen, so a downloaded
file cannot disagree with the table it was downloaded from.

Two sheets, because the section has two views: POs, and the same shortfall per SKU.
Undelivered value is split into "still to come" (the PO is open) and "missed" (the PO
closed short) wherever it appears — one is a forecast, the other is a loss.
"""
import uuid
from datetime import date
from tempfile import mkdtemp

from sqlalchemy.ext.asyncio import AsyncSession

from exports.workbook import write_workbook
from app.dependencies import Pagination
from app.schemas.exports import Column, Kpi, Report, Section
from app.services import po_service

# Everything, not just the page the reader is on: a download is for working through.
ALL = Pagination(page=1, limit=100_000)


def _po_section(
    rows, summary, start: date, end: date, scope: str, status: str | None = None
) -> Section:
    columns = [
        Column(key="po_number", header="PO Number", type="id", width=18),
        Column(key="facility_name", header="Warehouse", type="text", width=34),
        Column(key="city_name", header="City", type="text"),
        Column(key="po_state", header="Status", type="text"),
        Column(key="priority", header="Priority", type="text",
               help="High is ₹50,000 or more undelivered on a PO that is still open."),
        Column(key="units_ordered", header="Units Ordered", type="count"),
        Column(key="units_received", header="Units Received", type="count"),
        Column(key="short_lines", header="SKUs Short", type="count"),
        Column(key="lines", header="SKUs On PO", type="count"),
        Column(key="fill_rate", header="Fill Rate", type="pct", emphasis="good_high",
               help="Received ÷ ordered. Blank while the PO is still open."),
        Column(key="po_amount", header="PO Value", type="money"),
        Column(key="open_value", header="Still To Come", type="money",
               help="Undelivered value on a PO that is still open."),
        Column(key="missed_value", header="Missed", type="money", emphasis="bar",
               help="Undelivered value on a PO that closed short."),
        Column(key="delivery_days", header="Delivery Window (days)", type="count"),
        Column(key="slot", header="Delivery Slot", type="text",
               help="The booked appointment. 'Not booked' means an open PO with stock "
                    "still owed and no slot in the diary."),
        Column(key="issue_date", header="Raised", type="date"),
        Column(key="delivery_date", header="Due", type="date"),
        Column(key="expiry_date", header="Expires", type="date"),
    ]
    out = [
        {
            "po_number": r.po_number,
            "facility_name": r.facility_name,
            "city_name": r.city_name,
            "po_state": r.po_state,
            "priority": r.priority.title(),
            "units_ordered": r.units_ordered,
            "units_received": r.units_received,
            "short_lines": r.short_lines,
            "lines": r.lines,
            "fill_rate": r.fill_rate,
            "po_amount": r.po_amount,
            "open_value": r.undelivered_value if r.is_open else None,
            "missed_value": None if r.is_open else r.undelivered_value,
            "delivery_days": r.delivery_days,
            "slot": r.schedule_date.strftime("%d %b %Y, %H:%M")
            if r.schedule_date
            else ("Not booked" if r.needs_booking else None),
            "issue_date": r.issue_date,
            "delivery_date": r.delivery_date,
            "expiry_date": r.expiry_date,
        }
        for r in rows
    ]
    scope_label = (
        "Open POs with something still undelivered"
        if scope == "priority"
        else "Every PO raised in the window"
    )
    if status:
        scope_label += f" · {status}"
    return Section(
        key="purchase_orders",
        title="Purchase Orders",
        description="What Blinkit ordered, what arrived, and what is still undelivered.",
        context=f"{start:%d %b %Y} to {end:%d %b %Y} · {scope_label} · {len(out)} POs",
        kpis=[
            Kpi(label="PO Value", value=summary.po_value, type="money",
                detail=f"{summary.open_pos + summary.closed_pos} POs raised"),
            Kpi(label="Fill Rate", value=summary.fill_rate, type="pct",
                detail=f"{summary.closed_pos} closed POs, {summary.short_pos} filled short"),
            Kpi(label="Still To Come", value=summary.value_at_risk, type="money",
                detail=f"{summary.open_pos} POs still open"),
            Kpi(label="Missed", value=summary.value_missed, type="money",
                detail="Short units × landing rate, closed POs"),
        ],
        columns=columns,
        rows=out,
        notes=[
            "Undelivered value is short units × landing rate.",
            "Fill rate counts closed POs only — an open PO has received nothing yet.",
            "'Not booked' POs have stock owed and no delivery slot; they are listed first.",
        ],
    )


def _sku_section(rows, start: date, end: date) -> Section:
    columns = [
        Column(key="name", header="SKU", type="text", width=44),
        Column(key="item_id", header="Item ID", type="id"),
        Column(key="units_ordered", header="Units Ordered", type="count"),
        Column(key="units_short", header="Units Short", type="count"),
        Column(key="fill_rate", header="Fill Rate", type="pct", emphasis="good_high"),
        Column(key="open_value", header="Still To Come", type="money"),
        Column(key="missed_value", header="Missed", type="money", emphasis="bar"),
        Column(key="short_po_count", header="POs Short", type="count"),
        Column(key="po_count", header="POs", type="count"),
        Column(key="cities", header="Cities", type="count"),
        Column(key="last_ordered", header="Last Ordered", type="date"),
    ]
    return Section(
        key="po_skus",
        title="Shortfall by SKU",
        description="The same shortfall per product, across every PO in the window.",
        context=f"{start:%d %b %Y} to {end:%d %b %Y} · {len(rows)} SKUs",
        columns=columns,
        rows=[r.model_dump() for r in rows],
        notes=["Sorted by undelivered value, worst first."],
    )


async def build_file(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    scope: str = "priority",
    status: str | None = None,
    client_name: str | None = None,
    marketplace: str | None = None,
) -> tuple[str, str]:
    """Render the purchase-order section to an .xlsx. Returns (path, filename)."""
    summary = await po_service.insights_summary(
        session, tenant_id=tenant_id, start=start, end=end, marketplace=marketplace,
    )
    pos = await po_service.insights(
        session, tenant_id=tenant_id, pagination=ALL, start=start, end=end,
        scope=scope, status=status, marketplace=marketplace,
    )
    skus = await po_service.sku_insights(
        session, tenant_id=tenant_id, pagination=ALL, start=start, end=end,
        marketplace=marketplace,
    )
    if not pos.items and not skus.items:
        raise ValueError("No purchase orders in that window.")

    report = Report(
        title="Purchase Orders",
        subtitle=f"{client_name or ''} · {start:%d %b %Y} to {end:%d %b %Y}".strip(" ·"),
        sections=[
            _po_section(pos.items, summary, start, end, scope, status),
            _sku_section(skus.items, start, end),
        ],
        filename_stem="purchase_orders",
    )
    name = f"Purchase_Orders_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}.xlsx"
    path = f"{mkdtemp(prefix='po-export-')}/{name}"
    write_workbook(report, path)
    return path, name
