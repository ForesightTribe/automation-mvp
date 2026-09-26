"""Upsert parsed purchase-order data into `instamart_po` / `instamart_po_item`.

Same ON CONFLICT (upsert_key) DO UPDATE shape as every other Instamart
storage module — a PO's `pending_quantity`/`grn_quantity`/`status` change as
it's fulfilled, so re-scraping the same PO overwrites in place rather than
duplicating (see the "no receipt-event timestamp" note in
`app/models/instamart_po.py` for why this table is a snapshot, not a log).
"""
import uuid

from sqlalchemy import bindparam, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InstamartPO, InstamartPOItem
from app.utils.logger import logger
from app.utils.time import now_ist

_PLATFORM = "instamart"


def _key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def build_rows(tenant_id: str, po_rows: list[dict], item_rows: list[dict],
               scrape_job_id: uuid.UUID | None = None) -> tuple[list[dict], list[dict]]:
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()

    def common(row: dict) -> dict:
        row["tenant_id"] = tid
        row["platform"] = _PLATFORM
        row["scrape_job_id"] = scrape_job_id
        row["scraped_at"] = stamped
        return row

    for row in po_rows:
        common(row)["upsert_key"] = _key(_PLATFORM, tid, row["purchase_order_id"])
    for row in item_rows:
        common(row)["upsert_key"] = _key(
            _PLATFORM, tid, row["purchase_order_id"], row["external_item_code"])
    return po_rows, item_rows


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> int:
    if not rows:
        return 0

    deduped = {r["upsert_key"]: r for r in rows}
    if len(deduped) != len(rows):
        logger.info(
            f"{model.__tablename__}: collapsed {len(rows) - len(deduped)} "
            f"duplicate upsert_key row(s) before insert"
        )
    rows = list(deduped.values())

    shape = set(rows[0])
    for r in rows[1:]:
        if set(r) != shape:
            raise ValueError(
                f"{model.__tablename__}: rows in one batch have different columns — "
                f"missing: {sorted(shape - set(r))}; unexpected: {sorted(set(r) - shape)}"
            )

    update_cols = [c.name for c in model.__table__.columns
                   if c.name not in {"id", "upsert_key"}]
    chunk = max(1, 32000 // max(1, len(model.__table__.columns)))
    for i in range(0, len(rows), chunk):
        stmt = (
            insert(model)
            .values(rows[i:i + chunk])
            .on_conflict_do_update(
                index_elements=["upsert_key"],
                set_={c: insert(model).excluded[c] for c in update_cols},
            )
        )
        await session.execute(stmt)
    return len(rows)


async def save_purchase_orders(session: AsyncSession, tenant_id: str,
                                po_rows: list[dict], item_rows: list[dict],
                                scrape_job_id: uuid.UUID | None = None) -> dict[str, int]:
    po_rows, item_rows = build_rows(tenant_id, po_rows, item_rows, scrape_job_id)
    written = {
        "purchase_orders": await _upsert(session, InstamartPO, po_rows),
        "purchase_order_items": await _upsert(session, InstamartPOItem, item_rows),
    }
    logger.info(
        f"Instamart PO saved: {written['purchase_orders']} PO(s), "
        f"{written['purchase_order_items']} line item(s)"
    )
    return written


async def save_po_export(session: AsyncSession, tenant_id: str, rows: list[dict]) -> int:
    """A TARGETED update of only `received_qty`/`balanced_qty` on existing
    lines, keyed by (tenant_id, purchase_order_id, external_item_code) --
    NOT the generic `_upsert`, which would overwrite every other column
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
    result = await session.execute(stmt, params)
    # asyncpg doesn't report a real rowcount for an executemany-style UPDATE
    # (comes back -1) -- report how many rows we ATTEMPTED instead of a
    # number that looks like a failure.
    logger.info(f"Instamart PO export: synced received/balanced qty for {len(params)} line(s)")
    return len(params)
