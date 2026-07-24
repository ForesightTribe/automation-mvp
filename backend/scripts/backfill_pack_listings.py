"""Backfill pack columns on `search_listings` from the raw `unit` in `extra`.

Rows scraped before the pack columns existed keep their unit string in
`extra->>'unit'` (100% populated in every run inspected). This parses it into
`pack_raw`/`pack_size`/`pack_uom`/`pack_count` and re-derives `is_combo` from the
resulting `pack_count` — the same `scraper/utils/pack.py` the live scraper now uses,
so backfilled history and fresh rows are identical.

SAFE BY CONSTRUCTION:
  * Only touches rows not yet processed:
        (pack_raw IS NULL OR pack_raw = '') AND extra->>'unit' present
    A backfilled row gets `pack_raw` set (to the unit string, even when unparseable),
    so it drops out on the next run — idempotent and resumable, and it can NEVER blank
    a freshly-scraped row (those already carry a non-empty pack_raw).
  * Batched with a per-batch commit via a TEMP table + COPY + `UPDATE … FROM` — the
    fast path (the loader proved executemany is ~46 ms/row and dies on long runs).

DRY RUN BY DEFAULT: prints how many rows would change and a parse-coverage sample.
Pass --apply to write. This is a shared-DB write — get sign-off first.

Usage:
    cd backend
    python -m scripts.backfill_pack_listings                 # dry run
    python -m scripts.backfill_pack_listings --apply
    python -m scripts.backfill_pack_listings --apply --no-recombo   # leave is_combo as-is
"""
import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal          # noqa: E402
from app.utils.logger import logger                      # noqa: E402
from scraper.utils.pack import pack_fields, combo_from_pack  # noqa: E402

BATCH = 20000
# The Supabase pooler / home NAT drops a connection idle across a batch. A batch that
# fails wrote nothing (it commits atomically), so retry it; only give up after this
# many CONSECUTIVE failures. The counter resets on any batch that lands.
MAX_STALLS = 6

_SELECT = text("""
    SELECT id, product_name, extra->>'unit' AS unit
    FROM search_listings
    WHERE (pack_raw IS NULL OR pack_raw = '')
      AND extra->>'unit' IS NOT NULL AND extra->>'unit' <> ''
    ORDER BY id
    LIMIT :batch
""")

_COUNT = text("""
    SELECT count(*) FROM search_listings
    WHERE (pack_raw IS NULL OR pack_raw = '')
      AND extra->>'unit' IS NOT NULL AND extra->>'unit' <> ''
""")

_TEMP = ("CREATE TEMP TABLE _bf_listings ("
         "id bigint PRIMARY KEY, pack_raw text, pack_size double precision, "
         "pack_uom text, pack_count int, is_combo bool) ON COMMIT DROP")

_UPDATE_RECOMBO = ("UPDATE search_listings t SET "
                   "pack_raw=b.pack_raw, pack_size=b.pack_size, pack_uom=b.pack_uom, "
                   "pack_count=b.pack_count, is_combo=b.is_combo "
                   "FROM _bf_listings b WHERE t.id=b.id")

_UPDATE_KEEP = ("UPDATE search_listings t SET "
                "pack_raw=b.pack_raw, pack_size=b.pack_size, pack_uom=b.pack_uom, "
                "pack_count=b.pack_count "
                "FROM _bf_listings b WHERE t.id=b.id")


async def _raw(db):
    return (await (await db.connection()).get_raw_connection()).driver_connection


def _record(row) -> tuple:
    pf = pack_fields(row.unit)
    return (row.id, pf["pack_raw"], pf["pack_size"], pf["pack_uom"], pf["pack_count"],
            combo_from_pack(row.product_name or "", pf["pack_count"]))


async def _dry_run() -> None:
    async with AsyncSessionLocal() as db:
        total = (await db.execute(_COUNT)).scalar_one()
        sample = (await db.execute(_SELECT, {"batch": 500})).all()
    parsed = sum(1 for r in sample if pack_fields(r.unit)["pack_size"] is not None)
    combo_flips = sum(
        1 for r in sample
        if combo_from_pack(r.product_name or "", pack_fields(r.unit)["pack_count"])
    )
    logger.info(f"[dry run] {total:,} listings pending backfill")
    if sample:
        logger.info(f"[dry run] sample of {len(sample)}: "
                    f"{parsed} parsed to a size ({parsed/len(sample)*100:.1f}%), "
                    f"{combo_flips} would be is_combo=true")
        for r in sample[:10]:
            pf = pack_fields(r.unit)
            logger.info(f"    {r.unit!r:26} -> size={pf['pack_size']} uom={pf['pack_uom']!r} "
                        f"count={pf['pack_count']}")
    logger.info("[dry run] nothing written — pass --apply to backfill")


async def _apply(recombo: bool) -> None:
    update_sql = _UPDATE_RECOMBO if recombo else _UPDATE_KEEP
    cols = ["id", "pack_raw", "pack_size", "pack_uom", "pack_count", "is_combo"]
    done = 0
    stalls = 0
    while True:
        try:
            async with AsyncSessionLocal() as db:   # fresh session per batch: a dropped one can't be reused
                rows = (await db.execute(_SELECT, {"batch": BATCH})).all()
                if not rows:
                    break
                recs = [_record(r) for r in rows]
                pg = await _raw(db)
                await pg.execute(_TEMP)
                await pg.copy_records_to_table("_bf_listings", records=recs, columns=cols)
                await pg.execute(update_sql)
                await db.commit()
        except DBAPIError:
            stalls += 1
            if stalls > MAX_STALLS:
                raise
            delay = min(2 ** stalls, 30)
            logger.warning(f"connection dropped mid-batch — retry {stalls}/{MAX_STALLS} "
                           f"in {delay}s (the failed batch wrote nothing; resuming)")
            await asyncio.sleep(delay)
            continue
        stalls = 0                                   # a batch landed — reset the streak
        done += len(rows)
        logger.info(f"backfilled {done:,} listings")
        if len(rows) < BATCH:
            break
    logger.info(f"done — {done:,} listings backfilled"
                f"{'' if recombo else ' (is_combo left unchanged)'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill pack columns on search_listings")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--no-recombo", dest="recombo", action="store_false",
                    help="do NOT re-derive is_combo from pack_count")
    args = ap.parse_args()
    asyncio.run(_apply(args.recombo) if args.apply else _dry_run())


if __name__ == "__main__":
    main()
