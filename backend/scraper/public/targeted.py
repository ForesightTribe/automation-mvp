"""Targeted own-SKU orchestrator — the brand-query scrape.

The companion to `orchestrator.py`. Where that runs category keywords for SoV/rank
+ competitors, this runs each tenant's **brand name** as the query and paginates
the whole catalog (up to `brand_cap`), so every own SKU is captured at every store
regardless of whether it surfaces in a category-keyword search. Own-brand only;
writes the flat `sku_snapshots` fact table (price / mrp / discount / stock /
inventory / rating), keyed on `platform_product_id`.

Same machinery as the keyword orchestrator: one browser, N context-workers pulling
stores off a shared queue, and the marketplace engine resolved through
`scraper/public/providers.py` so nothing here is platform-specific. Results are
staged to a local SQLite file (no DB session during the scrape — see `staging.py`);
`--resume` skips stores already staged.
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
from scraper.public import staging
from scraper.public.orchestrator import _clamp_workers
from scraper.public.providers import DEFAULT_MARKETPLACE, get_provider
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.search_result import classify_products

DASHBOARD = "public_skus"

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a store → skip its remaining brands
_REFRESH_AFTER = 8      # consecutive failed fetches across stores → session stale, re-open
# Pacing is PER MARKETPLACE and comes off the provider — see providers.py. The old
# module-level 0.05 was Blinkit's, applied to every platform: on Zepto it drove 169
# stores in ~1 minute, which trips a 429 by store 60 and the LOGIN_REQUIRED gate by
# store 138. The keyword orchestrator already read these; this one did not.


def _brand_query(brand_slug: str, aliases: list[str]) -> str:
    """The search string for a brand: its first alias (the natural name) or the
    de-slugged brand_slug ('bombay-banta' → 'bombay banta')."""
    if aliases:
        return aliases[0]
    return brand_slug.replace("-", " ")


async def _own_brands(db: AsyncSession, tenant_id: uuid.UUID,
                      default_cap: int) -> list[tuple[str, list[str], int]]:
    """(brand_slug, aliases, brand_cap) for each own brand the tenant tracks."""
    rows = (await db.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        )
    )).scalars().all()
    return [(e.brand_slug, e.aliases or [], e.brand_cap or default_cap) for e in rows]


async def _locations(db: AsyncSession, tenant_id: uuid.UUID,
                     mp_slug: str) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == mp_slug)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()


async def _worker(
    wid, provider, browser, seed, queue, brands, done, stg, stats, total, tid,
    job_id, misses,
) -> None:
    """One concurrent worker: own browser context + session, pulling stores off the
    shared queue until empty. Per store, runs each own brand's query and stages its
    own-brand listings. Holds no DB session — see scraper/public/staging.py.

    `misses` is a shared list (safe to append without a lock — no `await` happens
    between the check and the append) collecting every (location, brand) pair that
    gave up. `run_targeted` runs one backlog pass over them after the main queue
    drains, exactly as the keyword orchestrator does. Without it a store that
    failed twice is simply absent from the run, and `--resume` cannot recover it
    either — resume skips stores that HAVE rows, so a failed store stays skipped.
    """
    session = await provider.open_session(browser, seed[0], seed[1])
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
                    # own-only classification discards non-own padding. A provider
                    # without that distinction may ignore the flag.
                    #
                    # `merchant_id` is REQUIRED, not optional. On a marketplace that
                    # binds by store id (Zepto), omitting it makes the engine resolve
                    # the store from the coordinate instead — and the catalogue's
                    # grid-found coordinates are lattice nodes up to ~2 km from the
                    # actual store, so many of them resolve to the SAME neighbouring
                    # store. Measured: 169 locations collapsed onto 61 stores, each
                    # re-staging its catalogue up to 8 times — 748 rows of which 474
                    # were duplicates, and 108 stores never scraped at all. The
                    # keyword orchestrator has always passed it; this path did not.
                    res = await provider.search(
                        session, query, brand_cap,
                        lat=loc.lat, lon=loc.lon,
                        merchant_id=loc.merchant_id,
                        follow_similarity=True,
                    )
                except Exception as e:
                    res = {"ok": False, "products": [], "error": f"{type(e).__name__}: {e}"}
                store_fetch += time.monotonic() - _t

                # Unconditional, and BEFORE the failure branch: a marketplace that
                # rate-limits per connection counts the blocked request too, so
                # skipping the gap on a failure is how a run digs itself deeper.
                if provider.search_gap_s:
                    await asyncio.sleep(provider.search_gap_s)

                # A BLOCK IS NOT A FAILURE — it means "come back shortly". Without
                # this the run treats a rate limit exactly like a 404: counts an
                # error, moves to the next store, and keeps hammering. That is how
                # a Zepto run produced 95 errors across 169 stores in one minute —
                # every request after the first block was doomed and sent anyway.
                # Mirrors the keyword orchestrator: wait, rebuild, retry once.
                if res.get("blocked") and provider.probe_every_s:
                    waits = 0
                    while waits < provider.max_block_waits:
                        waits += 1
                        logger.warning(
                            f"w{wid} {loc.city} brand '{query}' BLOCKED — waiting "
                            f"{provider.probe_every_s}s "
                            f"({waits}/{provider.max_block_waits})"
                        )
                        await asyncio.sleep(provider.probe_every_s)
                        await provider.close_session(session)
                        session = await provider.open_session(browser, loc.lat, loc.lon)
                        if session:
                            break
                    if not session:
                        logger.warning(f"worker {wid}: still blocked after {waits} "
                                       f"waits — exiting")
                        return
                    stats["blocked"] = stats.get("blocked", 0) + 1
                    stale = 0
                    try:
                        # Rebuilding the session reset its bound store, so the
                        # retry must re-bind explicitly — without it the retry
                        # would silently target whatever the fresh session
                        # resolved from the seed coordinate.
                        res = await provider.search(
                            session, query, brand_cap,
                            lat=loc.lat, lon=loc.lon,
                            merchant_id=loc.merchant_id,
                            follow_similarity=True,
                        )
                    except Exception as e:
                        res = {"ok": False, "products": [],
                               "error": f"{type(e).__name__}: {e}"}
                    if provider.search_gap_s:
                        await asyncio.sleep(provider.search_gap_s)

                if not res.get("ok"):
                    store_fail += 1
                    stale += 1
                    stats["errors"] += 1
                    # Recorded, not dropped — the backlog pass gets one more look.
                    misses.append((loc, brand_slug, aliases, brand_cap))
                    logger.warning(
                        f"w{wid} {loc.city} brand '{query}' failed: "
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
                # Own-brand only: empty competitor whitelist keeps just is_brand rows.
                cls = classify_products(res["products"], brand_slug, aliases, competitors=[])
                listings = cls["listings"]
                if not listings:
                    continue
                _t = time.monotonic()
                # Guard the silent failure directly: if the response came back
                # bound to a different store than we asked for, the rows describe
                # somebody else's shelf and must not be filed under this one.
                got = res.get("merchant_id", "")
                if got and loc.merchant_id and got != loc.merchant_id:
                    stats["errors"] += 1
                    logger.warning(
                        f"w{wid} {loc.city}: asked store {loc.merchant_id[:8]} but "
                        f"got {got[:8]} — dropping {len(listings)} rows rather than "
                        f"filing them under the wrong store"
                    )
                    continue

                n = await staging.save_skus(
                    stg, listings, brand_slug, tid, job_id,
                    merchant_id=loc.merchant_id or got,
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
            await asyncio.sleep(provider.store_gap_s)
    finally:
        if session:
            await provider.close_session(session)


async def _retry_worker(
    wid, provider, browser, seed, queue, stg, stats, tid, job_id,
) -> None:
    """Second-pass worker for the backlog `run_targeted` builds from the main
    pass's misses. Pulls one (location, brand) pair at a time — every pair here
    already failed during the main pass, so this is exactly one more attempt each,
    not another escalation. A pair that fails here is genuinely left out of the run
    and is reported by name at the end.

    Mirrors `orchestrator._retry_worker`; the two scrape paths should behave the
    same way under failure, and until now only the keyword one had a backlog pass.
    """
    session = await provider.open_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"backlog worker {wid}: could not open session — exiting")
        return
    try:
        while True:
            try:
                loc, brand_slug, aliases, brand_cap = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            query = _brand_query(brand_slug, aliases)
            try:
                # Bind by store id, same as the main pass — see the note there.
                res = await provider.search(
                    session, query, brand_cap,
                    lat=loc.lat, lon=loc.lon,
                    merchant_id=loc.merchant_id,
                    follow_similarity=True,
                )
            except Exception as e:
                res = {"ok": False, "products": [],
                       "error": f"{type(e).__name__}: {e}"}
            if provider.search_gap_s:
                await asyncio.sleep(provider.search_gap_s)

            if res.get("blocked") and provider.probe_every_s:
                # One wait, one look — this pair already had its fair shot.
                # Compounding waits here just delays the rest of the backlog.
                await asyncio.sleep(provider.probe_every_s)
                await provider.close_session(session)
                session = await provider.open_session(browser, loc.lat, loc.lon)
                stats["errors"] += 1
                if not session:
                    logger.warning(f"backlog worker {wid}: still blocked — exiting")
                    return
                stats.setdefault("unrecovered", []).append(
                    (loc.merchant_id, brand_slug))
                continue

            if not res.get("ok") or not res["products"]:
                stats["errors"] += 1
                stats.setdefault("unrecovered", []).append(
                    (loc.merchant_id, brand_slug))
                continue

            got = res.get("merchant_id", "")
            if got and loc.merchant_id and got != loc.merchant_id:
                stats["errors"] += 1
                logger.warning(
                    f"backlog w{wid}: asked store {loc.merchant_id[:8]} but got "
                    f"{got[:8]} — dropping rather than mis-filing"
                )
                continue

            cls = classify_products(res["products"], brand_slug, aliases,
                                    competitors=[])
            if not cls["listings"]:
                continue
            n = await staging.save_skus(
                stg, cls["listings"], brand_slug, tid, job_id,
                merchant_id=loc.merchant_id or got,
                city=loc.city, lat=loc.lat, lon=loc.lon,
            )
            stats["rows"] += n
            stats["recovered"] = stats.get("recovered", 0) + 1
    finally:
        if session:
            await provider.close_session(session)


async def run_targeted(
    db: AsyncSession, tenant_id, cap: int | None = None,
    city: str | None = None, resume: bool = False, workers: int = 5,
    mp_slug: str = DEFAULT_MARKETPLACE,
) -> dict:
    """Scrape a tenant's own catalog (brand query) across its `mp_slug` locations,
    writing `sku_snapshots`. `cap` overrides every brand's brand_cap for this run.
    `city` narrows to one city. `resume` continues the last incomplete run for THIS
    marketplace, skipping already-scraped stores. `workers` is the pool size."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    provider = get_provider(mp_slug)

    brands = await _own_brands(db, tid, provider.brand_cap)
    if cap:  # CLI override wins over each brand's configured cap
        brands = [(slug, aliases, cap) for slug, aliases, _ in brands]
    locations = await _locations(db, tid, mp_slug)
    if city:
        locations = [l for l in locations if l.city == city]
    summary = {
        "tenant_id": str(tid), "mp_slug": mp_slug,
        "brands": len(brands), "locations": len(locations),
        "rows": 0, "errors": 0, "skipped": 0, "job_id": None,
    }
    if not brands:
        logger.warning(f"targeted: tenant {tid} has no own brands — skipping")
        return summary
    if not locations:
        logger.warning(f"targeted: tenant {tid} has no {provider.name} locations — skipping")
        return summary

    # Staged locally, not written to Postgres here — see scraper/public/staging.py.
    if resume:
        prev = staging.resumable(staging.KIND_SKUS, tid, mp_slug)
        if not prev:
            logger.warning(
                f"targeted: no unloaded {mp_slug} staging run to resume for tenant {tid}"
            )
            return summary
        stg = staging.open_run(prev["path"])
        done = staging.done_stores(stg)
        logger.info(f"targeted: resuming {prev['path'].name} — {len(done)} stores already staged")
    else:
        stg = staging.new_run(tid, staging.KIND_SKUS, mp_slug)
        done = set()
    job_id = stg["job_id"]
    summary["job_id"] = job_id
    summary["staging_file"] = stg["path"].name
    stats = {"rows": 0, "errors": 0, "skipped": 0, "processed": 0}
    # (location, brand_slug, aliases, brand_cap) pairs the main pass gave up on.
    misses: list[tuple] = []
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    # Shared with the keyword orchestrator — a marketplace whose limiter is per
    # connection must not be handed a pool it cannot use.
    n_workers = _clamp_workers(workers, total, provider)

    # All DB reads are done — the scrape stages to SQLite and touches no database.
    # Release the pooled connection so it isn't held idle across the scrape and dropped
    # (surfacing as a spurious SQLAlchemy error at the end). See orchestrator.py.
    await db.close()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            try:
                logger.info(
                    f"targeted: tenant {tid} on {mp_slug} — {n_workers} workers × "
                    f"{total} stores, {len(brands)} brand(s)"
                )
                tasks = [
                    asyncio.create_task(_worker(
                        w, provider, browser, seed, queue, brands, done,
                        stg, stats, total, tid, job_id, misses,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)

                # Backlog pass: one more look at everything the main pass gave up
                # on, now that the main queue is drained (so this cannot starve
                # stores still waiting their first attempt). Same browser, so no
                # new launch overhead. Mirrors the keyword orchestrator.
                if misses:
                    logger.info(
                        f"targeted: main pass done — {len(misses)} misses, "
                        f"running one backlog pass to close them"
                    )
                    retry_queue: asyncio.Queue = asyncio.Queue()
                    for item in misses:
                        retry_queue.put_nowait(item)
                    retry_tasks = [
                        asyncio.create_task(_retry_worker(
                            w, provider, browser, seed, retry_queue,
                            stg, stats, tid, job_id,
                        ))
                        for w in range(1, min(n_workers, len(misses)) + 1)
                    ]
                    await asyncio.gather(*retry_tasks)
                    logger.info(
                        f"targeted: backlog pass done — "
                        f"{stats.get('recovered', 0)}/{len(misses)} recovered"
                    )
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

    unrecovered = stats.get("unrecovered", [])
    blocked = stats.get("blocked", 0)
    summary.update(rows=stats["rows"], errors=stats["errors"],
                   skipped=stats["skipped"], status="success",
                   blocked=blocked, recovered=stats.get("recovered", 0),
                   unrecovered=len(unrecovered))
    # A block that we waited out and recovered from is NOT an error — reporting it
    # as one made a healthy run look broken ("9 errors" when nothing was lost).
    # Three separate numbers, because they mean three different things:
    #   blocked      we hit a rate limit and waited; usually costs time, not data
    #   errors       a request genuinely failed
    #   unrecovered  data actually missing from this run  <- the one that matters
    logger.info(
        f"targeted: tenant {tid} done — {stats['rows']} sku rows, "
        f"{blocked} blocked (waited out), {stats['errors']} errors, "
        f"{len(unrecovered)} unrecovered, {stats['skipped']} skipped"
    )
    # An error COUNT is not actionable: "95 errors across 169 stores" does not say
    # which 95, and `--resume` cannot help (it skips stores that HAVE rows, so a
    # failed store stays skipped). Name them.
    if unrecovered:
        logger.warning(
            f"targeted: {len(unrecovered)} (store, brand) pair(s) still missing "
            f"after the backlog pass — these stores have NO rows in this run:"
        )
        for merchant_id, brand_slug in unrecovered[:20]:
            logger.warning(f"    {merchant_id}  {brand_slug}")
        if len(unrecovered) > 20:
            logger.warning(f"    ... and {len(unrecovered) - 20} more")
    logger.info(
        f"targeted: staged to {stg['path'].name} — NOT yet in the database. "
        f"Push it with:  python -m cli scrape load"
    )
    return summary


async def run_all_targeted(
    db: AsyncSession, cap: int | None = None, city: str | None = None, workers: int = 5,
    on_tenant_done=None, mp_slug: str = DEFAULT_MARKETPLACE,
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
        summary = await run_targeted(db, t.id, cap, city, workers=workers, mp_slug=mp_slug)
        out.append(summary)
        if on_tenant_done:
            await on_tenant_done(summary)
    return out
