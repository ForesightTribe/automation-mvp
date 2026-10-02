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
from scraper.public import caps, outcome, pacing, staging
from scraper.public.orchestrator import (
    _clamp_workers, _drain, _handles_blocks, _kinds, _note_block, _recover,
    warn_if_co_located,
)
from scraper.public.providers import DEFAULT_MARKETPLACE, get_provider
from scraper.utils.search_result import classify_products

# Start-up pacing for the worker pool — the SAME two rules as orchestrator.py,
# copied rather than shared on purpose (see that file for the measurements).
#
# This pool did not have them, and on 2026-09-16 19:30 it paid for it on the
# VM: all five workers opened a Blinkit session in the same second, Cloudflare
# refused every one, each exited on its single attempt, and the run ended after
# 38 s with 0 SKU rows across 2,059 locations. The keyword pool had survived the
# identical burst that morning because of exactly these lines.
#
# Worker N waits (N-1) x _WORKER_STAGGER_S before its first page load; a worker
# whose open fails waits and tries again, longer each time, before giving up.
_WORKER_STAGGER_S = 5
_OPEN_SESSION_RETRY_S = (10, 30)      # waits before attempt 2, attempt 3


async def _open_with_retry(provider, browser, wid: int, seed) -> dict | None:
    """Stagger by worker id, then open a session with retries. None = gave up."""
    if _WORKER_STAGGER_S and wid > 1:
        await asyncio.sleep(_WORKER_STAGGER_S * (wid - 1))
    session = None
    for attempt, wait in enumerate((*_OPEN_SESSION_RETRY_S, None), start=1):
        session = await provider.open_session(browser, seed[0], seed[1])
        if session or wait is None:
            break
        logger.warning(f"worker {wid}: could not open session (attempt {attempt}) — "
                       f"retrying in {wait}s")
        await asyncio.sleep(wait)
    return session

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


async def _own_brands(db: AsyncSession, tenant_id: uuid.UUID, default_cap: int,
                      mp_slug: str) -> list[tuple[str, list[str], int]]:
    """(brand_slug, aliases, brand_cap) for each own brand the tenant tracks — the cap being
    the brand's for THIS marketplace (scraper/public/caps.py), else `default_cap`."""
    rows = (await db.execute(
        select(TenantWatchlist).where(
            TenantWatchlist.tenant_id == tenant_id,
            TenantWatchlist.relationship == "own",
        )
    )).scalars().all()
    configured = await caps.own_caps(db, tenant_id, mp_slug)
    return [(e.brand_slug, e.aliases or [],
             (configured.get(e.brand_slug) or caps.Caps()).brand_cap or default_cap)
            for e in rows]


async def _locations(db: AsyncSession, tenant_id: uuid.UUID,
                     mp_slug: str) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == mp_slug)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()


async def _search(provider, session, loc, query: str, brand_cap: int) -> dict:
    """One brand search at one store. Never raises — a failure comes back as `ok=False`.

    Brand scrape follows the similarity tail — Blinkit returns only ~18 own products
    as `basic`, the rest as similarity; own-only classification discards non-own
    padding. A provider without that distinction may ignore the flag.

    `merchant_id` is REQUIRED, not optional. On a marketplace that binds by store id
    (Zepto), omitting it makes the engine resolve the store from the coordinate
    instead — and the catalogue's grid-found coordinates are lattice nodes up to ~2 km
    from the actual store, so many of them resolve to the SAME neighbouring store.
    Measured: 169 locations collapsed onto 61 stores, each re-staging its catalogue up
    to 8 times — 748 rows of which 474 were duplicates, and 108 stores never scraped at
    all. The keyword orchestrator has always passed it; this path did not.

    `distinct_ad_slots=False`: this scrape asks what a product's state is AT A STORE,
    not where it sat on a page. A brand-name query is exactly where a brand-defence ad
    appears, and keeping the sponsored and organic sightings as two rows would file the
    same product's inventory twice under one store.
    """
    try:
        return await provider.search(
            session, query, brand_cap,
            lat=loc.lat, lon=loc.lon,
            merchant_id=loc.merchant_id,
            follow_similarity=True,
            distinct_ad_slots=False,
        )
    except Exception as e:
        return {"ok": False, "products": [], "error": f"{type(e).__name__}: {e}"}


