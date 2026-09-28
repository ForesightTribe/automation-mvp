"""Parse `searchPurchaseOrder` and `listPurchaseOrderLines` responses into the
flat dict shapes `storage.py` upserts — same split as every other Instamart
parser in this codebase (fetch/parse/save kept separate so each is testable
against a saved response with no network).

Field names below are exactly what a live capture returned on 2026-09-25 (see
`app/models/instamart_po.py`'s module docstring for the full context); fields
the models don't need (reference_purchase_order_id, sample_po, business_type,
delivery_mode, hsn, tax breakdowns, ...) are read from `raw` but dropped here.
"""
import csv
import io
from datetime import date, datetime, timezone


def _epoch_ms_to_date(ms) -> date | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date()


def _epoch_ms_to_dt(ms) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(tzinfo=None)


def _money(m: dict | float | int | None) -> float | None:
    """Instamart's supply-portal money fields are `{"currency_code", "units"}`
    — `units` alone, no fractional/nanos component seen in captures (unlike
    the ads portal's `{"units", "nanos"}` shape) — but tolerate one anyway."""
    if m is None:
        return None
    if isinstance(m, (int, float)):
        return float(m)
    return float(m.get("units") or 0) + float(m.get("nanos") or 0) / 1e9


def parse_purchase_orders(raw: dict) -> list[dict]:
    """`raw` is one page of `searchPurchaseOrder`'s response body."""
    out = []
    for po in (raw.get("data") or {}).get("purchase_orders") or []:
        out.append({
            "purchase_order_id": po["purchase_order_id"],
            "facility_name": po.get("facility_name"),
            "vendor_name": po.get("vendor_name"),
            "vendor_code": po.get("vendor_code"),
            "status": po.get("status"),
            "receiving_status": po.get("receiving_status"),
            "po_date": _epoch_ms_to_date(po.get("po_date")),
            "expiry_date": _epoch_ms_to_date(po.get("expiry_date")),
            "completed_date": _epoch_ms_to_date(po.get("completed_date")),
            "value": _money(po.get("value")),
            "is_low_stock_po": bool(po.get("is_low_stock_po")),
            "total_quantity": int(po.get("total_quantity") or 0),
            "pending_quantity": int(po.get("pending_quantity") or 0),
            "grn_quantity": int(po.get("grn_quantity") or 0),
            "created_at": _epoch_ms_to_dt(po.get("created_at")),
        })
    return out


def total_po_count(raw: dict) -> int:
    return int((raw.get("data") or {}).get("total_number_of_purchase_order_records") or 0)


def parse_po_lines(raw: dict, *, purchase_order_id: str) -> list[dict]:
    """`raw` is `listPurchaseOrderLines`'s response body for ONE PO.

    Confirmed live 2026-09-25 (real PO BLRPO149238): `unit_cost_price_excluding_tax`
    is a LINE total despite its name (16786/218 qty = 41272/536 qty = exactly
    ₹77.00/unit both lines) — stored as `line_cost_excluding_tax`, matching
    what it actually measures. `total_amount_breakdown` on each line repeats
    the WHOLE PO's total (both lines showed 59234, the PO's own `value`) —
    not a real per-line figure, so it isn't parsed here at all.
    """
    out = []
    for line in (raw.get("data") or {}).get("purchase_order_lines") or []:
        out.append({
            "purchase_order_id": purchase_order_id,
            "external_item_code": line["external_item_code"],
            "description": line.get("description"),
            "category_id": line.get("category_id"),
            "qty": int(line.get("qty") or 0),
            "pending_qty": int(line.get("pending_qty") or 0),
            "mrp": _money(line.get("mrp")),
            "line_cost_excluding_tax": _money(line.get("unit_cost_price_excluding_tax")),
        })
    return out


def parse_po_export_csv(csv_text: str) -> list[dict]:
    """The bulk export's `ReceivedQty`/`BalancedQty` per (PoNumber, SkuCode)
    row -- the one source that survives a PO closing (see model docstring).
    One row per SKU per PO, same key `storage.py` upserts lines by."""
    out = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        po = (row.get("PoNumber") or "").strip()
        sku = (row.get("SkuCode") or "").strip()
        if not po or not sku:
            continue
        out.append({
            "purchase_order_id": po,
            "external_item_code": sku,
            "received_qty": int(float(row["ReceivedQty"])) if row.get("ReceivedQty") not in (None, "") else None,
            "balanced_qty": int(float(row["BalancedQty"])) if row.get("BalancedQty") not in (None, "") else None,
        })
    return out
