"""Re-derive pack_size/pack_uom/pack_count from the stored pack_raw strings.

`pack_raw` is kept verbatim on both public tables precisely so that a parser fix is
a backfill, never a re-scrape (see scraper/utils/pack.py). Run this after changing
`pack.py` to bring already-stored rows up to the new parser.

Cheap by construction: it groups by DISTINCT pack_raw and issues one UPDATE per
distinct string (21 for Zepto, 9 for Blinkit), not one per row.

Read-only by default — pass --apply to write.

    python -m scripts.backfill_pack --mp zepto            # report what would change
    python -m scripts.backfill_pack --mp zepto --apply    # write it
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from scraper.utils.pack import combo_from_pack, pack_fields

TABLES = ("sku_snapshots", "search_listings")

APPLY = "--apply" in sys.argv
MP = None
if "--mp" in sys.argv:
    MP = sys.argv[sys.argv.index("--mp") + 1]


async def main():
    async with AsyncSessionLocal() as db:
        grand = 0
        for table in TABLES:
            where_mp = "and mp_slug = :mp" if MP else ""
            rows = (await db.execute(text(
                f"select pack_raw, count(*) n from {table} "
                f"where pack_raw is not null and pack_raw <> '' {where_mp} "
                f"group by pack_raw order by n desc"
            ), ({"mp": MP} if MP else {}))).all()

            print(f"\n=== {table}{f' ({MP})' if MP else ''} — {len(rows)} distinct pack_raw ===")
            for raw, n in rows:
                f = pack_fields(raw)
                cur = (await db.execute(text(
                    f"select count(*) from {table} where pack_raw = :raw {where_mp} "
                    f"and pack_size is null"
                ), {"raw": raw, **({"mp": MP} if MP else {})})).scalar()
                if not cur:
                    continue
                mark = "would set" if not APPLY else "SET"
                print(f"  {mark} {cur:6} rows  {raw!r:22} -> "
                      f"size={f['pack_size']} uom={f['pack_uom']!r} count={f['pack_count']}")
                grand += cur
                if APPLY and f["pack_size"] is not None:
                    await db.execute(text(
                        f"update {table} set pack_size = :s, pack_uom = :u, pack_count = :c "
                        f"where pack_raw = :raw {where_mp} and pack_size is null"
                    ), {"s": f["pack_size"], "u": f["pack_uom"], "c": f["pack_count"],
                        "raw": raw, **({"mp": MP} if MP else {})})

        # is_combo is DERIVED from pack_count — reconcile it, or the two disagree.
        print("")
        print("=== is_combo reconciliation ===")
        for table in TABLES:
            where_mp = "and mp_slug = :mp" if MP else ""
            rows = (await db.execute(text(
                f"select pack_raw, pack_count, is_combo, count(*) n from {table} "
                f"where pack_count is not null {where_mp} "
                f"group by pack_raw, pack_count, is_combo"
            ), ({"mp": MP} if MP else {}))).all()
            for raw, cnt, flag, n in rows:
                want = combo_from_pack("", cnt)
                if want == flag:
                    continue
                print(f"  {'SET' if APPLY else 'would set'} {n:6} rows  {raw!r:22} "
                      f"pack_count={cnt} is_combo {flag} -> {want}")
                grand += n
                if APPLY:
                    await db.execute(text(
                        f"update {table} set is_combo = :want "
                        f"where pack_raw = :raw and pack_count = :cnt {where_mp}"
                    ), {"want": want, "raw": raw, "cnt": cnt,
                        **({"mp": MP} if MP else {})})

        if APPLY:
            await db.commit()
            print(f"\ncommitted — {grand} rows updated")
        else:
            print(f"\ndry run — {grand} rows would change. Re-run with --apply to write.")


asyncio.run(main())
