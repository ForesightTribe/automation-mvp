"""Raw data export — the underlying rows, streamed to CSV.

Deliberately **not** part of the client report. One 7-day window of Dobra is
~194k search listings and ~85k own-SKU readings; bundling that into every
workbook would make the eventual Download button ship a hundred megabytes nobody
asked for. The report is a readable deliverable; this is a data dump, and the two
have different shapes, formats and audiences.

**CSV, not xlsx, on purpose.** At these volumes a styled workbook is the wrong
container: openpyxl holds every cell in memory, none of the design system
survives a raw dump, and Excel opens CSV natively anyway. Use `--limit` for a
sample small enough to eyeball.

Rows are read in keyset chunks (`WHERE id > last ORDER BY id LIMIT n`) rather
than with a server-side cursor: every table has a monotonic integer primary key,
and keyset paging behaves identically through a connection pooler, where
streaming cursors can quietly fail.
"""
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import MarketplaceLocation, SearchListing, SearchSnapshot, SkuSnapshot
from app.utils.logger import logger

# The window filter is imported rather than re-derived — same rule as build.py.
from app.services.inventory_service import _bounds  # noqa: PLC2701

CHUNK = 10_000

# `extra` is the scraper's untyped payload — ~284 bytes a row, over half of each
# listing, and mostly an image URL. Excluded by default; --include-extra brings
# it back for anyone who actually needs it.
_HEAVY = {"extra"}


@dataclass(frozen=True)
class Table:
    key: str
    model: type
    label: str
    description: str
    tenant_scoped: bool = True
    windowed: bool = True


TABLES: dict[str, Table] = {
    "sku": Table(
        key="sku", model=SkuSnapshot, label="own_products_by_store",
        description="One row per own product per dark store per scrape — price, stock, pack.",
    ),
    "listings": Table(
        key="listings", model=SearchListing, label="search_listings",
        description="Every product seen in a search — yours and competitors'. The biggest table.",
    ),
    "searches": Table(
        key="searches", model=SearchSnapshot, label="searches",
        description="One row per search at one probe point — rank, share of search, result count.",
    ),
    "stores": Table(
        key="stores", model=MarketplaceLocation, label="store_catalogue",
        description="The dark-store catalogue: id, name, city, coordinates.",
        tenant_scoped=False, windowed=False,
    ),
}


def columns(table: Table, *, include_extra: bool = False) -> list[str]:
    return [
        c.name for c in table.model.__table__.columns
        if include_extra or c.name not in _HEAVY
    ]


def _conditions(table: Table, *, tenant_id, start: date, end: date,
                city: str | None, marketplace: str | None) -> list:
    model = table.model
    cond = []
    if table.tenant_scoped:
        cond.append(model.tenant_id == tenant_id)
    if table.windowed:
        lo, hi = _bounds(start, end)
        cond += [model.scraped_at >= lo, model.scraped_at < hi]
    if city and hasattr(model, "city"):
        cond.append(model.city == city)
    if marketplace and hasattr(model, "mp_slug"):
        cond.append(model.mp_slug == marketplace)
    return cond


async def count(db: AsyncSession, table: Table, **filters) -> int:
    cond = _conditions(table, **filters)
    stmt = select(func.count()).select_from(table.model)
    if cond:
        stmt = stmt.where(*cond)
    return (await db.execute(stmt)).scalar_one()


def _cell(value):
    """CSV is text: render types the way a spreadsheet or pandas will read back."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


async def export_table(
    db: AsyncSession,
    table: Table,
    path: Path,
    *,
    include_extra: bool = False,
    limit: int | None = None,
    **filters,
) -> int:
    """Stream one table to `path`. Returns the number of data rows written."""
    cols = columns(table, include_extra=include_extra)
    model = table.model
    cond = _conditions(table, **filters)
    written, last_id = 0, 0

    # utf-8-sig: Excel on Windows assumes the system codepage for a .csv without
    # a BOM, which turns ₹ and every accented product name into mojibake.
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        while True:
            take = CHUNK if limit is None else min(CHUNK, limit - written)
            if take <= 0:
                break
            stmt = (
                select(*[getattr(model, c) for c in cols])
                .where(*cond, model.id > last_id)
                .order_by(model.id)
                .limit(take)
            )
            rows = (await db.execute(stmt)).all()
            if not rows:
                break
            id_at = cols.index("id")
            for row in rows:
                writer.writerow([_cell(v) for v in row])
            written += len(rows)
            last_id = rows[-1][id_at]
            logger.debug(f"{table.key}: {written:,} rows")
    return written
