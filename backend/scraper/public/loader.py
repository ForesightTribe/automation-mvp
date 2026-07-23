"""Push a staged SQLite run into Postgres — the "load" half of E→L.

ALL-OR-NOTHING: the whole file goes in inside ONE transaction. If the connection
drops halfway, Postgres rolls back and nothing was written, so a retry is trivially
safe — no bookkeeping, no dedup pass. That matters because public data is
append-only with no upsert and no unique constraint, so a *partially* applied load
would silently duplicate rows on the next attempt.

Verified safe against this database (2026-07-17):
    statement_timeout                   = 2min   -- per STATEMENT; our chunks are ms
    idle_in_transaction_session_timeout = 0      -- nothing kills a long transaction

The cost of atomicity is redoing a failed load from scratch — ~60s, against the
~1.5h scrape it protects. Fine trade.

One thing is NOT a straight copy: `search_listings.snapshot_id` points at a Postgres
serial that only exists after insert, so snapshots go in first and each listing's
local parent id is remapped to the real one.

See `staging.py` for why any of this exists.
"""
import asyncio
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import ScrapeJob, JobStatus
from app.models.search import SearchSnapshot, SearchListing, SkuSnapshot
from app.utils.logger import logger
from scraper.public import staging
from scraper.utils.storage import ensure_refs

# Rows pushed per COPY call. COPY streams, so this only bounds peak memory (~4 MB at
# 20k rows). Bigger is measurably better — per-row cost roughly halves from 5k to 20k
# (0.234 → 0.087 ms/row) because it is dominated by round trips, not data volume.
CHUNK = 20000


