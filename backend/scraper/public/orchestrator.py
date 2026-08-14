"""Public-scraper orchestrator — the keyword scrape.

Turns a tenant's watchlist + selected locations into scrapes:
  watchlist (own brands → keywords + aliases)  ×  tenant_locations (where)
For each location it opens ONE browser session and runs every keyword as an
in-page fetch (session reused across keywords — the batching win), classifies the
result against each own brand that tracks that keyword, and writes per-tenant
snapshot + listing rows under a single scrape_job.

Locations come entirely from the DB (`marketplace_locations` via
`tenant_locations`) — never `cities.py`.

**Marketplace-agnostic.** The engine is resolved through `scraper/public/providers.py`
(`open_session` / `search` / `close_session` / `parse`), so nothing below this line
knows which platform it is driving. Everything platform-specific — endpoints,
extraction, the store-binding mechanism — lives in that marketplace's
`public_data/` package. `mp_slug` also selects the locations and stamps the staged
rows. See docs/zepto.md.
"""
import asyncio
import random
import time
import uuid

from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search import MarketplaceLocation, TenantLocation
from app.models.tenant import Tenant, TenantWatchlist
from app.utils.logger import logger
from scraper.public import staging
from scraper.public.providers import DEFAULT_MARKETPLACE, get_provider
from scraper.utils.browser import PLAYWRIGHT_ARGS

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a store → skip its remaining keywords
_REFRESH_AFTER = 8      # consecutive failed fetches across stores → session likely stale, re-open
_JITTER_FRAC = 0.15     # ± spread on the block-recovery wait, so workers stop retrying in lockstep


def _jittered(base_s: float) -> float:
    """`base_s` ± `_JITTER_FRAC`. All 5 workers hit the same block within seconds of
    each other (they run the same keyword list at the same pace), so an un-jittered
    wait means they also RECOVER within seconds of each other and retry in one
    synchronized burst — observed directly: gets blocked again immediately, every
    time. Spreading the wake-up time breaks that lockstep."""
    spread = base_s * _JITTER_FRAC
    return base_s + random.uniform(-spread, spread)
# Pacing moved onto Provider — it is per-marketplace, not global. Blinkit has no
# volume cap and runs 5 workers at 0.05 s between stores; Zepto enforces one and
# dies after a single search at that rate. See scraper/public/providers.py.


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


async def _keyword_cap(db: AsyncSession, tenant_id: uuid.UUID) -> int | None:
    """The tenant's configured keyword_cap (first own row that sets one), or None."""
    rows = (await db.execute(
        select(TenantWatchlist.keyword_cap).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
            TenantWatchlist.keyword_cap.is_not(None),
        )
    )).scalars().all()
    return rows[0] if rows else None


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


async def _locations(db: AsyncSession, tenant_id: uuid.UUID,
                     mp_slug: str) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == mp_slug)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()


