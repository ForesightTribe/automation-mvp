"""Reclaim disk space on the public tables — REINDEX then VACUUM FULL.

WHY THIS EXISTS: `DELETE` never returns disk to the OS, and every `UPDATE` writes a
new row version and leaves the old one dead (MVCC). Autovacuum makes that space
reusable *by the same table* but never shrinks the file, so a big delete + a big
backfill can leave a table several times larger than its live data. On Supabase free
tier (500 MB) that fills the quota. Only `VACUUM FULL` returns the space.

WHY THE ORDER MATTERS: `VACUUM FULL` writes the new copy BEFORE dropping the old, so
it needs free headroom roughly equal to the compacted table. When you are near the
quota that can fail — or worse, tip the project into read-only. So this script
rebuilds the (bloated) indexes one at a time first: each rebuild's peak cost is a few
MB and it frees far more, buying headroom for the heap rewrite that follows.

Run it OVER A DIRECT CONNECTION, not the Supabase SQL editor — the dashboard has an
HTTP gateway timeout (~1 min) that kills a long VACUUM FULL with "upstream timeout"
even though Postgres is still working. This script sets statement_timeout=0.

⚠️ Takes an ACCESS EXCLUSIVE lock per object: the table is unavailable while it runs.
NEVER run during a scrape or `cli scrape load`.

Usage:
    cd backend
    python -m scripts.reclaim_space                 # report sizes only
    python -m scripts.reclaim_space --apply         # reindex + vacuum full
    python -m scripts.reclaim_space --apply --table search_listings
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine                    # noqa: E402
from app.utils.logger import logger                     # noqa: E402

# Smallest first: each one frees headroom for the next.
DEFAULT_TABLES = ["search_snapshots", "sku_snapshots", "search_listings"]

_SIZES = text("""
    SELECT pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
           pg_total_relation_size(c.oid)                 AS raw
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = :t
""")

_INDEXES = text("""
    SELECT indexrelname AS iname
    FROM pg_stat_user_indexes WHERE relname = :t
    ORDER BY pg_relation_size(indexrelid) DESC
""")

_DBSIZE = text("SELECT pg_size_pretty(pg_database_size(current_database()))")


async def _report(conn) -> None:
    db = (await conn.execute(_DBSIZE)).scalar()
    logger.info(f"database size: {db}")
    for t in DEFAULT_TABLES:
        row = (await conn.execute(_SIZES, {"t": t})).first()
        if row:
            logger.info(f"  {t:20} {row.total}")


async def _reclaim(conn, table: str) -> None:
    before = (await conn.execute(_SIZES, {"t": table})).first()
    logger.info(f"{table}: {before.total} before")

    # 1. Rebuild indexes individually — cheap peak cost, frees headroom for step 2.
    idxs = [r.iname for r in (await conn.execute(_INDEXES, {"t": table})).all()]
    for i in idxs:
        t0 = time.time()
        await conn.execute(text(f'REINDEX INDEX "{i}"'))
        logger.info(f"  reindexed {i} ({time.time() - t0:.1f}s)")

    mid = (await conn.execute(_SIZES, {"t": table})).first()
    logger.info(f"  after reindex: {mid.total} "
                f"(freed {(before.raw - mid.raw) / 1024 / 1024:.0f} MB)")

    # 2. Rewrite the heap compactly. ANALYZE too: the planner stats are stale after a
    #    large delete/backfill, which skews query plans on top of the disk problem.
    t0 = time.time()
    await conn.execute(text(f'VACUUM (FULL, ANALYZE) "{table}"'))
    after = (await conn.execute(_SIZES, {"t": table})).first()
    logger.info(f"  VACUUM FULL done in {time.time() - t0:.1f}s -> {after.total} "
                f"(total freed {(before.raw - after.raw) / 1024 / 1024:.0f} MB)")


async def main_async(tables: list[str], apply: bool) -> None:
    # AUTOCOMMIT: VACUUM/REINDEX cannot run inside a transaction block.
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("SET statement_timeout = 0"))   # no server-side cap
        await conn.execute(text("SET lock_timeout = '30s'"))    # don't queue forever behind a scrape

        if not apply:
            await _report(conn)
            logger.info("report only — pass --apply to reindex + VACUUM FULL")
            return

        logger.info("=== reclaim starting (tables are LOCKED while this runs) ===")
        await _report(conn)
        for t in tables:
            await _reclaim(conn, t)
        logger.info("=== done ===")
        await _report(conn)


def main() -> None:
    ap = argparse.ArgumentParser(description="Reclaim disk space (REINDEX + VACUUM FULL)")
    ap.add_argument("--apply", action="store_true", help="actually run it (default: report)")
    ap.add_argument("--table", action="append", dest="tables",
                    help="limit to this table (repeatable); default = all three public tables")
    args = ap.parse_args()
    asyncio.run(main_async(args.tables or DEFAULT_TABLES, args.apply))


if __name__ == "__main__":
    main()
