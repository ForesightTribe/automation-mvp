"""Helpers both Instamart consoles share — the Brand Portal (seller/) and the
Supply Portal (supply/).

    IST_OFFSET / epoch_s   the portals think in IST calendar days
    upsert_key / upsert    ON CONFLICT (upsert_key) DO UPDATE, the one write shape
                           every Instamart table uses
"""
import datetime as dt

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import logger

PLATFORM = "instamart"

IST_OFFSET = dt.timedelta(hours=5, minutes=30)

# Postgres caps bind parameters per statement at 32767 (one per column per row).
_MAX_PARAMS = 32000


def epoch_s(d: dt.date, end_of_day: bool = False) -> int:
    """IST calendar date -> UTC epoch seconds, matching how the portal itself
    builds its date filters (verified against a captured request: its 16-23 Sept
    IST window is exactly epoch 1789497000..1790188199)."""
    t = dt.time.max if end_of_day else dt.time.min
    local = dt.datetime.combine(d, t) - IST_OFFSET
    return int(local.replace(tzinfo=dt.timezone.utc).timestamp())


def upsert_key(*parts) -> str:
    return "|".join(str(p) for p in parts)


async def upsert(session: AsyncSession, model, rows: list[dict]) -> int:
    """Insert `rows`, overwriting any existing row with the same `upsert_key`.
    Returns the number of distinct rows written."""
    if not rows:
        return 0

    # ON CONFLICT DO UPDATE cannot touch the same row twice in one statement
    # ("command cannot affect row a second time"), so collapse duplicates first.
    deduped = {r["upsert_key"]: r for r in rows}
    if len(deduped) != len(rows):
        logger.debug(
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
    chunk = max(1, _MAX_PARAMS // max(1, len(model.__table__.columns)))
    for i in range(0, len(rows), chunk):
        stmt = insert(model).values(rows[i:i + chunk])
        stmt = stmt.on_conflict_do_update(
            index_elements=["upsert_key"],
            set_={c: stmt.excluded[c] for c in update_cols},
        )
        await session.execute(stmt)
    return len(rows)