async def _worker(
    wid, provider, browser, seed, queue, kw_map, competitor_list, done,
    stg, stats, total, tid, job_id, cap, misses,
) -> None:
    """One concurrent worker: its own browser context + session, pulling stores off
    the shared queue until it's empty.

    Holds NO database session — results are staged to the run's local SQLite file and
    pushed to Postgres later by `cli scrape load`. That decoupling is why a Supabase
    blip can no longer kill a multi-hour run. See scraper/public/staging.py.

    `misses` is a shared list (safe to append from any worker without a lock — no
    `await` happens between the check and the append, so no other task can interleave)
    collecting every (location, keyword) pair that gave up after both attempts. After
    every worker has drained the main queue, `run_tenant` runs one more pass over just
    this list — see the backlog pass there. A keyword that fails there too is genuinely
    left out of this run, not queued forever.
    """
    session = await provider.open_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"worker {wid}: could not open session — exiting")
        return
    stale = 0
    searches = 0        # since this worker's last rest, for provider.pause_every
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

                # Scheduled rest, for a marketplace with a volume cap. Resting
                # BEFORE the wall is cheaper than crashing into it: recovery from a
                # hard block yields ~3 searches per 5-minute cycle, while a clean
                # pause resets the window. No-op when pause_every is None (Blinkit).
                if provider.pause_every and searches >= provider.pause_every:
                    logger.info(f"w{wid} scheduled rest {provider.pause_s // 60} min "
                                f"after {searches} searches")
                    await asyncio.sleep(provider.pause_s)
                    searches = 0
                    await provider.close_session(session)
                    session = await provider.open_session(browser, loc.lat, loc.lon)
                    if not session:
                        logger.warning(f"worker {wid}: session refresh failed after "
                                       f"rest — exiting")
                        return

                # Up to 2 attempts at THIS keyword: the plain fetch, plus — only if
                # it comes back blocked — one retry after a confirmed-successful
                # session recovery. A BLOCK is not a failure to retry blind (that
                # prolongs it), but a session that reopens successfully after the
                # wait is proof the block has actually lifted, and discarding the
                # keyword anyway at that point just throws away data we've already
                # paid the wait for. One retry, not unbounded: if it blocks again
                # immediately, something more persistent is wrong and hammering
                # this one keyword further only delays the rest of the queue.
                give_up = False
                for attempt in range(2):
                    _t = time.monotonic()
                    try:
                        # merchant_id as well as the coordinate: marketplaces bind in
                        # opposite directions (D8). Blinkit ignores it; Zepto needs it,
                        # or it spends a second rate-limited endpoint resolving a store
                        # this loop already has in hand.
                        res = await provider.search(session, keyword, cap,
                                                    lat=loc.lat, lon=loc.lon,
                                                    merchant_id=loc.merchant_id)
                    except Exception as e:
                        res = {"ok": False, "products": [], "merchant_id": "",
                               "total_results": 0, "error": f"{type(e).__name__}: {e}"}
                    store_fetch += time.monotonic() - _t
                    searches += 1

                    # Pace HERE, not at the end of the loop. Every branch below can
                    # `continue`/`break` out early, and an empty result is the
                    # commonest of them — on Zepto 'sourdough bread loaf' returns
                    # 0-6 products at most stores. Pacing after those branches means
                    # the thinnest keywords fire back to back with no gap at all,
                    # which is what blocked five workers in 37 seconds.
                    if provider.search_gap_s:
                        await asyncio.sleep(provider.search_gap_s)

                    if res.get("blocked") and provider.probe_every_s:
                        waits = 0
                        while waits < provider.max_block_waits:
                            waits += 1
                            logger.warning(
                                f"w{wid} {loc.city} '{keyword}' BLOCKED — waiting "
                                f"{provider.probe_every_s // 60} min "
                                f"({waits}/{provider.max_block_waits})"
                            )
                            await asyncio.sleep(_jittered(provider.probe_every_s))
                            await provider.close_session(session)
                            session = await provider.open_session(browser, loc.lat, loc.lon)
                            if session:
                                break
                        if not session:
                            logger.warning(f"worker {wid}: still blocked after "
                                           f"{waits} waits — exiting")
                            return
                        searches = 0
                        stats["errors"] += 1
                        if attempt == 0:
                            logger.info(
                                f"w{wid} {loc.city} '{keyword}' recovered — retrying"
                            )
                            continue
                        # Only counts as ONE store failure for `_STORE_SKIP_AFTER`,
                        # not one per attempt — this keyword got two tries (see
                        # above) precisely so a single flaky keyword can't, on its
                        # own, trip a threshold meant for distinct keyword failures.
                        store_fail += 1
                        give_up = True
                        misses.append((loc, keyword))
                        break

                    break  # a real (non-blocked) response — done with this keyword

                if give_up:
                    continue

                if not res.get("ok"):
                    store_fail += 1
                    stale += 1
                    stats["errors"] += 1
                    logger.warning(
                        f"w{wid} {loc.city} '{keyword}' failed: "
                        f"{res.get('error') or 'no result'}"
                    )
                    if stale >= _REFRESH_AFTER:
                        await provider.close_session(session)
                        session = await provider.open_session(browser, loc.lat, loc.lon)
                        stale = 0
                        if not session:
                            logger.warning(f"worker {wid}: session refresh failed — exiting")
                            return
                    continue

                stale = 0
                if not res["products"]:
                    continue
                # The catalog says this coordinate is served by loc.merchant_id;
                # the response says otherwise. Free store-moved/closed/opened
                # alarm — the mapping has held on every location probed so far,
                # so a mismatch is worth a look, not a silent overwrite. The
                # OBSERVED store is what gets stored; the catalog is the claim.
                if res["merchant_id"] and res["merchant_id"] != loc.merchant_id:
                    logger.warning(
                        f"w{wid} {loc.city}/{loc.location_name}: express store is "
                        f"{res['merchant_id']}, catalog says {loc.merchant_id} — "
                        f"store moved/closed, or the coordinate drifted?"
                    )
                for brand_slug, aliases in brands:
                    raw = {
                        "platform": provider.slug, "keyword": keyword, "brand_slug": brand_slug,
                        "city": loc.city, "zone": loc.location_name, "pincode": loc.pincode,
                        "lat": loc.lat, "lon": loc.lon, "aliases": aliases,
                        "competitors": competitor_list or None,
                        "merchant_id": res["merchant_id"], "total_results": res["total_results"],
                        "products": res["products"],
                    }
                    result = provider.parse(raw)
                    _t = time.monotonic()
                    n = await staging.save_search(stg, result, tid, job_id)
                    store_db += time.monotonic() - _t
                    stats["rows"] += n
                    store_rows += n
                    stats["snapshots"] += 1
                    store_snaps += 1

            stats["processed"] += 1
            logger.info(
                f"[{stats['processed']}/{total}] w{wid} {loc.city:<15} "
                f"{store_snaps} kw · {store_rows} rows  "
                f"[fetch {store_fetch:5.1f}s stage {store_db:4.1f}s]  "
                f"| {stats['snapshots']} snap, {stats['rows']} rows, {stats['errors']} err"
            )
            await asyncio.sleep(provider.store_gap_s)
    finally:
        if session:
            await provider.close_session(session)


