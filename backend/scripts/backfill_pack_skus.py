"""Backfill pack columns on `sku_snapshots` — enriched from `search_listings`.

`sku_snapshots` never stored the `unit` string (the scraper dropped it), so unlike
the listings backfill there is no local source. Instead we build a
`platform_product_id → unit` map from `search_listings.extra->>'unit'` (the unit is a
stable property of a product id) and apply it. On the staged runs inspected this
covers 100% of sku rows; any product id absent from the map is left NULL — the honest
answer, never a guess.

Same safety model as the listings backfill: only rows with an empty `pack_raw` are
written, so a re-run is idempotent and a freshly-scraped row (already carrying
pack_raw) is never blanked. A monotonic id cursor guarantees termination even when a
whole batch is unmatched (those rows have no unit to set, so they'd otherwise be
re-selected forever).

DRY RUN BY DEFAULT — pass --apply to write. Shared-DB write; get sign-off first.

Usage:
    cd backend
    python -m scripts.backfill_pack_skus                 # dry run
    python -m scripts.backfill_pack_skus --apply
    python -m scripts.backfill_pack_skus --apply --no-recombo
"""
import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal          # noqa: E402
from app.utils.logger import logger                      # noqa: E402
from scraper.utils.pack import pack_fields, combo_from_pack  # noqa: E402

BATCH = 20000
# Consecutive connection-drop retries before giving up (see backfill_pack_listings).
MAX_STALLS = 6

# Every (product_id, unit) seen in the keyword scrape, with a frequency — so a product
# whose unit ever drifted resolves to its most common string, not a random one.
_MAP = text("""
    SELECT platform_product_id AS pid, extra->>'unit' AS unit, count(*) AS n
    FROM search_listings
    WHERE platform_product_id IS NOT NULL
      AND extra->>'unit' IS NOT NULL AND extra->>'unit' <> ''
    GROUP BY 1, 2
""")

_PAGE = text("""
    SELECT id, platform_product_id AS pid, product_name
    FROM sku_snapshots
    WHERE (pack_raw IS NULL OR pack_raw = '') AND id > :after
    ORDER BY id
    LIMIT :batch
""")

_COUNT = text("SELECT count(*) FROM sku_snapshots WHERE pack_raw IS NULL OR pack_raw = ''")

_TEMP = ("CREATE TEMP TABLE _bf_skus ("
         "id bigint PRIMARY KEY, pack_raw text, pack_size double precision, "
         "pack_uom text, pack_count int, is_combo bool) ON COMMIT DROP")

_UPDATE_RECOMBO = ("UPDATE sku_snapshots t SET "
                   "pack_raw=b.pack_raw, pack_size=b.pack_size, pack_uom=b.pack_uom, "
                   "pack_count=b.pack_count, is_combo=b.is_combo "
                   "FROM _bf_skus b WHERE t.id=b.id")

_UPDATE_KEEP = ("UPDATE sku_snapshots t SET "
                "pack_raw=b.pack_raw, pack_size=b.pack_size, pack_uom=b.pack_uom, "
                "pack_count=b.pack_count "
                "FROM _bf_skus b WHERE t.id=b.id")


async def _raw(db):
    return (await (await db.connection()).get_raw_connection()).driver_connection


async def _build_map(db) -> dict[str, str]:
    """platform_product_id → most-frequent unit string."""
    freq: dict[str, Counter] = defaultdict(Counter)
    for row in (await db.execute(_MAP)).all():
        freq[row.pid][row.unit] += row.n
    return {pid: c.most_common(1)[0][0] for pid, c in freq.items()}


def _record(row, unit_map) -> tuple | None:
    """The temp-table record for one sku row, or None when its product id has no
    known unit (leave it NULL rather than guess)."""
    unit = unit_map.get(row.pid)
    if not unit:
        return None
    pf = pack_fields(unit)
    return (row.id, pf["pack_raw"], pf["pack_size"], pf["pack_uom"], pf["pack_count"],
            combo_from_pack(row.product_name or "", pf["pack_count"]))


async def _dry_run() -> None:
    async with AsyncSessionLocal() as db:
        unit_map = await _build_map(db)
        total = (await db.execute(_COUNT)).scalar_one()
        sample = (await db.execute(_PAGE, {"after": 0, "batch": 1000})).all()
    matched = sum(1 for r in sample if r.pid in unit_map)
    logger.info(f"[dry run] {total:,} sku rows pending; unit map has {len(unit_map):,} product ids")
    if sample:
        logger.info(f"[dry run] sample of {len(sample)}: {matched} matched a unit "
                    f"({matched/len(sample)*100:.1f}%), {len(sample)-matched} would stay NULL")
        for r in sample[:10]:
            unit = unit_map.get(r.pid)
            pf = pack_fields(unit) if unit else None
            logger.info(f"    pid={r.pid!s:12} unit={unit!r:20} "
                        f"-> {pf['pack_size'] if pf else None}")
    logger.info("[dry run] nothing written — pass --apply to backfill")


async def _apply(recombo: bool) -> None:
    update_sql = _UPDATE_RECOMBO if recombo else _UPDATE_KEEP
    cols = ["id", "pack_raw", "pack_size", "pack_uom", "pack_count", "is_combo"]
    async with AsyncSessionLocal() as db:
        unit_map = await _build_map(db)
    logger.info(f"unit map: {len(unit_map):,} product ids")

    after = 0
    written = scanned = 0
    stalls = 0
    while True:
        try:
            async with AsyncSessionLocal() as db:   # fresh session per batch: a dropped one can't be reused
                rows = (await db.execute(_PAGE, {"after": after, "batch": BATCH})).all()
                if not rows:
                    break
                recs = [rec for r in rows if (rec := _record(r, unit_map)) is not None]
                if recs:
                    pg = await _raw(db)
                    await pg.execute(_TEMP)
                    await pg.copy_records_to_table("_bf_skus", records=recs, columns=cols)
                    await pg.execute(update_sql)
                    await db.commit()
        except DBAPIError:
            stalls += 1
            if stalls > MAX_STALLS:
                raise
            delay = min(2 ** stalls, 30)
            logger.warning(f"connection dropped mid-batch — retry {stalls}/{MAX_STALLS} "
                           f"in {delay}s (cursor not advanced; resuming)")
            await asyncio.sleep(delay)
            continue
        # Advance the cursor ONLY after the batch lands — else a retry would skip the
        # unwritten rows past `after`. `stalls` resets on any batch that succeeds.
        after = rows[-1].id
        stalls = 0
        scanned += len(rows)
        written += len(recs)
        logger.info(f"scanned {scanned:,} / written {written:,}")
        if len(rows) < BATCH:
            break
    logger.info(f"done — {written:,} sku rows backfilled, {scanned - written:,} left NULL "
                f"(no known unit){'' if recombo else '; is_combo unchanged'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill pack columns on sku_snapshots")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--no-recombo", dest="recombo", action="store_false",
                    help="do NOT re-derive is_combo from pack_count")
    args = ap.parse_args()
    asyncio.run(_apply(args.recombo) if args.apply else _dry_run())


if __name__ == "__main__":
    main()
