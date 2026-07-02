"""Public-scraper orchestrator (Blinkit).

Turns a tenant's watchlist + selected locations into scrapes:
  watchlist (own brands → keywords + aliases)  ×  tenant_locations (where)
For each location it opens ONE browser session and runs every keyword as an
in-page fetch (session reused across keywords — the batching win), classifies the
result against each own brand that tracks that keyword, and writes per-tenant
snapshot + listing rows under a single scrape_job.

Locations come entirely from the DB (`marketplace_locations` via
`tenant_locations`) — never `cities.py`.

v1 is sequential (one location, one keyword at a time). A capped browser pool /
task queue for concurrency is a later refinement; the unit of work is already a
(location, keyword) task, so it slots in without reshaping this.
"""
import asyncio
import time
import uuid

from playwright.async_api import async_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.job import ScrapeJob, JobStatus
from app.models.search import MarketplaceLocation, TenantLocation, SearchSnapshot
from app.models.tenant import Tenant, TenantWatchlist
from app.utils.logger import logger
from scraper.platforms.blinkit.public_data import endpoints as ep
from scraper.platforms.blinkit.public_data import parser as bl_parser
from scraper.platforms.blinkit.public_data import scraper as bl_scraper
from scraper.platforms.blinkit.public_data import storage as bl_storage
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.jobs import complete_scrape_job, create_scrape_job, fail_scrape_job

MP = "blinkit"

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a store → skip its remaining keywords
_REFRESH_AFTER = 8      # consecutive failed fetches across stores → session likely stale, re-open
_PACING = 0.05          # polite gap between stores (seconds)


async def _own_keyword_map(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, list[tuple[str, list[str]]]]:
    """keyword -> [(own_brand_slug, aliases), ...]. Lets a shared keyword be
    classified for every own brand that tracks it, scraping the SERP once."""
    rows = (await db.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        )
    )).scalars().all()
    kw_map: dict[str, list[tuple[str, list[str]]]] = {}
    for e in rows:
        for kw in e.keywords:
            kw_map.setdefault(kw, []).append((e.brand_slug, e.aliases or []))
    return kw_map


async def _competitor_list(db: AsyncSession, tenant_id: uuid.UUID) -> list[tuple[str, list[str]]]:
    """(slug, aliases) of the tenant's declared competitors — the whitelist of
    which competitor products to store (own is always stored). Empty → own only."""
    rows = (await db.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "competitor",
        )
    )).scalars().all()
    return [(e.brand_slug, e.aliases or []) for e in rows]


async def _locations(db: AsyncSession, tenant_id: uuid.UUID) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == MP)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.zone)
    )).scalars().all()