async def _retry_worker(
    wid, provider, browser, seed, queue, competitor_list, kw_map,
    stg, stats, tid, job_id, cap,
) -> None:
    """Second-pass worker for the backlog `run_tenant` builds from the main pass's
    misses. Pulls one (location, keyword) pair at a time instead of a whole
    location's keyword list — every pair here already failed twice during the main
    pass, so this gets exactly one more attempt each, not another multi-wait escalation.
    A pair that fails here too is genuinely left out of this run.
    """
    session = await provider.open_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"backlog worker {wid}: could not open session — exiting")
        return
    try:
        while True:
            try:
                loc, keyword = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            brands = kw_map.get(keyword)
            if not brands:
                continue

            try:
                res = await provider.search(session, keyword, cap,
                                            lat=loc.lat, lon=loc.lon,
                                            merchant_id=loc.merchant_id)
            except Exception as e:
                res = {"ok": False, "products": [], "merchant_id": "",
                       "total_results": 0, "error": f"{type(e).__name__}: {e}"}
            if provider.search_gap_s:
                await asyncio.sleep(provider.search_gap_s)

            if res.get("blocked") and provider.probe_every_s:
                # One wait, one look — this pair already had its fair shot in the
                # main pass. Compounding further waits here just delays the rest
                # of the backlog for something that's already twice-failed.
                await asyncio.sleep(_jittered(provider.probe_every_s))
                await provider.close_session(session)
                session = await provider.open_session(browser, loc.lat, loc.lon)
                stats["errors"] += 1
                if not session:
                    logger.warning(f"backlog worker {wid}: still blocked — exiting")
                    return
                continue

            if not res.get("ok") or not res["products"]:
                stats["errors"] += 1
                continue

            for brand_slug, aliases in brands:
                raw = {
                    "platform": provider.slug, "keyword": keyword, "brand_slug": brand_slug,
                    "city": loc.city, "zone": loc.location_name, "pincode": loc.pincode,
                    "lat": loc.lat, "lon": loc.lon, "aliases": aliases,
                    "competitors": competitor_list or None,
                    "merchant_id": res["merchant_id"], "total_results": res["total_results"],
                    "products": res["products"],
                }
                result = provider.parse(raw)
                n = await staging.save_search(stg, result, tid, job_id)
                stats["rows"] += n
                stats["snapshots"] += 1
            stats["recovered"] = stats.get("recovered", 0) + 1
    finally:
        await provider.close_session(session)


