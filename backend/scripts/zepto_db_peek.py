"""Peek at what Zepto data is in Postgres — counts plus a few real rows.

A read-only sanity check for after `cli scrape load`, so you can see the rows
without opening Supabase.

Run from backend/:
    python -m scripts.zepto_db_peek
    python -m scripts.zepto_db_peek --mp blinkit      # same view for Blinkit
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

MP = "blinkit" if "--mp" in sys.argv and "blinkit" in sys.argv else "zepto"


async def main():
    async with AsyncSessionLocal() as db:
        print(f"\n=== {MP.upper()} in Postgres ===\n")

        rows = (await db.execute(text(
            "select mp_slug, count(*) from search_snapshots group by mp_slug "
            "order by mp_slug"))).all()
        print("search_snapshots   " + "   ".join(f"{m}={n:,}" for m, n in rows))
        rows = (await db.execute(text(
            "select mp_slug, count(*) from search_listings group by mp_slug "
            "order by mp_slug"))).all()
        print("search_listings    " + "   ".join(f"{m}={n:,}" for m, n in rows))

        print(f"\n--- {MP} snapshots by keyword ---")
        q = text("select keyword, count(*) n, count(distinct merchant_id) stores, "
                 "round(avg(brand_rank)::numeric,1) avg_rank, "
                 "round(avg(brand_sov)::numeric,1) avg_sov "
                 "from search_snapshots where mp_slug=:mp "
                 "group by keyword order by n desc")
        print(f"  {'keyword':<24}{'rows':>6}{'stores':>8}{'avg rank':>10}{'avg SoV':>9}")
        for r in (await db.execute(q, {"mp": MP})).all():
            print(f"  {r[0]:<24}{r[1]:>6}{r[2]:>8}{str(r[3]):>10}{str(r[4]):>9}")

        print(f"\n--- {MP} top brands in listings ---")
        q = text("select brand_slug, count(*) n from search_listings "
                 "where mp_slug=:mp group by brand_slug order by n desc limit 8")
        for r in (await db.execute(q, {"mp": MP})).all():
            print(f"  {r[0]:<28}{r[1]:>6}")

        print(f"\n--- sample {MP} listings ---")
        q = text("select keyword, position, product_name, price, mrp, "
                 "pack_size, pack_uom, in_stock, is_brand "
                 "from search_listings where mp_slug=:mp "
                 "order by keyword, position limit 10")
        print(f"  {'keyword':<20}{'#':<4}{'product':<38}{'price':>8}{'mrp':>8}"
              f"{'pack':>12}{'stock':>7}{'own':>5}")
        for r in (await db.execute(q, {"mp": MP})).all():
            pack = f"{r[5]}{r[6] or ''}" if r[5] else ""
            print(f"  {r[0]:<20}#{str(r[1]):<3}{str(r[2])[:36]:<38}"
                  f"{str(r[3]):>8}{str(r[4]):>8}{pack:>12}"
                  f"{'yes' if r[7] else 'no':>7}{'yes' if r[8] else '':>5}")
        print()


asyncio.run(main())
