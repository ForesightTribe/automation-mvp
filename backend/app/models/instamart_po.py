"""Instamart Supply Portal (partner.instamart.in/im-vendor) purchase orders.

A DIFFERENT portal from everything else Instamart in this codebase: not the
Brand Portal (`partner.instamart.in/instamart/...`, WASM-signed, the ads/sales
side), but a separate vendor-facing "Supply Portal" at `.../im-vendor/...`,
talking to `picker.swiggy.com` with its own `abacus-token` JWT auth. Same
underlying login (verified: the JWT's `email`/`user_pool` match the Brand
Portal session's), different downstream token and host.

Unlike Zepto (PO / GRN / ASN as three separate documents joined by po_id),
Instamart's `searchPurchaseOrder` puts ordered/pending/received quantities
directly on the PO header row — `grn_quantity` needs no separate receipt
table to compute a fill rate. There is also no ASN equivalent (no ship-vs-
accept split possible here, unlike Zepto's).

⚠️ NO RECEIPT-EVENT TIMESTAMP. Zepto's `zepto_grn.grn_date` is a real event
date per receipt, so its scorecard can bucket by the week something actually
arrived. Instamart's PO only carries `po_date` (raised) and `completed_date`
(set once, when the WHOLE po finishes — never for a partial receipt). There
is no per-quantity received-on date anywhere in `searchPurchaseOrder` or
`listPurchaseOrderLines`. So a scorecard built on this table buckets by
`po_date` (when the order was raised), not receipt date — an honest proxy,
not the same measurement Zepto's is.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class InstamartPO(SQLModel, table=True):
    """One row per purchase order header — ordered/pending/received quantities
    and value already on this one row (see module docstring), replaced whole
    on every scrape (a live PO's `pending_quantity`/`grn_quantity` change as
    it's fulfilled, so this is a current-state snapshot, not an append-only
    log)."""

    __tablename__ = "instamart_po"

    __table_args__ = (
        Index("idx_impo_tenant_po_date", "tenant_id", "po_date"),
        Index("idx_impo_facility", "tenant_id", "facility_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    purchase_order_id: str          # Instamart's own id, e.g. "BLRPO149238"
    facility_name: str | None = None
    vendor_name: str | None = None
    vendor_code: str | None = None

    status: str | None = None                # STATUS_CONFIRMED, STATUS_COMPLETED, ...
    receiving_status: str | None = None       # RECEIVING_STATUS_NOT_RECEIVED / _PARTIALLY_RECEIVED / _INVALID

    po_date: date | None = None
    expiry_date: date | None = None
    completed_date: date | None = None       # set only once the WHOLE po completes

    value: float | None = None
    is_low_stock_po: bool = False

    total_quantity: int = 0
    pending_quantity: int = 0
    grn_quantity: int = 0                     # received — fill rate is grn_quantity / total_quantity

    # ── Booking-slot fields — CONFIRMED LIVE 2026-09-28 to exist on this same
    # `searchPurchaseOrder` response, mirroring what the Supply Portal's own
    # "PO Booking" tab renders (see instamart_po_service.py's module docstring,
    # which previously — wrongly — claimed no booking concept exists here at
    # all). None/False until the vendor actually books a slot for the PO.
    appointment_start_date: datetime | None = None   # the booked delivery slot, if any — Blinkit's schedule_date equivalent
    po_min_order_qty_fulfilled: bool = False          # the portal's "MOQ" badge
    po_min_order_value_fulfilled: bool = False
    supplier_multi_grn_enabled: bool = False          # the portal's "Multi-GRN" badge
    pdp_enabled: bool = False                         # the portal's "PDP" badge

    created_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=now_ist)


class InstamartPOItem(SQLModel, table=True):
    """One row per SKU per purchase order — from `listPurchaseOrderLines`, a
    separate per-PO call (not included in `searchPurchaseOrder`'s list).

    `pending_qty` from THIS endpoint resets to 0 once a PO closes (verified
    live 2026-09-25) and can't be trusted for a closed PO's real shortfall.
    `received_qty`/`balanced_qty` below are a SEPARATE, more reliable source:
    the Supply Portal's bulk CSV export (`/api/v1/batch/submit` +
    `/api/v1/batch/list`, see `dashboard_data/supply/fetch.py`'s
    `submit_po_export`/`fetch_po_export`), which carries Instamart's own
    `ReceivedQty`/`BalancedQty` per line and does NOT get reset on close.
    Populated by a separate scrape step; null until that step has run for a
    given PO.
    """

    __tablename__ = "instamart_po_item"

    __table_args__ = (
        Index("idx_impoi_tenant_po", "tenant_id", "purchase_order_id"),
        Index("idx_impoi_item", "tenant_id", "external_item_code"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "instamart"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    purchase_order_id: str           # links to InstamartPO.purchase_order_id (no hard FK: POs and lines are fetched separately, a line should still save if written before the header)
    external_item_code: str          # Instamart's product code -- same id family as instamart_ad_product_daily.candidate_id? NOT yet confirmed; join by name until verified.
    description: str | None = None   # the product name, e.g. "Brik Oven Artisanal Sourdough Bread (Freshly Baked) 400.0 g"
    category_id: str | None = None   # e.g. "Dairy, Bread and Eggs, Bread and Buns"

    qty: int = 0                      # ordered
    pending_qty: int = 0              # still outstanding -- received = qty - pending_qty

    mrp: float | None = None
    # Despite its API name ("unit_cost_price_excluding_tax"), this is a LINE
    # total, not a per-unit price -- verified live 2026-09-25: dividing by qty
    # gives an EXACT per-unit rate on real data (16786/218 = 41272/536 =
    # 77.00), which a genuinely-already-per-unit field couldn't reproduce.
    # Per-unit cost is this / qty, computed at read time rather than stored,
    # for the same reason Zepto's derived figures are -- it can't drift from
    # the two numbers it comes from.
    line_cost_excluding_tax: float | None = None

    # From the bulk CSV export, not `listPurchaseOrderLines` -- see class
    # docstring. Null until the export step has synced this line.
    received_qty: int | None = None
    balanced_qty: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)
