"""
Export Blinkit scraped data for a single tenant to an Excel workbook.

Usage:
    python export_to_excel.py <tenant_id>
    python export_to_excel.py <tenant_id> --output report.xlsx

Reads MONGODB_URL and DB_NAME from .env (same as the backend).
"""

import asyncio
import argparse
import json
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "foresight")

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)

# Internal MongoDB / system fields — not shown to clients
_STRIP = {"_id", "upsert_key", "tenant_id"}


def _to_header(key: str) -> str:
    return key.replace("_", " ").title()


def _clean_value(val):
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)  # Excel doesn't support tz-aware datetimes
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)  # fallback for any unexpected nested structures
    return val


def _write_sheet(ws, rows: list[dict]) -> None:
    if not rows:
        ws.append(["(no data)"])
        return

    all_keys = list(dict.fromkeys(k for row in rows for k in row))

    for col_idx, key in enumerate(all_keys, start=1):
        cell = ws.cell(row=1, column=col_idx, value=_to_header(key))
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in enumerate(rows, start=2):
        for col_idx, key in enumerate(all_keys, start=1):
            ws.cell(row=row_idx, column=col_idx, value=_clean_value(row.get(key)))

    for col_idx, key in enumerate(all_keys, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            len(_to_header(key)),
            max((len(str(row.get(key) or "")) for row in rows), default=0),
        )
        ws.column_dimensions[col_letter].width = min(max_len + 2, 55)


def _strip(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _STRIP}


async def export(tenant_id: str, output_path: str) -> None:
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    async def fetch(collection: str) -> list[dict]:
        cursor = db[collection].find({"tenant_id": tenant_id}, {"_id": 0})
        return await cursor.to_list(length=None)

    def add_sheet(name: str, rows: list[dict]) -> None:
        _write_sheet(wb.create_sheet(name), rows)

    # ── Ad Performance Summary ────────────────────────────────────────────────
    # budget_distribution is a dict — flatten inline with budget_dist_ prefix
    raw_perf = await fetch("ad_performance_summary")
    flat_perf = []
    for doc in raw_perf:
        row: dict = {}
        for k, v in _strip(doc).items():
            if k == "budget_distribution" and isinstance(v, dict):
                for bk, bv in v.items():
                    row[f"budget_dist_{bk}"] = bv
            else:
                row[k] = v
        flat_perf.append(row)
    add_sheet("Ad Performance Summary", flat_perf)

    # ── Ad Campaigns ─────────────────────────────────────────────────────────
    add_sheet("Ad Campaigns", [_strip(d) for d in await fetch("ad_campaigns")])

    # ── Sponsored SOV ────────────────────────────────────────────────────────
    add_sheet("Sponsored SOV", [_strip(d) for d in await fetch("sponsored_sov")])

    # ── Brand Collections ────────────────────────────────────────────────────
    add_sheet("Brand Collections", [_strip(d) for d in await fetch("brand_collections")])

    # ── Visibility Plans ─────────────────────────────────────────────────────
    add_sheet("Visibility Plans", [_strip(d) for d in await fetch("visibility_plans")])

    # ── Seller Sales ─────────────────────────────────────────────────────────
    add_sheet("Seller Sales", [_strip(d) for d in await fetch("blinkit_seller_sales")])

    # ── Sales Summary ────────────────────────────────────────────────────────
    add_sheet("Sales Summary", [_strip(d) for d in await fetch("blinkit_seller_sales_summary")])

    # ── Purchase Orders ──────────────────────────────────────────────────────
    # Each PO doc may contain an `items` list of line items — extract to separate sheet
    raw_pos = await fetch("blinkit_pos")
    po_line_items: list[dict] = []
    flat_pos = []
    for doc in raw_pos:
        items = doc.get("items") or []
        po_number = doc.get("po_number")
        for item in items:
            po_line_items.append({"po_number": po_number, **item})
        flat_pos.append({k: v for k, v in _strip(doc).items() if k != "items"})
    add_sheet("Purchase Orders", flat_pos)
    add_sheet("PO Line Items", po_line_items)

    # ── PO Snapshots ─────────────────────────────────────────────────────────
    add_sheet("PO Snapshots", [_strip(d) for d in await fetch("blinkit_po_snapshots")])

    # ── Stock On Hand ────────────────────────────────────────────────────────
    add_sheet("Stock On Hand", [_strip(d) for d in await fetch("blinkit_soh")])

    # ── Scorecard Weekly ─────────────────────────────────────────────────────
    # overall + best_category dicts → flattened inline
    # categories list → separate sheet
    raw_weekly = await fetch("blinkit_scorecard_weekly")
    flat_weekly = []
    all_categories: list[dict] = []

    for doc in raw_weekly:
        row: dict = {}
        for k, v in _strip(doc).items():
            if k == "overall" and isinstance(v, dict):
                for sk, sv in v.items():
                    row[f"overall_{sk}"] = sv
            elif k == "best_category" and isinstance(v, dict):
                for sk, sv in v.items():
                    row[f"best_cat_{sk}"] = sv
            elif k == "categories" and isinstance(v, list):
                for cat in v:
                    all_categories.append({
                        "manufacturer_id": doc.get("manufacturer_id"),
                        "from_date_ist": doc.get("from_date_ist"),
                        **cat,
                    })
            else:
                row[k] = v
        flat_weekly.append(row)

    add_sheet("Scorecard Weekly", flat_weekly)
    add_sheet("Scorecard Categories", all_categories)

    # ── Scorecard Facilities ──────────────────────────────────────────────────
    add_sheet("Scorecard Facilities", [_strip(d) for d in await fetch("blinkit_scorecard_facilities")])

    # ── Scorecard Key SKUs ────────────────────────────────────────────────────
    add_sheet("Scorecard Key SKUs", [_strip(d) for d in await fetch("blinkit_scorecard_key_skus")])

    client.close()
    wb.save(output_path)
    print(f"Exported {len(wb.sheetnames)} sheets → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Blinkit tenant data to Excel")
    parser.add_argument("tenant_id", help="Tenant ID to export")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (default: blinkit_<tenant_id>_<date>.xlsx)",
    )
    args = parser.parse_args()

    output = args.output or f"blinkit_{args.tenant_id}_{date.today().isoformat()}.xlsx"
    asyncio.run(export(args.tenant_id, output))