async def _stage(stg, loc, brand_slug, aliases, res, tid, job_id, stats, who: str) -> int:
    """Stage one ANSWERED (brand, store) pair. Returns sku rows written.

    Always writes the pair's `pairs_done` marker, rows or not: "this store does not
    list the brand" is an answer, and without the marker it looked the same as a store
    that was never scraped (see staging.py).

    One answer is refused rather than filed: a response bound to a DIFFERENT store
    than the one asked for. Its rows describe somebody else's shelf. The pair still
    counts as answered — asking again returns the same store, so a retry cannot fix
    what is a catalogue problem — but nothing is written, marker included.
    """
    # Own-brand only: empty competitor whitelist keeps just is_brand rows.
    cls = classify_products(res.get("products") or [], brand_slug, aliases, competitors=[])
    listings = cls["listings"]
    got = res.get("merchant_id", "")
    if listings and got and loc.merchant_id and got != loc.merchant_id:
        stats["mismatched"] += 1
        logger.warning(
            f"{who} {loc.city}: asked store {loc.merchant_id[:8]} but got {got[:8]} — "
            f"dropping {len(listings)} rows rather than filing them under the wrong store"
        )
        return 0
    return await staging.save_skus(
        stg, listings, brand_slug, tid, job_id,
        merchant_id=loc.merchant_id or got,
        city=loc.city, lat=loc.lat, lon=loc.lon,
    )


