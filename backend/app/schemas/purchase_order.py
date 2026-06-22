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
