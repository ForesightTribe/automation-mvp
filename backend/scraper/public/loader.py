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
import json
import uuid
from pathlib import Path

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import ScrapeJob, JobStatus
from app.models.search import SearchSnapshot, SearchListing, SkuSnapshot
from app.utils.logger import logger
from scraper.public import staging
from scraper.utils.storage import ensure_refs

# Rows per INSERT. Keeps each statement far inside statement_timeout and bounds the
# parameter count (Postgres caps at 65535 bind params; ~23 cols × 1000 ≈ 23k).
CHUNK = 1000


def _chunks(rows: list, n: int = CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _dt(v):
    return staging.parse_dt(v)


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

        # ── snapshots, capturing the real ids ────────────────────────────────
        local_to_real: dict[int, int] = {}
        for chunk in _chunks(snaps):
            rows = [{
                "tenant_id": tid, "job_id": job_id, "brand_slug": r["brand_slug"],
                "mp_slug": r["mp_slug"], "keyword": r["keyword"], "city": r["city"],
                "zone": r["zone"], "pincode": r["pincode"], "lat": r["lat"],
                "lon": r["lon"], "merchant_id": r["merchant_id"] or "",
                "scraped_at": _dt(r["scraped_at"]), "brand_rank": r["brand_rank"],
                "brand_sov": r["brand_sov"], "total_results": r["total_results"],
            } for r in chunk]
            res = await db.execute(insert(SearchSnapshot).returning(SearchSnapshot.id), rows)
            new_ids = [row[0] for row in res.fetchall()]
            if len(new_ids) != len(chunk):
                raise RuntimeError(
                    f"snapshot id remap failed: inserted {len(new_ids)} of {len(chunk)}"
                )
            # SQLAlchemy's insertmanyvalues guarantees RETURNING order matches input.
            for src, new_id in zip(chunk, new_ids):
                local_to_real[src["id"]] = new_id

        # ── listings, with snapshot_id remapped ──────────────────────────────
        missing = {r["snapshot_local_id"] for r in lists} - set(local_to_real)
        if missing:
            raise RuntimeError(f"{len(missing)} listings reference unknown snapshots")

        for chunk in _chunks(lists):
            rows = [{
                "snapshot_id": local_to_real[r["snapshot_local_id"]],
                "tenant_id": tid, "job_id": job_id, "mp_slug": r["mp_slug"],
                "brand_slug": r["brand_slug"], "keyword": r["keyword"],
                "city": r["city"], "zone": r["zone"], "pincode": r["pincode"],
                "scraped_at": _dt(r["scraped_at"]), "position": r["position"],
                "product_name": r["product_name"], "is_brand": bool(r["is_brand"]),
                "price": r["price"], "mrp": r["mrp"], "discount_pct": r["discount_pct"],
                "in_stock": bool(r["in_stock"]), "inventory": r["inventory"],
                "platform_product_id": r["platform_product_id"],
                "merchant_id": r["merchant_id"] or "",
                "merchant_type": r["merchant_type"] or "",
                "is_combo": bool(r["is_combo"]),
                "extra": json.loads(r["extra"]) if r["extra"] else None,
            } for r in chunk]
            await db.execute(insert(SearchListing), rows)

        # ── sku snapshots (no FK to remap) ───────────────────────────────────
        for chunk in _chunks(skus):
            rows = [{
                "tenant_id": tid, "job_id": job_id, "mp_slug": r["mp_slug"],
                "brand_slug": r["brand_slug"],
                "platform_product_id": r["platform_product_id"],
                "product_name": r["product_name"],
                "merchant_id": r["merchant_id"] or "",
                "merchant_type": r["merchant_type"] or "",
                "city": r["city"], "lat": r["lat"], "lon": r["lon"],
                "scraped_at": _dt(r["scraped_at"]), "price": r["price"],
                "mrp": r["mrp"], "discount_pct": r["discount_pct"],
                "in_stock": bool(r["in_stock"]), "inventory": r["inventory"],
                "rating": r["rating"], "is_combo": bool(r["is_combo"]),
            } for r in chunk]
            await db.execute(insert(SkuSnapshot), rows)

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