def _chunks(rows: list, n: int = CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _dt(v):
    return staging.parse_dt(v)


async def _raw(db: AsyncSession):
    """The underlying asyncpg connection, for COPY. Still inside the SQLAlchemy
    transaction — COPY FROM STDIN participates in it and rolls back with it."""
    return (await (await db.connection()).get_raw_connection()).driver_connection


async def _copy(db: AsyncSession, table: str, columns: list[str], records: list[tuple]) -> None:
    """Bulk-insert via Postgres COPY, in CHUNK-sized batches.

    Measured against this database (2026-07-19, 5000 real rows):

        execute(insert(M), rows)   46.6  ms/row   -- executemany: A ROUND TRIP PER ROW
        insert(M).values(rows)      0.61 ms/row   -- one multi-row statement per chunk
        COPY                        0.15 ms/row

    The first form is what shipped originally and it is a trap: it reads like a bulk
    insert but is not. A 35,802-row load took **28 minutes** and duly died mid-flight
    on a dropped connection. The same load COPYs in ~5 seconds.

    Speed is the whole safety story here: a load that finishes in seconds is one the
    connection has almost no chance to drop under.
    """
    if not records:
        return
    pg = await _raw(db)
    for chunk in _chunks(records):
        await pg.copy_records_to_table(table, records=chunk, columns=columns)


async def load_file(db: AsyncSession, path: Path | str, *, prune: bool = True) -> dict:
    """Load one staging file into Postgres in a single transaction.

    Returns a summary dict. Raises on failure — the caller reports it; the file is
    left untouched and can be retried as-is.
    """
    path = Path(path)
    stg = staging.open_run(path)
    m = staging.meta(stg)
    conn = stg["conn"]

    if m["loaded_at"]:
        staging.close(stg)
        raise ValueError(f"{path.name}: already loaded at {m['loaded_at']}")

    job_id = uuid.UUID(m["job_id"])
    tid = uuid.UUID(m["tenant_id"])

    snaps = [dict(r) for r in conn.execute("SELECT * FROM search_snapshots ORDER BY id")]
    lists = [dict(r) for r in conn.execute("SELECT * FROM search_listings ORDER BY id")]
    skus = [dict(r) for r in conn.execute("SELECT * FROM sku_snapshots ORDER BY id")]
    staging.close(stg)

    total = len(snaps) + len(lists) + len(skus)
    if not total:
        raise ValueError(f"{path.name}: no rows to load")

    logger.info(
        f"loader: {path.name} — {len(snaps)} snapshots, {len(lists)} listings, "
        f"{len(skus)} sku rows (job {m['job_id']})"
    )

    # Every brand slug referenced by any row — the FKs must resolve before insert.
    slugs = {r["brand_slug"] for r in snaps + skus if r.get("brand_slug")}
    slugs |= {r["brand_slug"] for r in lists if r.get("brand_slug")}

    try:
        for slug in sorted(slugs):
            await ensure_refs(db, slug, "blinkit")

        # The scrape_jobs row is created HERE, not at scrape time — so a run that is
        # never loaded leaves no phantom `running` job behind. Timestamps come from
        # the staging metadata, i.e. when the scrape actually happened.
        db.add(ScrapeJob(
            id=job_id,
            tenant_id=tid,
            platform="blinkit",
            dashboard=m["kind"],
            status=JobStatus.success if m["status"] == "success" else JobStatus.failed,
            started_at=_dt(m["started_at"]),
            completed_at=_dt(m["completed_at"]),
            error=m["error"],
            records_written=len(snaps) + len(lists) + len(skus),
            created_at=_dt(m["started_at"]),
        ))
        await db.flush()

        # ── snapshots ────────────────────────────────────────────────────────
        # Ids are pre-allocated from the sequence rather than read back from
        # RETURNING: one round trip, and it removes any reliance on RETURNING coming
        # back in VALUES order (true in Postgres, but not guaranteed by the standard).
        local_to_real: dict[int, int] = {}
        if snaps:
            got = await db.execute(text(
                "SELECT nextval(pg_get_serial_sequence('search_snapshots','id')) "
                "FROM generate_series(1, :n)"
            ), {"n": len(snaps)})
            new_ids = [r[0] for r in got.fetchall()]
            local_to_real = {s["id"]: nid for s, nid in zip(snaps, new_ids)}

            await _copy(db, "search_snapshots", [
                "id", "tenant_id", "job_id", "brand_slug", "mp_slug", "keyword", "city",
                "zone", "pincode", "lat", "lon", "merchant_id", "scraped_at",
                "brand_rank", "brand_sov", "total_results",
            ], [(
                local_to_real[r["id"]], tid, job_id, r["brand_slug"], r["mp_slug"],
                r["keyword"], r["city"], r["zone"], r["pincode"], r["lat"], r["lon"],
                r["merchant_id"] or "", _dt(r["scraped_at"]), r["brand_rank"],
                r["brand_sov"], r["total_results"],
            ) for r in snaps])
            logger.info(f"loader: {len(snaps):,} snapshots copied")

        # ── listings, with snapshot_id remapped ──────────────────────────────
        missing = {r["snapshot_local_id"] for r in lists} - set(local_to_real)
        if missing:
            raise RuntimeError(f"{len(missing)} listings reference unknown snapshots")

        # `extra` is a json column: asyncpg's COPY wants the encoded text, not a dict.
        await _copy(db, "search_listings", [
            "snapshot_id", "tenant_id", "job_id", "mp_slug", "brand_slug", "keyword",
            "city", "zone", "pincode", "scraped_at", "position", "product_name",
            "is_brand", "price", "mrp", "discount_pct", "in_stock", "inventory",
            "platform_product_id", "merchant_id", "merchant_type", "is_combo", "extra",
        ], [(
            local_to_real[r["snapshot_local_id"]], tid, job_id, r["mp_slug"],
            r["brand_slug"], r["keyword"], r["city"], r["zone"], r["pincode"],
            _dt(r["scraped_at"]), r["position"], r["product_name"], bool(r["is_brand"]),
            r["price"], r["mrp"], r["discount_pct"], bool(r["in_stock"]), r["inventory"],
            r["platform_product_id"], r["merchant_id"] or "", r["merchant_type"] or "",
            bool(r["is_combo"]), r["extra"] or None,
        ) for r in lists])
        if lists:
            logger.info(f"loader: {len(lists):,} listings copied")

        # ── sku snapshots (no FK to remap) ───────────────────────────────────
        await _copy(db, "sku_snapshots", [
            "tenant_id", "job_id", "mp_slug", "brand_slug", "platform_product_id",
            "product_name", "merchant_id", "merchant_type", "city", "lat", "lon",
            "scraped_at", "price", "mrp", "discount_pct", "in_stock", "inventory",
            "rating", "is_combo",
        ], [(
            tid, job_id, r["mp_slug"], r["brand_slug"], r["platform_product_id"],
            r["product_name"], r["merchant_id"] or "", r["merchant_type"] or "",
            r["city"], r["lat"], r["lon"], _dt(r["scraped_at"]), r["price"], r["mrp"],
            r["discount_pct"], bool(r["in_stock"]), r["inventory"], r["rating"],
            bool(r["is_combo"]),
        ) for r in skus])
        if skus:
            logger.info(f"loader: {len(skus):,} sku rows copied")

        await db.commit()   # ← the single all-or-nothing boundary

    except Exception:
        await db.rollback()
        logger.error(f"loader: {path.name} FAILED — rolled back, nothing written. "
                     f"The file is unchanged; retry with the same command.")
        raise

    staging.mark_loaded(path)
    logger.info(f"loader: {path.name} loaded — {total} rows, job {m['job_id']}")

    pruned = []
    if prune:
        pruned = staging.prune(m["tenant_id"], m["kind"])

    return {
        "file": path.name, "job_id": m["job_id"], "kind": m["kind"],
        "tenant_id": m["tenant_id"], "snapshots": len(snaps),
        "listings": len(lists), "skus": len(skus), "total": total,
        "pruned": len(pruned),
    }


# Backoff between load attempts. A dropped connection usually recovers in seconds;
# beyond three tries the database is genuinely unavailable and the file should just
# stay pending for a human.
_RETRY_DELAYS = (2.0, 5.0, 10.0)


async def load_with_retry(path: Path | str, *, attempts: int = 3, prune: bool = True) -> dict:
    """Load one staging file, retrying connection-level failures.

    Each attempt gets a FRESH session: a dropped connection cannot be reused, and the
    pool entry behind it is poisoned. Retrying is safe by construction — the load is a
    single all-or-nothing transaction, so a failed attempt wrote nothing (public data
    is append-only with no upsert, so a *partial* load would duplicate).

    Raises the last error if every attempt fails; the file is left untouched and
    `cli scrape load --file <ref>` retries it later.
    """
    from app.core.database import AsyncSessionLocal

    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            async with AsyncSessionLocal() as db:
                return await load_file(db, path, prune=prune)
        except DBAPIError as e:
            last = e
            if i == attempts:
                break
            delay = _RETRY_DELAYS[min(i - 1, len(_RETRY_DELAYS) - 1)]
            logger.warning(
                f"loader: attempt {i}/{attempts} failed on a connection error — "
                f"retrying in {delay:.0f}s"
            )
            await asyncio.sleep(delay)
    raise last if last else RuntimeError("load failed")