async def run_tenant(
    db: AsyncSession, tenant_id, cap: int | None = None,
    keyword: str | None = None, city: str | None = None,
    resume: bool = False, workers: int = 5,
    mp_slug: str = DEFAULT_MARKETPLACE,
) -> dict:
    """Scrape a tenant's whole watchlist across its selected locations on `mp_slug`.
    `keyword`/`city` narrow the run to a single keyword or city. `resume` continues
    the tenant's last incomplete job for THIS marketplace, skipping already-scraped
    stores. `workers` is the concurrent pool size — N isolated browser contexts on
    one browser, each pulling stores off a shared queue."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    provider = get_provider(mp_slug)
    # Precedence: CLI --cap > tenant's configured keyword_cap > the platform's floor.
    cap = cap or await _keyword_cap(db, tid) or provider.result_cap

    kw_map = await _own_keyword_map(db, tid)
    if keyword:
        kw_map = {k: v for k, v in kw_map.items() if k == keyword}
    locations = await _locations(db, tid, mp_slug)
    if city:
        locations = [l for l in locations if l.city == city]
    competitor_list = await _competitor_list(db, tid)
    summary = {
        "tenant_id": str(tid), "mp_slug": mp_slug,
        "keywords": len(kw_map), "locations": len(locations),
        "snapshots": 0, "rows": 0, "errors": 0, "skipped": 0, "job_id": None,
    }
    if not kw_map:
        logger.warning(f"orchestrator: tenant {tid} has no own-brand keywords — skipping")
        return summary
    if not locations:
        logger.warning(
            f"orchestrator: tenant {tid} has no {provider.name} locations — skipping"
        )
        return summary

    # Results are staged to a local SQLite file, NOT written to Postgres here — see
    # scraper/public/staging.py. `cli scrape load` pushes the file afterwards.
    if resume:
        prev = staging.resumable(staging.KIND_SEARCH, tid, mp_slug)
        if not prev:
            logger.warning(
                f"orchestrator: no unloaded {mp_slug} staging run to resume for tenant {tid}"
            )
            return summary
        stg = staging.open_run(prev["path"])
        done = staging.done_pairs(stg)
        logger.info(f"orchestrator: resuming {prev['path'].name} — "
                    f"{len(done)} (keyword,store) pairs already staged")
    else:
        stg = staging.new_run(tid, staging.KIND_SEARCH, mp_slug)
        done = set()
    job_id = stg["job_id"]
    summary["job_id"] = job_id
    summary["staging_file"] = stg["path"].name
    stats = {"snapshots": 0, "rows": 0, "errors": 0, "skipped": 0, "processed": 0}
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    n_workers = max(1, min(workers, total))

    # Every DB read is done — the scrape stages to SQLite and touches no database.
    # Release the pooled connection now: held open across a ~1.5h scrape it goes idle,
    # the Supabase pooler / home NAT silently drops it, and closing it later raises a
    # spurious SQLAlchemy error at the end of an otherwise-clean run. `locations` are
    # already-loaded ORM rows and stay readable detached (expire_on_commit=False).
    await db.close()

    # Every (location, keyword) pair that gave up after both main-pass attempts
    # lands here — shared across workers, appended with no `await` between check
    # and append so it's safe without a lock. See the backlog pass below.
    misses: list = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            try:
                logger.info(
                    f"orchestrator: tenant {tid} on {mp_slug} — {n_workers} workers × "
                    f"{total} stores, cap={cap}"
                )
                tasks = [
                    asyncio.create_task(_worker(
                        w, provider, browser, seed, queue, kw_map, competitor_list, done,
                        stg, stats, total, tid, job_id, cap, misses,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)

                # Backlog pass: one more look at everything the main pass gave up
                # on, now that the main queue is fully drained (so this can't
                # starve stores still waiting their first attempt). Same browser,
                # so no new launch overhead.
                if misses:
                    logger.info(
                        f"orchestrator: main pass done — {len(misses)} misses, "
                        f"running one backlog pass to close them"
                    )
                    retry_queue: asyncio.Queue = asyncio.Queue()
                    for item in misses:
                        retry_queue.put_nowait(item)
                    retry_tasks = [
                        asyncio.create_task(_retry_worker(
                            w, provider, browser, seed, retry_queue, competitor_list,
                            kw_map, stg, stats, tid, job_id, cap,
                        ))
                        for w in range(1, min(n_workers, len(misses)) + 1)
                    ]
                    await asyncio.gather(*retry_tasks)
                    logger.info(
                        f"orchestrator: backlog pass done — "
                        f"{stats.get('recovered', 0)}/{len(misses)} recovered"
                    )
            finally:
                await browser.close()
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, "success")
    except Exception as e:
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, "failed", str(e))
        logger.error(f"orchestrator: tenant {tid} run failed: {e}")
        raise
    finally:
        staging.close(stg)

    summary.update(snapshots=stats["snapshots"], rows=stats["rows"],
                   errors=stats["errors"], skipped=stats["skipped"], status="success")
    logger.info(
        f"orchestrator: tenant {tid} done — {stats['snapshots']} snapshots, "
        f"{stats['rows']} rows, {stats['errors']} errors, {stats['skipped']} skipped"
    )
    logger.info(
        f"orchestrator: staged to {stg['path'].name} — NOT yet in the database. "
        f"Push it with:  python -m cli scrape load"
    )
    return summary


async def run_all(
    db: AsyncSession, cap: int | None = None,
    keyword: str | None = None, city: str | None = None, workers: int = 5,
    on_tenant_done=None, mp_slug: str = DEFAULT_MARKETPLACE,
) -> list[dict]:
    """Run every active tenant, each into its own staging file.

    `on_tenant_done(summary)` is awaited after each tenant finishes — the CLI uses it
    to load that tenant's staging file immediately rather than waiting for the whole
    sweep. On a weekly scheduled run that matters: one tenant failing (or the process
    dying at tenant 7 of 9) must not strand the six tenants already scraped.
    """
    tenants = (await db.execute(
        select(Tenant).where(Tenant.is_active == True)  # noqa: E712
    )).scalars().all()
    out = []
    for t in tenants:
        summary = await run_tenant(db, t.id, cap, keyword, city,
                                   workers=workers, mp_slug=mp_slug)
        out.append(summary)
        if on_tenant_done:
            await on_tenant_done(summary)
    return out
