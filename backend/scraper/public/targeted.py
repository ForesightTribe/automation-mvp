"""Targeted own-SKU orchestrator (Blinkit).

The companion to `orchestrator.py`. Where that runs category keywords for SoV/rank
+ competitors, this runs each tenant's **brand name** as the query and paginates
the whole catalog (up to `brand_cap`), so every own SKU is captured at every store
regardless of whether it surfaces in a category-keyword search. Own-brand only;
writes the flat `sku_snapshots` fact table (price / mrp / discount / stock /
inventory / rating), keyed on `platform_product_id`.

Same machinery as the keyword orchestrator: one browser, N context-workers pulling
stores off a shared queue. Results are staged to a local SQLite file (no DB session
during the scrape — see `staging.py`); `--resume` skips stores already staged.
"""
import asyncio
import time
import uuid

from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import MarketplaceLocation, TenantLocation
from app.models.tenant import Tenant, TenantWatchlist
from app.utils.logger import logger
from scraper.platforms.blinkit.public_data import endpoints as ep
from scraper.platforms.blinkit.public_data import scraper as bl_scraper
from scraper.public import staging
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.search_result import classify_products

MP = "blinkit"
DASHBOARD = "public_skus"

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a store → skip its remaining brands
_REFRESH_AFTER = 8      # consecutive failed fetches across stores → session stale, re-open
_PACING = 0.05


def _brand_query(brand_slug: str, aliases: list[str]) -> str:
    """The search string for a brand: its first alias (the natural name) or the
    de-slugged brand_slug ('bombay-banta' → 'bombay banta')."""
    if aliases:
        return aliases[0]
    return brand_slug.replace("-", " ")


async def _own_brands(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[str, list[str], int]]:
    """(brand_slug, aliases, brand_cap) for each own brand the tenant tracks."""
    rows = (await db.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        )
    )).scalars().all()
    return [(e.brand_slug, e.aliases or [], e.brand_cap or ep.BRAND_RESULT_CAP) for e in rows]


async def _locations(db: AsyncSession, tenant_id: uuid.UUID) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == MP)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()


async def _worker(
    wid, browser, seed, queue, brands, done, stg, stats, total, tid, job_id,
) -> None:
    """One concurrent worker: own browser context + session, pulling stores off the
    shared queue until empty. Per store, runs each own brand's query and stages its
    own-brand listings. Holds no DB session — see scraper/public/staging.py."""
    session = await bl_scraper.open_context_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"worker {wid}: could not open session — exiting")
        return
    stale = 0
    try:
        while True:
            try:
                loc = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if (loc.lat, loc.lon) in done:
                stats["skipped"] += 1
                stats["processed"] += 1
                continue

            store_fail = 0
            store_rows = 0
            store_fetch = store_db = 0.0
            for brand_slug, aliases, brand_cap in brands:
                if store_fail >= _STORE_SKIP_AFTER:
                    break
                query = _brand_query(brand_slug, aliases)
                _t = time.monotonic()
                try:
                    # Brand scrape follows the similarity tail — Blinkit returns
                    # only ~18 own products as `basic`, the rest as similarity;
                    # own-only classification discards non-own padding.
                    res = await bl_scraper.search(
                        session, query, brand_cap,
                        lat=loc.lat, lon=loc.lon, follow_similarity=True,
                    )
                except Exception as e:
                    res = {"ok": False, "products": [], "error": f"{type(e).__name__}: {e}"}
                store_fetch += time.monotonic() - _t

                if not res.get("ok"):
                    store_fail += 1
                    stale += 1
                    stats["errors"] += 1
                    logger.warning(
                        f"w{wid} {loc.city} brand '{query}' failed: "
                        f"{res.get('error') or 'no result'}"
                    )
                    if stale >= _REFRESH_AFTER:
                        await bl_scraper.close_session(session)
                        session = await bl_scraper.open_context_session(browser, loc.lat, loc.lon)
                        stale = 0
                        if not session:
                            logger.warning(f"worker {wid}: session refresh failed — exiting")
                            return
                    continue

                stale = 0
                if not res["products"]:
                    continue
                # Own-brand only: empty competitor whitelist keeps just is_brand rows.
                cls = classify_products(res["products"], brand_slug, aliases, competitors=[])
                listings = cls["listings"]
                if not listings:
                    continue
                _t = time.monotonic()
                n = await staging.save_skus(
                    stg, listings, brand_slug, tid, job_id,
                    merchant_id=res.get("merchant_id", ""),
                    city=loc.city, lat=loc.lat, lon=loc.lon,
                )
                store_db += time.monotonic() - _t
                stats["rows"] += n
                store_rows += n

            stats["processed"] += 1
            logger.info(
                f"[{stats['processed']}/{total}] w{wid} {loc.city:<15} "
                f"{store_rows} skus  [fetch {store_fetch:5.1f}s stage {store_db:4.1f}s]  "
                f"| {stats['rows']} rows, {stats['errors']} err"
            )
            await asyncio.sleep(_PACING)
    finally:
        if session:
            await bl_scraper.close_session(session)