async def _latest_incomplete_job(db: AsyncSession, tid: uuid.UUID) -> str | None:
    """The most recent public_search job for the tenant that didn't succeed —
    the one a --resume picks up."""
    row = (await db.execute(
        select(ScrapeJob.id)
        .where(ScrapeJob.tenant_id == tid,
               ScrapeJob.dashboard == "public_search",
               ScrapeJob.status != JobStatus.success)
        .order_by(ScrapeJob.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return str(row) if row else None


async def _done_pairs(db: AsyncSession, job_id: str) -> set[tuple]:
    """(keyword, lat, lon) already scraped under this job — skipped on resume."""
    rows = (await db.execute(
        select(SearchSnapshot.keyword, SearchSnapshot.lat, SearchSnapshot.lon)
        .where(SearchSnapshot.job_id == uuid.UUID(job_id))
    )).all()
    return {(kw, lat, lon) for kw, lat, lon in rows}


async def _worker(
    wid, browser, seed, queue, kw_map, competitor_list, done,
    ensured, stats, total, tid, job_id, cap,
) -> None:
    """One concurrent worker: its own browser context + session + DB session,
    pulling stores off the shared queue until it's empty."""
    session = await bl_scraper.open_context_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"worker {wid}: could not open session — exiting")
        return
    stale = 0
    async with AsyncSessionLocal() as wdb:
        try:
            while True:
                try:
                    loc = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                store_fail = 0
                store_snaps = store_rows = 0
                store_fetch = store_db = 0.0
                for keyword, brands in kw_map.items():
                    if store_fail >= _STORE_SKIP_AFTER:
                        break
                    if (keyword, loc.lat, loc.lon) in done:
                        stats["skipped"] += 1
                        continue
                    _t = time.monotonic()
                    try:
                        res = await bl_scraper.search(session, keyword, cap, lat=loc.lat, lon=loc.lon)
                    except Exception as e:
                        res = {"ok": False, "products": [], "merchant_id": "",
                               "total_results": 0, "error": f"{type(e).__name__}: {e}"}
                    store_fetch += time.monotonic() - _t

                    if not res.get("ok"):
                        store_fail += 1
                        stale += 1
                        stats["errors"] += 1
                        logger.warning(
                            f"w{wid} {loc.city} '{keyword}' failed: "
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
                    for brand_slug, aliases in brands:
                        raw = {
                            "platform": MP, "keyword": keyword, "brand_slug": brand_slug,
                            "city": loc.city, "zone": loc.zone, "pincode": loc.pincode,
                            "lat": loc.lat, "lon": loc.lon, "aliases": aliases,
                            "competitors": competitor_list or None,
                            "merchant_id": res["merchant_id"], "total_results": res["total_results"],
                            "products": res["products"],
                        }
                        result = bl_parser.parse(raw)
                        _t = time.monotonic()
                        n = await bl_storage.save(wdb, result, tid, job_id, ensured)
                        store_db += time.monotonic() - _t
                        stats["rows"] += n
                        store_rows += n
                        stats["snapshots"] += 1
                        store_snaps += 1

                stats["processed"] += 1
                logger.info(
                    f"[{stats['processed']}/{total}] w{wid} {loc.city:<15} "
                    f"{store_snaps} kw · {store_rows} rows  "
                    f"[fetch {store_fetch:5.1f}s db {store_db:4.1f}s]  "
                    f"| {stats['snapshots']} snap, {stats['rows']} rows, {stats['errors']} err"
                )
                await asyncio.sleep(_PACING)
        finally:
            if session:
                await bl_scraper.close_session(session)


async def run_tenant(
    db: AsyncSession, tenant_id, cap: int | None = None,
    keyword: str | None = None, city: str | None = None,
    resume: bool = False, workers: int = 5,
) -> dict:
    """Scrape a tenant's whole Blinkit watchlist across its selected locations.
    `keyword`/`city` narrow the run to a single keyword or city. `resume` continues
    the tenant's last incomplete job, skipping already-scraped stores. `workers` is
    the concurrent pool size — N isolated browser contexts on one browser, each with
    its own DB session, pulling stores off a shared queue."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    cap = cap or ep.RESULT_CAP

    kw_map = await _own_keyword_map(db, tid)
    if keyword:
        kw_map = {k: v for k, v in kw_map.items() if k == keyword}
    locations = await _locations(db, tid)
    if city:
        locations = [l for l in locations if l.city == city]
    competitor_list = await _competitor_list(db, tid)
    summary = {
        "tenant_id": str(tid), "keywords": len(kw_map), "locations": len(locations),
        "snapshots": 0, "rows": 0, "errors": 0, "skipped": 0, "job_id": None,
    }
    if not kw_map:
        logger.warning(f"orchestrator: tenant {tid} has no own-brand keywords — skipping")
        return summary
    if not locations:
        logger.warning(f"orchestrator: tenant {tid} has no Blinkit locations — skipping")
        return summary

    if resume:
        job_id = await _latest_incomplete_job(db, tid)
        if not job_id:
            logger.warning(f"orchestrator: no incomplete job to resume for tenant {tid}")
            return summary
        done = await _done_pairs(db, job_id)
        await db.execute(
            update(ScrapeJob).where(ScrapeJob.id == uuid.UUID(job_id)).values(status=JobStatus.running)
        )
        await db.commit()
        logger.info(f"orchestrator: resuming job {job_id} — {len(done)} (keyword,store) pairs already done")
    else:
        job_id = await create_scrape_job(db, str(tid), "public_search", MP)
        done = set()
    summary["job_id"] = job_id
    ensured: set[str] = set()  # brand slugs upserted this run (ensure_refs once each)
    stats = {"snapshots": 0, "rows": 0, "errors": 0, "skipped": 0, "processed": 0}
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    n_workers = max(1, min(workers, total))

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            try:
                logger.info(
                    f"orchestrator: tenant {tid} — {n_workers} workers × {total} stores, cap={cap}"
                )
                tasks = [
                    asyncio.create_task(_worker(
                        w, browser, seed, queue, kw_map, competitor_list, done,
                        ensured, stats, total, tid, job_id, cap,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)
            finally:
                await browser.close()
        await complete_scrape_job(db, job_id, stats["rows"])
    except Exception as e:
        await fail_scrape_job(db, job_id, str(e))
        logger.error(f"orchestrator: tenant {tid} run failed: {e}")
        raise

    summary.update(snapshots=stats["snapshots"], rows=stats["rows"],
                   errors=stats["errors"], skipped=stats["skipped"])
    logger.info(
        f"orchestrator: tenant {tid} done — {stats['snapshots']} snapshots, "
        f"{stats['rows']} rows, {stats['errors']} errors, {stats['skipped']} skipped, job={job_id}"
    )
    return summary


async def run_all(
    db: AsyncSession, cap: int | None = None,
    keyword: str | None = None, city: str | None = None, workers: int = 5,
) -> list[dict]:
    """Run every active tenant. Each gets its own scrape_job."""
    tenants = (await db.execute(
        select(Tenant).where(Tenant.is_active == True)  # noqa: E712
    )).scalars().all()
    out = []
    for t in tenants:
        out.append(await run_tenant(db, t.id, cap, keyword, city, workers=workers))
    return out