async def _worker(
    wid, provider, browser, seed, queue, brands, finished, popped, stg, stats, total,
    tid, job_id,
) -> None:
    """One concurrent worker: own browser context + session, pulling stores off the
    shared queue until empty. Per store, runs each own brand's query and stages its
    own-brand listings. Holds no DB session — see scraper/public/staging.py.

    Bookkeeping is the same two shared collections as the keyword orchestrator (see
    `orchestrator._worker`): `popped` = stores taken off the queue, `finished` =
    (brand, lat, lon) pairs that got a real answer. What is missing is derived from
    those two, so a pair cannot fall through unrecorded — whether it failed, was
    skipped after `_STORE_SKIP_AFTER`, or the worker died mid-store.
    """
    session = await _open_with_retry(provider, browser, wid, seed)
    if not session:
        logger.warning(f"worker {wid}: could not open session — exiting")
        return
    stale = 0
    pacer = pacing.new(provider)
    streak = 0          # blocks in a row; reset by the first answer that is not one
    blocked_since = 0.0
    try:
        while True:
            try:
                loc = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            popped.append(loc)
            todo = [b for b in brands if (b[0], loc.lat, loc.lon) not in finished]
            if not todo:
                stats["skipped"] += 1
                stats["processed"] += 1
                continue

            store_fail = 0
            store_rows = 0
            store_fetch = store_db = 0.0
            for brand_slug, aliases, brand_cap in todo:
                if store_fail >= _STORE_SKIP_AFTER:
                    # The rest stay out of `finished`; the backlog pass takes them.
                    break
                query = _brand_query(brand_slug, aliases)

                # Up to 2 attempts: the plain search, plus — only if it came back
                # BLOCKED — one retry once the block has been waited out. A BLOCK IS
                # NOT A FAILURE, it means "come back shortly". Without this the run
                # treated a rate limit exactly like a 404: counted an error, moved to
                # the next store, and kept hammering. That is how a Zepto run produced
                # 95 errors across 169 stores in one minute. Mirrors the keyword
                # orchestrator.
                blocked_twice = False
                for attempt in range(2):
                    # Unconditional, and before the request: a marketplace that
                    # rate-limits per connection counts the blocked request too.
                    await pacing.before(pacer, session)
                    _t = time.monotonic()
                    # `_search` passes merchant_id, so a retry on a REBUILT session is
                    # still bound to this store, not whatever the new session resolved.
                    res = await _search(provider, session, loc, query, brand_cap)
                    store_fetch += time.monotonic() - _t
                    await pacing.after(pacer)

                    if res.get("blocked") and _handles_blocks(provider):
                        streak += 1
                        if streak == 1:
                            blocked_since = time.monotonic()
                        await _note_block(stg, stats, "main", wid, loc, query, res, streak)
                        pacing.on_block(pacer)
                        session = await _recover(provider, browser, session, loc,
                                                 res.get("kind") or "", streak,
                                                 blocked_since, f"worker {wid}",
                                                 stg=stg, wid=wid)
                        if not session:
                            return
                        stale = 0
                        if attempt == 0:
                            continue
                        blocked_twice = True
                        break
                    streak = 0
                    pacing.on_clean(pacer)
                    break

                if blocked_twice:
                    # One store failure, not two — and the pair stays out of
                    # `finished`, so the backlog pass gets it.
                    store_fail += 1
                    continue

                if not res.get("ok"):
                    store_fail += 1
                    stale += 1
                    stats["errors"] += 1
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
                _t = time.monotonic()
                n = await _stage(stg, loc, brand_slug, aliases, res, tid, job_id,
                                 stats, f"w{wid}")
                store_db += time.monotonic() - _t
                finished.add((brand_slug, loc.lat, loc.lon))
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
    wid, provider, browser, seed, queue, finished, stg, stats, tid, job_id,
) -> None:
    """Second-pass worker for the backlog `run_targeted` builds from the main
    pass's misses. Pulls one store at a time with ONLY the brands it is still
    missing — this is exactly one more attempt each, not another escalation. A pair
    that fails here is genuinely left out of the run and is reported by name at the
    end.

    Mirrors `orchestrator._retry_worker`; the two scrape paths behave the same way
    under failure.
    """
    session = await _open_with_retry(provider, browser, wid, seed)
    if not session:
        logger.warning(f"backlog worker {wid}: could not open session — exiting")
        return
    pacer = pacing.new(provider)
    streak = 0
    blocked_since = 0.0
    try:
        while True:
            try:
                loc, todo = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            store_fail = 0
            for brand_slug, aliases, brand_cap in todo:
                if store_fail >= _STORE_SKIP_AFTER:
                    break
                query = _brand_query(brand_slug, aliases)
                # Bind by store id and collapse ad slots, same as the main pass —
                # see `_search`.
                await pacing.before(pacer, session)
                res = await _search(provider, session, loc, query, brand_cap)
                await pacing.after(pacer)

                if res.get("blocked") and _handles_blocks(provider):
                    # Wait it out so the NEXT pair gets a working session, but do not
                    # retry this one — it already had its fair shot in the main pass.
                    streak += 1
                    if streak == 1:
                        blocked_since = time.monotonic()
                    await _note_block(stg, stats, "backlog", wid, loc, query, res, streak)
                    pacing.on_block(pacer)
                    store_fail += 1
                    session = await _recover(provider, browser, session, loc,
                                             res.get("kind") or "", streak, blocked_since,
                                             f"backlog worker {wid}", stg=stg,
                                             phase="backlog", wid=wid)
                    if not session:
                        return
                    continue
                streak = 0
                pacing.on_clean(pacer)

                if not res.get("ok"):
                    stats["errors"] += 1
                    store_fail += 1
                    continue

                n = await _stage(stg, loc, brand_slug, aliases, res, tid, job_id,
                                 stats, f"backlog w{wid}")
                finished.add((brand_slug, loc.lat, loc.lon))
                stats["rows"] += n
                stats["recovered"] += 1
    finally:
        if session:
            await provider.close_session(session)


def _missing(popped, brands, finished) -> list[tuple]:
    """[(location, [brand tuples still unanswered])] over the stores this run attempted."""
    out = []
    for loc in popped:
        todo = [b for b in brands if (b[0], loc.lat, loc.lon) not in finished]
        if todo:
            out.append((loc, todo))
    return out


