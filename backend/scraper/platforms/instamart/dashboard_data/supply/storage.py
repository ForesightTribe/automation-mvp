"""Upsert parsed purchase-order data into `instamart_po` / `instamart_po_item`.

Same ON CONFLICT (upsert_key) DO UPDATE shape (common.upsert) as every
other Instamart table — a PO's `pending_quantity`/`grn_quantity`/`status` change as
it's fulfilled, so re-scraping the same PO overwrites in place rather than
duplicating (see the "no receipt-event timestamp" note in
`app/models/instamart_po.py` for why this table is a snapshot, not a log).
"""
import uuid

from sqlalchemy import bindparam, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InstamartPO, InstamartPOItem
from app.utils.time import now_ist
from scraper.platforms.instamart.dashboard_data.common import PLATFORM, upsert, upsert_key


# The PO header fields that move whenever its lines do (a receipt changes
# pending/grn qty and the receiving status; an edit changes value or totals).
# If none of them changed since the stored copy, the lines have not either.
PO_FINGERPRINT = ("status", "receiving_status", "value", "total_quantity",
                  "pending_quantity", "grn_quantity", "expiry_date", "completed_date")


def po_fingerprint(row: dict) -> tuple:
    return tuple(row.get(k) for k in PO_FINGERPRINT)


async def stored_po_fingerprints(session: AsyncSession, tenant_id: str) -> dict[str, tuple]:
    """{purchase_order_id: fingerprint} for every stored PO that HAS line items —
    a PO stored without any (new, or its lines were lost) is absent, so it is
    always fetched."""
    tid = uuid.UUID(str(tenant_id))
    with_items = (select(InstamartPOItem.purchase_order_id)
                  .where(InstamartPOItem.tenant_id == tid).distinct())
    rows = await session.execute(
        select(InstamartPO.purchase_order_id, *(getattr(InstamartPO, k) for k in PO_FINGERPRINT))
        .where(InstamartPO.tenant_id == tid, InstamartPO.purchase_order_id.in_(with_items))
    )
    return {r[0]: tuple(r[1:]) for r in rows}


def build_rows(tenant_id: str, po_rows: list[dict], item_rows: list[dict],
               scrape_job_id: uuid.UUID | None = None) -> tuple[list[dict], list[dict]]:
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()

    def common(row: dict) -> dict:
        row["tenant_id"] = tid
        row["platform"] = PLATFORM
        row["scrape_job_id"] = scrape_job_id
        row["scraped_at"] = stamped
        return row

    for row in po_rows:
        common(row)["upsert_key"] = upsert_key(PLATFORM, tid, row["purchase_order_id"])
    for row in item_rows:
        common(row)["upsert_key"] = upsert_key(
            PLATFORM, tid, row["purchase_order_id"], row["external_item_code"])
    return po_rows, item_rows


async def save_purchase_orders(session: AsyncSession, tenant_id: str,
                                po_rows: list[dict], item_rows: list[dict],
                                scrape_job_id: uuid.UUID | None = None) -> dict[str, int]:
    po_rows, item_rows = build_rows(tenant_id, po_rows, item_rows, scrape_job_id)
    written = {
        "purchase_orders": await upsert(session, InstamartPO, po_rows),
        "purchase_order_items": await upsert(session, InstamartPOItem, item_rows),
    }
    return written


async def save_po_export(session: AsyncSession, tenant_id: str, rows: list[dict]) -> int:
    """A TARGETED update of only `received_qty`/`balanced_qty` on existing
    lines, keyed by (tenant_id, purchase_order_id, external_item_code) --
    NOT the generic `upsert`, which would overwrite every other column
    (qty, mrp, line_cost_excluding_tax, ...) with its INSERT-clause default
    since export rows don't carry them. Rows for a PO/SKU we haven't
    scraped a line for yet (via `listPurchaseOrderLines`) are silently
    no-ops -- there's no existing row to match."""
    if not rows:
        return 0
    tid = uuid.UUID(str(tenant_id))
    params = [
        {"tid": tid, "po": r["purchase_order_id"], "sku": r["external_item_code"],
         "rq": r["received_qty"], "bq": r["balanced_qty"]}
        for r in rows
    ]
    # Core `.__table__`, not the ORM class -- `update(InstamartPOItem)` with a
    # list of param dicts triggers SQLAlchemy 2.0's ORM-enabled bulk UPDATE
    # path, which requires a primary key in every dict (ours matches by
    # tenant/po/sku instead). The Core table skips that entirely.
    tbl = InstamartPOItem.__table__
    stmt = (
        update(tbl)
        .where(
            tbl.c.tenant_id == bindparam("tid"),
            tbl.c.purchase_order_id == bindparam("po"),
            tbl.c.external_item_code == bindparam("sku"),
        )
        .values(received_qty=bindparam("rq"), balanced_qty=bindparam("bq"))
    )
    await session.execute(stmt, params)
    # asyncpg doesn't report a real rowcount for an executemany-style UPDATE
    # (comes back -1) -- report how many rows we ATTEMPTED instead of a
    # number that looks like a failure.
    return len(params)
