"""Upsert the parsed Sales report into the two Instamart seller tables.

Same ON CONFLICT (upsert_key) DO UPDATE shape as the Zepto seller storage, so
re-running a report — or loading an overlapping window — overwrites in place
instead of duplicating. A 31-day report and a single-day report for a date
inside it produce the same keys, which is exactly what we want.
"""
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InstamartBrandCityDaily, InstamartSellerStoreDaily
from app.utils.logger import logger
from app.utils.time import now_ist

_PLATFORM = "instamart"


def _key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def build_rows(tenant_id: str, store_rows: list[dict], brand_rows: list[dict],
               scrape_job_id: uuid.UUID | None = None) -> tuple[list[dict], list[dict]]:
    """Add the bookkeeping columns the tables share, and the upsert keys."""
    tid = uuid.UUID(str(tenant_id))
    stamped = now_ist()

    def common(row: dict) -> dict:
        row["tenant_id"] = tid
        row["platform"] = _PLATFORM
        row["scrape_job_id"] = scrape_job_id
        row["scraped_at"] = stamped
        return row

    for row in store_rows:
        common(row)["upsert_key"] = _key(
            _PLATFORM, tid, row["date"], row["store_id"], row["item_code"])
    for row in brand_rows:
        common(row)["upsert_key"] = _key(_PLATFORM, tid, row["date"], row["city"])
    return store_rows, brand_rows


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> int:
    if not rows:
        return 0

    # ON CONFLICT DO UPDATE cannot touch the same row twice in one statement
    # ("command cannot affect row a second time"), so collapse duplicates first.
    # A single report should never contain any; a caller merging two reports can.
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
    # Postgres caps bind parameters per statement at 32767 (one per column per row).
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


async def save_sales(session: AsyncSession, tenant_id: str,
                     store_rows: list[dict], brand_rows: list[dict],
                     scrape_job_id: uuid.UUID | None = None) -> dict[str, int]:
    """Upsert both grains. Returns rows written per table."""
    store_rows, brand_rows = build_rows(tenant_id, store_rows, brand_rows, scrape_job_id)
    written = {
        "store_daily": await _upsert(session, InstamartSellerStoreDaily, store_rows),
        "brand_city": await _upsert(session, InstamartBrandCityDaily, brand_rows),
    }
    logger.info(
        f"Instamart sales saved: {written['store_daily']} store rows, "
        f"{written['brand_city']} brand-city rows"
    )
    return written