async def run_targeted(
    db: AsyncSession, tenant_id, cap: int | None = None,
    city: str | None = None, resume: bool = False, workers: int = 5,
) -> dict:
    """Scrape a tenant's own catalog (brand query) across its locations, writing
    `sku_snapshots`. `cap` overrides every brand's brand_cap for this run. `city`
    narrows to one city. `resume` continues the last incomplete run, skipping
    already-scraped stores. `workers` is the concurrent pool size."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))

    brands = await _own_brands(db, tid)
    if cap:  # CLI override wins over each brand's configured cap
        brands = [(slug, aliases, cap) for slug, aliases, _ in brands]
    locations = await _locations(db, tid)
    if city:
        locations = [l for l in locations if l.city == city]
    summary = {
        "tenant_id": str(tid), "brands": len(brands), "locations": len(locations),
        "rows": 0, "errors": 0, "skipped": 0, "job_id": None,
    }
    if not brands:
        logger.warning(f"targeted: tenant {tid} has no own brands — skipping")
        return summary
    if not locations:
        logger.warning(f"targeted: tenant {tid} has no Blinkit locations — skipping")
        return summary

    # Staged locally, not written to Postgres here — see scraper/public/staging.py.
    if resume:
        prev = staging.resumable(staging.KIND_SKUS, tid)
        if not prev:
            logger.warning(f"targeted: no unloaded staging run to resume for tenant {tid}")
            return summary
        stg = staging.open_run(prev["path"])
        done = staging.done_stores(stg)
        logger.info(f"targeted: resuming {prev['path'].name} — {len(done)} stores already staged")
    else:
        stg = staging.new_run(tid, staging.KIND_SKUS)
        done = set()
    job_id = stg["job_id"]
    summary["job_id"] = job_id
    summary["staging_file"] = stg["path"].name
    stats = {"rows": 0, "errors": 0, "skipped": 0, "processed": 0}
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    n_workers = max(1, min(workers, total))

    # All DB reads are done — the scrape stages to SQLite and touches no database.
    # Release the pooled connection so it isn't held idle across the scrape and dropped
    # (surfacing as a spurious SQLAlchemy error at the end). See orchestrator.py.
    await db.close()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            try:
                logger.info(
                    f"targeted: tenant {tid} — {n_workers} workers × {total} stores, "
                    f"{len(brands)} brand(s)"
                )
                tasks = [
                    asyncio.create_task(_worker(
                        w, browser, seed, queue, brands, done, stg, stats, total, tid, job_id,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)
            finally:
                await browser.close()
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, "success")
    except Exception as e:
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, "failed", str(e))
        logger.error(f"targeted: tenant {tid} run failed: {e}")
        raise
    finally:
        staging.close(stg)

    summary.update(rows=stats["rows"], errors=stats["errors"],
                   skipped=stats["skipped"], status="success")
    logger.info(
        f"targeted: tenant {tid} done — {stats['rows']} sku rows, "
        f"{stats['errors']} errors, {stats['skipped']} skipped"
    )
    logger.info(
        f"targeted: staged to {stg['path'].name} — NOT yet in the database. "
        f"Push it with:  python -m cli scrape load"
    )
    return summary


async def run_all_targeted(
    db: AsyncSession, cap: int | None = None, city: str | None = None, workers: int = 5,
    on_tenant_done=None,
) -> list[dict]:
    """Run the targeted own-SKU scrape for every active tenant.

    `on_tenant_done(summary)` is awaited after each tenant — the CLI loads that
    tenant's staging file immediately, so a later tenant failing can't strand the
    earlier ones. See orchestrator.run_all.
    """
    tenants = (await db.execute(
        select(Tenant).where(Tenant.is_active == True)  # noqa: E712
    )).scalars().all()
    out = []
    for t in tenants:
        summary = await run_targeted(db, t.id, cap, city, workers=workers)
        out.append(summary)
        if on_tenant_done:
            await on_tenant_done(summary)
    return out
