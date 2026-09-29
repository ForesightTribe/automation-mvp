from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PurchaseOrderOut(BaseModel):
    """PO header (list view)."""
    model_config = ConfigDict(from_attributes=True)

    po_number: str
    po_state: str | None = None
    vendor_id: str | None = None
    vendor_name: str | None = None
    manufacturer_id: str | None = None
    manufacturer_name: str | None = None
    facility_id: str | None = None
    facility_name: str | None = None
    city_name: str | None = None
    outlet_id: str | None = None
    po_type_id: str | None = None
    address: str | None = None
    issue_date: datetime | None = None
    expiry_date: datetime | None = None
    delivery_date: datetime | None = None
    schedule_date: datetime | None = None
    scheduled_on: datetime | None = None
    total_units_ordered: int | None = None
    item_count: int | None = None
    total_grn_quantity: int | None = None
    total_po_amount: float | None = None
    multiple_grn: int | None = None
    load_size: int | None = None
    active: bool | None = None
    download_url: str | None = None
    po_excel_report_url: str | None = None
    grn_report_excel_url: str | None = None
    pm_name: str | None = None
    pm_phone: str | None = None
    pm_email: str | None = None
    entity_vendor_cin: str | None = None
    entity_vendor_legal_name: str | None = None
    delivery_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    scraped_at: datetime


class POItemOut(BaseModel):
    """PO line item."""
    model_config = ConfigDict(from_attributes=True)

    po_number: str
    line_id: str | None = None
    item_id: str
    upc: str | None = None
    name: str | None = None
    uom_text: str | None = None
    variant_id: str | None = None
    units_ordered: int | None = None
    remaining_quantity: int | None = None
    cost_price: float | None = None
    landing_rate: float | None = None
    mrp: float | None = None
    margin_percentage: float | None = None
    total_amount: float | None = None
    tax_value: float | None = None
    cgst_value: float | None = None
    sgst_value: float | None = None
    igst_value: float | None = None
    cess_value: float | None = None
    bucket_type: str | None = None
    created_at: datetime | None = None


class PODetailOut(PurchaseOrderOut):
    """PO header with its line items (detail view)."""
    items: list[POItemOut] = []
    # Whether the delivery window is still open. Carried so clients need not
    # re-derive the open set from `po_state`.
    is_open: bool = False


class POSnapshotOut(BaseModel):
    """Windowed PO summary counts."""
    model_config = ConfigDict(from_attributes=True)

    window_start: date
    scraped_at: datetime
    total_raised: int | None = None
    scheduled: int | None = None
    created: int | None = None
    cancelled: int | None = None
    expired_unfulfilled: int | None = None
    expired_partial: int | None = None
    po_amount: float | None = None
    items_delivered: int | None = None


class POStateCount(BaseModel):
    """One state an open PO can sit in, with what it is worth.

    `Scheduled` means a delivery slot exists; `Unscheduled` means the PO is live
    and nobody has booked one. That difference is the whole reason this is
    reported separately from the single open figure.
    """

    state: str
    pos: int
    value: float
    overdue: int  # of those, how many are past their expiry date


class POInsightsSummary(BaseModel):
    """The headline figures above the PO table, for one reporting window.

    `prev_*` repeat them for the window of equal length immediately before, and
    `*_delta` is the change as a fraction (0.12 = up 12%). A delta is None where it
    cannot be stated: no earlier figure, or a fill rate with no closed POs behind it.
    """

    po_value: float
    fill_rate: float | None          # received ÷ ordered, closed POs only
    value_at_risk: float             # undelivered value on POs still open
    value_missed: float              # undelivered value on POs that closed short
    open_pos: int
    closed_pos: int
    short_pos: int                   # closed POs that were not filled in full
    # The open figure split by the state the marketplace has each PO in.
    open_states: list[POStateCount] = []

    # `value_at_risk` has no comparison: it counts what is open RIGHT NOW, and an
    # older window's figure decays to nothing as its POs close.
    prev_po_value: float | None = None
    prev_fill_rate: float | None = None
    prev_value_missed: float | None = None

    po_value_delta: float | None = None
    fill_rate_delta: float | None = None
    value_missed_delta: float | None = None


class POInsightRow(BaseModel):
    """One PO as the insights table shows it."""

    po_number: str
    facility_name: str | None = None
    city_name: str | None = None
    po_state: str | None = None
    is_open: bool
    priority: str                    # high | medium | low
    lines: int
    short_lines: int
    units_ordered: int
    units_received: int
    fill_rate: float | None
    po_amount: float | None
    undelivered_value: float         # short units × landing rate
    delivery_days: int | None        # issue → delivery
    issue_date: date | None
    delivery_date: date | None
    schedule_date: datetime | None = None   # the booked delivery slot, if one exists
    expiry_date: date | None = None
    days_to_expiry: int | None = None       # from today; negative once past
    needs_booking: bool = False             # open, still undelivered, no slot booked


class POSkuRow(BaseModel):
    """One SKU across every PO in the window."""

    item_id: str
    name: str | None = None
    units_ordered: int
    # Scoped to settled POs, like `fill_rate` beside it. Units on open POs are
    # `units_not_due`: not a shortfall until their PO closes.
    units_short: int
    units_not_due: int               # remaining on OPEN POs — not yet a shortfall
    units_received: int              # ordered − remaining, settled POs only
    fill_rate: float | None          # received ÷ ordered, closed POs only
    # Rate of sale and cover, from the sales and stock feeds rather than the PO
    # feed. `doi_days` reads the LATEST stock snapshot, so it answers "how long
    # does today's stock last" and does not move with the date picker.
    drr: float | None = None         # units sold per day over the window
    doi_days: float | None = None    # (frontend + backend stock) ÷ drr
    undelivered_value: float
    open_value: float                # of that, still to come
    missed_value: float              # of that, already lost
    po_count: int
    # A SKU spans many POs, so it has no single state. What it has is a split:
    # how many of its POs are still open, against how many have settled.
    open_po_count: int
    short_po_count: int
    cities: int
    last_ordered: date | None = None
