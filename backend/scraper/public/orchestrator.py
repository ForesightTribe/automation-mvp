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

from app.models.job import ScrapeJob, JobStatus
from app.models.search import MarketplaceLocation, TenantLocation, SearchSnapshot
from app.models.tenant import Tenant, TenantWatchlist
from app.utils.logger import logger
from scraper.platforms.blinkit.public_data import endpoints as ep
from scraper.platforms.blinkit.public_data import parser as bl_parser
from scraper.platforms.blinkit.public_data import scraper as bl_scraper
from scraper.platforms.blinkit.public_data import storage as bl_storage
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


async def run_tenant(
    db: AsyncSession, tenant_id, cap: int | None = None,
    keyword: str | None = None, city: str | None = None,
    resume: bool = False,
) -> dict:
    """Scrape a tenant's whole Blinkit watchlist across its selected locations.
    `keyword`/`city` narrow the run to a single keyword or city (just-in-case).
    `resume` continues the tenant's last incomplete job, skipping (keyword, store)
    pairs it already saved — each fresh run is otherwise a new full job."""
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
    rows = snapshots = errors = skipped = 0
    ensured: set[str] = set()  # brand slugs upserted this run (ensure_refs once each)

    try:
        async with async_playwright() as pw:
            # One session for the whole run: pay the ~13s browser warmup once, then
            # sweep stores by swapping the lat/lon headers (Blinkit picks the store
            # from those). See scraper.search(lat=, lon=).
            session = await bl_scraper.open_session(pw, locations[0].lat, locations[0].lon)
            if not session:
                raise RuntimeError("failed to open Blinkit session")
            stale = 0  # consecutive failed fetches across stores → session expiry
            total_stores = len(locations)
            try:
                for idx, loc in enumerate(locations, 1):
                    store_fail = 0
                    store_snaps = store_rows = 0
                    store_fetch = store_db = 0.0
                    for keyword, brands in kw_map.items():
                        if store_fail >= _STORE_SKIP_AFTER:
                            break  # unserviceable store — skip its remaining keywords
                        if (keyword, loc.lat, loc.lon) in done:
                            skipped += 1
                            continue  # already scraped under this (resumed) job
                        _t = time.monotonic()
                        try:
                            res = await bl_scraper.search(session, keyword, cap, lat=loc.lat, lon=loc.lon)
                        except Exception as e:
                            logger.debug(f"orchestrator: search '{keyword}' @ {loc.city} error: {e}")
                            res = {"ok": False, "products": [], "merchant_id": "", "total_results": 0}
                        store_fetch += time.monotonic() - _t

                        if not res.get("ok"):
                            store_fail += 1
                            stale += 1
                            errors += 1
                            if stale >= _REFRESH_AFTER:
                                logger.info("orchestrator: session looks stale — refreshing")
                                await bl_scraper.close_session(session)
                                session = await bl_scraper.open_session(pw, loc.lat, loc.lon)
                                stale = 0
                                if not session:
                                    raise RuntimeError("session refresh failed")
                            continue

                        stale = 0
                        if not res["products"]:
                            continue
                        for brand_slug, aliases in brands:
                            raw = {
                                "platform": MP, "keyword": keyword, "brand_slug": brand_slug,
                                "city": loc.city, "zone": loc.zone, "pincode": loc.pincode,
                                "lat": loc.lat, "lon": loc.lon, "aliases": aliases,
                                # Declared competitors → whitelist; none declared → keep all
                                # (discovery mode: see who shows up, then narrow later).
                                "competitors": competitor_list or None,
                                "merchant_id": res["merchant_id"], "total_results": res["total_results"],
                                "products": res["products"],
                            }
                            result = bl_parser.parse(raw)
                            _t = time.monotonic()
                            n = await bl_storage.save(db, result, tid, job_id, ensured)
                            store_db += time.monotonic() - _t
                            rows += n
                            store_rows += n
                            snapshots += 1
                            store_snaps += 1

                    logger.info(
                        f"[{idx}/{total_stores}] {loc.city:<16} "
                        f"{store_snaps} kw · {store_rows} rows   "
                        f"[fetch {store_fetch:5.1f}s · db {store_db:4.1f}s]  "
                        f"| run: {snapshots} snap, {rows} rows, {errors} err"
                    )
                    await asyncio.sleep(_PACING)
            finally:
                if session:
                    await bl_scraper.close_session(session)

        await complete_scrape_job(db, job_id, rows)
    except Exception as e:
        await fail_scrape_job(db, job_id, str(e))
        logger.error(f"orchestrator: tenant {tid} run failed: {e}")
        raise

    summary.update(snapshots=snapshots, rows=rows, errors=errors, skipped=skipped)
    logger.info(
        f"orchestrator: tenant {tid} done — {snapshots} snapshots, {rows} rows, "
        f"{errors} errors, {skipped} skipped, job={job_id}"
    )
    return summary


async def run_all(
    db: AsyncSession, cap: int | None = None,
    keyword: str | None = None, city: str | None = None,
) -> list[dict]:
    """Run every active tenant. Each gets its own scrape_job."""
    tenants = (await db.execute(
        select(Tenant).where(Tenant.is_active == True)  # noqa: E712
    )).scalars().all()
    out = []
    for t in tenants:
        out.append(await run_tenant(db, t.id, cap, keyword, city))
    return out