async def run_targeted(
    db: AsyncSession, tenant_id, cap: int | None = None,
    city: str | None = None, resume: bool = False, workers: int = 5,
    mp_slug: str = DEFAULT_MARKETPLACE,
) -> dict:
    """Scrape a tenant's own catalog (brand query) across its `mp_slug` locations,
    writing `sku_snapshots`. `cap` overrides every brand's brand_cap for this run.
    `city` narrows to one city. `resume` continues the last incomplete run for THIS
    marketplace, skipping already-answered (brand, store) pairs. `workers` is the
    pool size.

    The summary's `status` is decided from COVERAGE (see scraper/public/outcome.py):
    `success`, `partial` (kept on disk for --resume, never auto-loaded) or `failed`."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    provider = get_provider(mp_slug)

    brands = await _own_brands(db, tid, provider.brand_cap, mp_slug)
    if cap:  # CLI override wins over each brand's configured cap
        brands = [(slug, aliases, cap) for slug, aliases, _ in brands]
    locations = await _locations(db, tid, mp_slug)
    if city:
        locations = [l for l in locations if l.city == city]
    summary = {
        "tenant_id": str(tid), "mp_slug": mp_slug,
        "brands": len(brands), "locations": len(locations),
        "rows": 0, "errors": 0, "skipped": 0, "job_id": None,
        # Nothing to scrape is not a failure — see orchestrator.run_tenant.
        "status": outcome.SKIPPED,
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
        # Pairs, not stores. Resuming on "stores that have rows" skipped a store whose
        # FIRST brand had staged while its second had failed, and re-scraped every
        # store that simply does not list the brand.
        done = staging.done_sku_pairs(stg)
        logger.info(f"targeted: resuming {prev['path'].name} — "
                    f"{len(done)} (brand,store) pairs already answered")
    else:
        stg = staging.new_run(tid, staging.KIND_SKUS, mp_slug)
        done = set()
    job_id = stg["job_id"]
    summary["job_id"] = job_id
    summary["staging_file"] = stg["path"].name
    stats = {"rows": 0, "errors": 0, "skipped": 0, "processed": 0,
             "blocked": 0, "recovered": 0, "mismatched": 0, "blocks_by_kind": {}}
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    # Shared with the keyword orchestrator — a marketplace whose limiter is per
    # connection must not be handed a pool it cannot use.
    n_workers = _clamp_workers(workers, total, provider)

    # What this run sets out to do, as (brand, store) pairs, and what the file holds.
    scope = {(slug, l.lat, l.lon) for l in locations for slug, _, _ in brands}
    finished: set[tuple] = set(done)
    done_before = len(scope & finished)
    popped: list = []          # stores taken off the queue, by any worker
    unattempted: list = []     # stores nobody lived to take
    unrecovered: list = []     # (location, [brands]) still missing after the backlog

    # All DB reads are done — the scrape stages to SQLite and touches no database.
    # Release the pooled connection so it isn't held idle across the scrape and dropped
    # (surfacing as a spurious SQLAlchemy error at the end). See orchestrator.py.
    await db.close()

    try:
        async with async_playwright() as pw:
            browser = await provider.launch_browser(pw)
            try:
                logger.info(
                    f"targeted: tenant {tid} on {mp_slug} — {n_workers} workers × "
                    f"{total} stores, {len(brands)} brand(s)"
                )
                warn_if_co_located(locations, "targeted")
                tasks = [
                    asyncio.create_task(_worker(
                        w, provider, browser, seed, queue, brands, finished, popped,
                        stg, stats, total, tid, job_id,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)

                # The pool has returned — EITHER the queue is empty OR every worker
                # gave up. Only the queue can say which.
                unattempted = _drain(queue)
                misses = _missing(popped, brands, finished)
                n_missed = sum(len(todo) for _, todo in misses)

                # Backlog pass: one more look at everything the main pass left
                # unanswered, now that the main queue is drained (so this cannot
                # starve stores still waiting their first attempt). Same browser, so
                # no new launch overhead. Skipped when stores were left unattempted —
                # every worker lost its session, and a backlog pool would open into
                # the same wall; --resume picks all of it up. Mirrors the keyword
                # orchestrator.
                if misses and unattempted:
                    logger.warning(
                        f"targeted: the workers stopped with {len(unattempted)} stores "
                        f"untouched — skipping the backlog pass ({n_missed} pairs); "
                        f"--resume continues from here"
                    )
                elif misses:
                    logger.info(
                        f"targeted: main pass done — {n_missed} pairs missing across "
                        f"{len(misses)} stores, running one backlog pass"
                    )
                    retry_queue: asyncio.Queue = asyncio.Queue()
                    for item in misses:
                        retry_queue.put_nowait(item)
                    retry_tasks = [
                        asyncio.create_task(_retry_worker(
                            w, provider, browser, seed, retry_queue, finished,
                            stg, stats, tid, job_id,
                        ))
                        for w in range(1, min(n_workers, len(misses)) + 1)
                    ]
                    await asyncio.gather(*retry_tasks)
                    logger.info(
                        f"targeted: backlog pass done — "
                        f"{stats['recovered']}/{n_missed} recovered"
                    )
                unrecovered = _missing(popped, brands, finished)
            finally:
                await browser.close()
    except Exception as e:
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, outcome.FAILED, str(e))
        staging.close(stg)
        logger.error(f"targeted: tenant {tid} run failed: {e}")
        raise

    # ── How did it end? Decided from coverage, not from having got this far. ──
    pairs_done = len(scope & finished)
    n_unrecovered = sum(len(todo) for _, todo in unrecovered)
    status = outcome.decide(
        expected=len(scope), done=pairs_done,
        done_this_run=pairs_done - done_before,
        unattempted_stores=len(unattempted),
    )
    note = outcome.describe(
        expected=len(scope), done=pairs_done, unattempted_stores=len(unattempted),
        stores_total=total, unrecovered=n_unrecovered, unit="brand-store",
    )
    stats.update(pairs_total=len(scope), pairs_done=pairs_done,
                 unattempted=len(unattempted), unrecovered=n_unrecovered)
    try:
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, status,
                           None if status == outcome.SUCCESS else f"{status}: {note}")
    finally:
        staging.close(stg)

    summary.update(
        rows=stats["rows"], errors=stats["errors"], skipped=stats["skipped"],
        status=status, note=note, blocked=stats["blocked"],
        blocks_by_kind=stats["blocks_by_kind"],
        recovered=stats["recovered"], mismatched=stats["mismatched"],
        unattempted=len(unattempted), unrecovered=n_unrecovered,
        pairs_total=len(scope), pairs_done=pairs_done,
        coverage_pct=outcome.coverage_pct(pairs_done, len(scope)),
    )
    # A block that we waited out and recovered from is NOT an error — reporting it
    # as one made a healthy run look broken ("9 errors" when nothing was lost).
    # Separate numbers, because they mean different things:
    #   blocked      we hit a rate limit and waited; usually costs time, not data
    #   errors       a request genuinely failed (it may have been recovered later)
    #   unrecovered  pairs unanswered at stores that were reached <- data missing
    #   unattempted  stores no worker lived to take               <- data missing
    #   mismatched   the marketplace answered for a different store (catalogue drift)
    logger.info(
        f"targeted: tenant {tid} {status.upper()} — {note} · {stats['rows']} sku rows, "
        f"{stats['blocked']} blocked (waited out{_kinds(stats)}), {stats['errors']} errors, "
        f"{stats['mismatched']} wrong-store answers dropped, {stats['skipped']} skipped"
    )
    # An error COUNT is not actionable: "95 errors across 169 stores" does not say
    # which 95. Name them.
    if unrecovered:
        logger.warning(
            f"targeted: {n_unrecovered} (store, brand) pair(s) have NO answer in "
            f"this run:"
        )
        for loc, todo in unrecovered[:20]:
            logger.warning(f"    {loc.merchant_id}  {loc.city}  "
                           f"{', '.join(b[0] for b in todo)}")
        if len(unrecovered) > 20:
            logger.warning(f"    ... and {len(unrecovered) - 20} more stores")
    if status == outcome.SUCCESS:
        logger.info(
            f"targeted: staged to {stg['path'].name} — NOT yet in the database. "
            f"Push it with:  python -m cli scrape load"
        )
    else:
        logger.warning(
            f"targeted: {stg['path'].name} is {status} and will NOT be auto-loaded. "
            f"Continue it with --resume, or load what it has with "
            f"`python -m cli scrape load --file {staging.ref(stg['path'])}`"
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
