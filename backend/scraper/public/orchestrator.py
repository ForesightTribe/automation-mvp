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
from scraper.public import outcome, pacing, staging
from scraper.public.providers import DEFAULT_MARKETPLACE, get_provider

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a store → skip its remaining keywords
_REFRESH_AFTER = 8      # consecutive failed fetches across stores → session likely stale, re-open
_JITTER_FRAC = 0.15     # ± spread on the block-recovery wait, so workers stop retrying in lockstep
# Seconds between worker start-ups. Opening a session means loading the
# marketplace's homepage and capturing the first search request's headers; five
# workers doing that in the same second on the VM left three of them past the
# capture window ("no session headers captured", all at 11:00:59 on 2026-09-14)
# and a worker that fails to open its session exits and is not replaced, so the
# whole 10-hour run went on two workers. Worker N waits (N-1) x this before its
# first page load. 0 restores the old all-at-once start.
_WORKER_STAGGER_S = 5
# The stagger took the VM from 2 to 4 live workers. What loses the rest is
# not a slow page but Cloudflare rate-limiting the VM's IP ("HTTP 429 ·
# non-JSON body" surfaced mid-run on 2026-09-15) — a challenge page instead
# of the site, so no search request fires and no headers are captured. Its
# window is short, so a worker that fails to open waits and tries again,
# with a longer wait each time, before giving up. On the VM the second
# attempt rescued two of three failed workers; the third wait is for the
# one it did not. A single entry restores the old give-up-at-once.
_OPEN_SESSION_RETRY_S = (10, 30)      # waits before attempt 2, attempt 3


def _clamp_workers(requested: int, total: int, provider) -> int:
    """Pool size, never above what the marketplace can actually use.

    A marketplace whose limiter is per CONNECTION gains nothing from parallelism
    inside one IP — Zepto measured 1 worker at 791 products/min against 4 workers
    at 807, a 1.02x return that wasted 76% of its requests. Without this clamp
    `--workers 5` would quietly do that and look like it was working.

    Warns rather than failing: the run is still correct, just narrower than asked
    for, and a silent downgrade is how surprises get built into a schedule.

    `max_workers = None` means no ceiling, which is how Blinkit keeps its existing
    behaviour — including honouring a `--workers` above its usual 5.
    """
    n = max(1, min(requested, total))
    cap = getattr(provider, "max_workers", None)
    if not cap or n <= cap:
        return n

    if cap == 1:
        # The marketplace is single-worker by design, so --workers is not a knob
        # here at all. Informational: the default is 5 and nobody chose it, so a
        # warning on every run would be noise about a decision the user did not
        # make.
        logger.info(
            f"{provider.slug}: --workers does not apply (rate limit is per "
            f"connection, not per worker) — running single-worker"
        )
    else:
        logger.warning(
            f"{provider.slug}: --workers {requested} reduced to {cap} — beyond "
            f"that, workers share one budget and waste requests rather than "
            f"adding throughput"
        )
    return cap


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


def _handles_blocks(provider) -> bool:
    """Does this marketplace report blocks for us to wait out? (Blinkit does not yet.)"""
    return bool(provider.block_remedy or provider.probe_every_s)


async def _note_block(stg, stats, phase: str, wid: int, loc, query: str, res: dict,
                      streak: int) -> None:
    """Count, log and record one block — WHICH mechanism, in the marketplace's own words.

    The log used to say only "BLOCKED", so a run that spent hours blocked could not say
    whether it was the rate limit, the login gate or the firewall — three things with
    three different remedies. Now each block names its kind in the log, and lands in the
    staging file's `blocks` table for after-the-fact diagnosis."""
    kind = res.get("kind") or "blocked"
    stats["blocked"] += 1
    stats["blocks_by_kind"][kind] = stats["blocks_by_kind"].get(kind, 0) + 1
    logger.warning(f"w{wid} {loc.city} '{query}' BLOCKED · {kind} · "
                   f"{(res.get('error') or '').strip()[:160]}")
    await staging.record_block(stg, phase=phase, worker=wid, merchant_id=loc.merchant_id,
                               city=loc.city, query=query, kind=kind,
                               detail=res.get("error"), streak=streak)


async def _recover(provider, browser, session, loc, kind: str, streak: int,
                   blocked_since: float, who: str, stg=None, phase: str = "main",
                   wid: int = 0) -> dict | None:
    """Meet a block. Returns the session to carry on with — the same one, or a new one —
    or None when the worker should stop (the run then ends `partial`).

    With a marketplace `block_remedy` (Zepto) the KIND decides: wait on the same session,
    or rebuild. A worker stops only after `block_give_up_s` with nothing but blocks,
    measured from `blocked_since` (the first block of the current streak). Without one
    (Instamart) the generic remedy: wait `probe_every_s`, rebuild, up to
    `max_block_waits` times.
    """
    if provider.block_remedy is None:
        waits = 0
        while waits < provider.max_block_waits:
            waits += 1
            logger.warning(f"{who} {loc.city}: waiting {provider.probe_every_s}s, then a "
                           f"new session ({waits}/{provider.max_block_waits})")
            await asyncio.sleep(_jittered(provider.probe_every_s))
            await provider.close_session(session)
            session = await provider.open_session(browser, loc.lat, loc.lon)
            if session:
                return session
        logger.warning(f"{who}: still blocked after {waits} waits — stopping")
        return None

    n = streak
    while True:
        blocked_for = time.monotonic() - blocked_since
        if blocked_for >= provider.block_give_up_s:
            logger.warning(
                f"{who}: nothing but blocks for {blocked_for / 60:.0f} min — stopping. "
                f"That is not a rate limit (those clear in about a minute); the run ends "
                f"partial and --resume continues it")
            if session:
                await provider.close_session(session)
            return None
        wait, rebuild = provider.block_remedy(kind, n)
        logger.info(f"{who} {loc.city}: {kind} block, {n} in a row — waiting {wait:.0f}s "
                    f"on {'a NEW session' if rebuild else 'the same session'}")
        if wait:
            await asyncio.sleep(_jittered(wait))
        if not rebuild:
            return session
        await provider.close_session(session)
        session = await provider.open_session(browser, loc.lat, loc.lon)
        if session:
            return session
        if stg is not None:
            await staging.record_block(stg, phase=phase, worker=wid,
                                       merchant_id=loc.merchant_id, city=loc.city,
                                       query="", kind="open_failed",
                                       detail="could not open a new session", streak=n)
        n += 1
        kind = "open_failed"


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


def warn_if_co_located(locations, label: str) -> int:
    """Warn when several catalog rows share one coordinate. Returns the wasted count.

    The search API picks the dark store FROM THE COORDINATE, so two catalog rows at the
    same lat/lon send an identical request and get an identical response — the second is
    pure waste, and the response cannot even tell you it happened, because it names the
    store that served rather than the row we asked for.

    This was real: the catalog once held 2,216 rows across 1,924 distinct coordinates,
    so ~13% of every national run was duplicate work — roughly ten hours a cycle, for
    months, entirely silently. It is 0 today (2,059 rows, 2,059 coordinates), fixed as a
    side effect of a `cli sync --prune` rather than by intent, which is exactly why it is
    worth a line: nothing would announce its return either.

    Deliberately a WARNING and not a filter. Duplicate coordinates are a CATALOG problem
    — two rows describing one probe point — and silently deduping here would hide it
    while leaving `config.xlsx` wrong and every other consumer still double-counting.
    `--resume` already skips these (it keys on `(keyword, lat, lon)`); a fresh run does
    not.
    """
    coords = {(l.lat, l.lon) for l in locations}
    wasted = len(locations) - len(coords)
    if wasted:
        logger.warning(
            f"{label}: {len(locations)} stores share only {len(coords)} distinct "
            f"coordinates — {wasted} ({wasted / len(locations) * 100:.0f}%) will be "
            f"scraped twice for an identical response. Fix the catalog (`cli sync`), "
            f"not the scrape."
        )
    return wasted


async def _locations(db: AsyncSession, tenant_id: uuid.UUID,
                     mp_slug: str) -> list[MarketplaceLocation]:
    return (await db.execute(
        select(MarketplaceLocation)
        .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
        .where(TenantLocation.tenant_id == tenant_id, MarketplaceLocation.mp_slug == mp_slug)
        .order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()


async def _open_with_retry(provider, browser, wid: int, seed, who: str = "worker") -> dict | None:
    """Stagger by worker id, then open a session with retries. None = gave up.

    See `_WORKER_STAGGER_S` / `_OPEN_SESSION_RETRY_S` above for the measurements."""
    if _WORKER_STAGGER_S and wid > 1:
        await asyncio.sleep(_WORKER_STAGGER_S * (wid - 1))
    session = None
    for attempt, wait in enumerate((*_OPEN_SESSION_RETRY_S, None), start=1):
        session = await provider.open_session(browser, seed[0], seed[1])
        if session or wait is None:
            break
        logger.warning(f"{who} {wid}: could not open session (attempt {attempt}) — "
                       f"retrying in {wait}s")
        await asyncio.sleep(wait)
    return session


async def _stage(provider, stg, loc, keyword, brands, competitor_list, res,
                 tid, job_id, wid) -> tuple[int, int]:
    """Stage one ANSWERED search — one snapshot per own brand tracking the keyword.
    Returns (snapshots, rows).

    An answer with no products is still staged, as a snapshot with `total_results = 0`
    and no listings. Skipping it made "this keyword returns nothing at this store"
    indistinguishable from "this store was never scraped": a full national run came out
    603 pairs short of stores x keywords with no way to say which were which. Rank and
    SoV are left NULL on such a row — an empty page has no share to take — so the read
    side's averages ignore it.
    """
    products = res.get("products") or []
    got = res.get("merchant_id") or ""
    # The catalog says this coordinate is served by loc.merchant_id; the response says
    # otherwise. Free store-moved/closed/opened alarm — the mapping has held on every
    # location probed so far, so a mismatch is worth a look, not a silent overwrite.
    # The OBSERVED store is what gets stored; the catalog is the claim.
    if products and got and got != loc.merchant_id:
        logger.warning(
            f"w{wid} {loc.city}/{loc.location_name}: express store is {got}, catalog "
            f"says {loc.merchant_id} — store moved/closed, or the coordinate drifted?"
        )
    snaps = rows = 0
    for brand_slug, aliases in brands:
        raw = {
            "platform": provider.slug, "keyword": keyword, "brand_slug": brand_slug,
            "city": loc.city, "zone": loc.location_name, "pincode": loc.pincode,
            "lat": loc.lat, "lon": loc.lon, "aliases": aliases,
            "competitors": competitor_list or None,
            "merchant_id": got, "total_results": res.get("total_results"),
            "products": products,
        }
        result = provider.parse(raw)
        if not products:
            result["total_results"] = 0
            result["brand_rank"] = None
            result["brand_sov_pct"] = None
        rows += await staging.save_search(stg, result, tid, job_id)
        snaps += 1
    return snaps, rows


async def _worker(
    wid, provider, browser, seed, queue, kw_map, competitor_list, finished, popped,
    stg, stats, total, tid, job_id, cap,
) -> None:
    """One concurrent worker: its own browser context + session, pulling stores off
    the shared queue until it's empty.

    Holds NO database session — results are staged to the run's local SQLite file and
    pushed to Postgres later by `cli scrape load`. That decoupling is why a Supabase
    blip can no longer kill a multi-hour run. See scraper/public/staging.py.

    THE BOOKKEEPING IS TWO SHARED COLLECTIONS, and nothing else:

      `popped`    every store this pool took off the queue (appended on pop)
      `finished`  every (keyword, lat, lon) that got a real answer and was staged

    Both are safe to touch from any worker without a lock — asyncio is single-threaded
    and no `await` sits between a check and its write. What a run is MISSING is then
    derived, not tracked: a pair of a popped store that is not in `finished` is a miss,
    whatever the reason — blocked twice, a plain failure, a store skipped after
    `_STORE_SKIP_AFTER`, or this worker dying mid-store. The previous version recorded
    a miss only on the blocked-twice path, so the other three vanished without a count.
    `run_tenant` gives every miss one more look in the backlog pass.
    """
    session = await _open_with_retry(provider, browser, wid, seed)
    if not session:
        logger.warning(f"worker {wid}: could not open session — exiting")
        return
    stale = 0
    searches = 0        # since this worker's last rest, for provider.pause_every
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
            store_fail = 0
            store_snaps = store_rows = 0
            store_fetch = store_db = 0.0
            for keyword, brands in kw_map.items():
                if store_fail >= _STORE_SKIP_AFTER:
                    # The store's remaining keywords stay out of `finished`, so the
                    # backlog pass picks them up — skipping here only stops this worker
                    # spending the whole keyword list on a store that is failing now.
                    break
                key = (keyword, loc.lat, loc.lon)
                if key in finished:
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
                    # Pace HERE, before the request, and unconditionally (see
                    # scraper/public/pacing.py). Every branch below can
                    # `continue`/`break` out early, and an empty result is the
                    # commonest of them — on Zepto 'sourdough bread loaf' returns
                    # 0-6 products at most stores. Pacing only after those branches
                    # meant the thinnest keywords fired back to back with no gap at
                    # all, which is what blocked five workers in 37 seconds.
                    await pacing.before(pacer, session)
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
                    await pacing.after(pacer)

                    if res.get("blocked") and _handles_blocks(provider):
                        # Counted apart from `errors`: a block we wait out costs
                        # time, not data, and lumping the two made a healthy run
                        # look broken. Counted and recorded HERE, before the wait, so
                        # a worker that never recovers still shows the block it died on.
                        streak += 1
                        if streak == 1:
                            blocked_since = time.monotonic()
                        await _note_block(stg, stats, "main", wid, loc, keyword, res, streak)
                        pacing.on_block(pacer)
                        session = await _recover(provider, browser, session, loc,
                                                 res.get("kind") or "", streak,
                                                 blocked_since, f"worker {wid}",
                                                 stg=stg, wid=wid)
                        if not session:
                            return
                        searches = 0
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
                        break

                    streak = 0
                    pacing.on_clean(pacer)
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
                _t = time.monotonic()
                n_snaps, n_rows = await _stage(provider, stg, loc, keyword, brands,
                                               competitor_list, res, tid, job_id, wid)
                store_db += time.monotonic() - _t
                finished.add(key)
                stats["rows"] += n_rows
                store_rows += n_rows
                stats["snapshots"] += n_snaps
                store_snaps += n_snaps

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
    wid, provider, browser, seed, queue, kw_map, competitor_list, finished,
    stg, stats, tid, job_id, cap,
) -> None:
    """Second-pass worker for the backlog `run_tenant` builds from the main pass's
    misses. Pulls one store at a time with ONLY the keywords it is still missing, and
    gives each exactly one more attempt — not another multi-wait escalation. A pair
    that fails here too is genuinely left out of this run, and is named at the end.

    The same `_STORE_SKIP_AFTER` rule applies: a store that fails twice in a row here
    is not answering, and spending its whole keyword list on it only delays the rest.
    """
    session = await _open_with_retry(provider, browser, wid, seed, who="backlog worker")
    if not session:
        logger.warning(f"backlog worker {wid}: could not open session — exiting")
        return
    pacer = pacing.new(provider)
    streak = 0
    blocked_since = 0.0
    try:
        while True:
            try:
                loc, keywords = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            store_fail = 0
            for keyword in keywords:
                if store_fail >= _STORE_SKIP_AFTER:
                    break
                brands = kw_map.get(keyword)
                if not brands:
                    continue

                await pacing.before(pacer, session)
                try:
                    res = await provider.search(session, keyword, cap,
                                                lat=loc.lat, lon=loc.lon,
                                                merchant_id=loc.merchant_id)
                except Exception as e:
                    res = {"ok": False, "products": [], "merchant_id": "",
                           "total_results": 0, "error": f"{type(e).__name__}: {e}"}
                await pacing.after(pacer)

                if res.get("blocked") and _handles_blocks(provider):
                    # Wait it out so the NEXT pair gets a working session, but do not
                    # retry this one — it already had its fair shot in the main pass.
                    streak += 1
                    if streak == 1:
                        blocked_since = time.monotonic()
                    await _note_block(stg, stats, "backlog", wid, loc, keyword, res, streak)
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

                n_snaps, n_rows = await _stage(provider, stg, loc, keyword, brands,
                                               competitor_list, res, tid, job_id, wid)
                finished.add((keyword, loc.lat, loc.lon))
                stats["rows"] += n_rows
                stats["snapshots"] += n_snaps
                stats["recovered"] += 1
    finally:
        if session:
            await provider.close_session(session)


def _kinds(stats: dict) -> str:
    """': gate 30, rate 8' — the block breakdown for a summary line, or ''."""
    by = stats.get("blocks_by_kind") or {}
    return (": " + ", ".join(f"{k} {n}" for k, n in sorted(by.items(), key=lambda kv: -kv[1]))
            if by else "")


def _missing(popped, kw_map, finished) -> list[tuple]:
    """[(location, [keywords still unanswered])] over the stores this run attempted."""
    out = []
    for loc in popped:
        kws = [kw for kw in kw_map if (kw, loc.lat, loc.lon) not in finished]
        if kws:
            out.append((loc, kws))
    return out


def _drain(queue: asyncio.Queue) -> list:
    """Whatever is still on the queue — the stores no worker lived to take."""
    left = []
    while True:
        try:
            left.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return left


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
    one browser, each pulling stores off a shared queue.

    The summary's `status` is decided from COVERAGE (see scraper/public/outcome.py):
    `success`, `partial` (stores left unattempted, or under the coverage floor — kept
    on disk for --resume, never auto-loaded) or `failed` (nothing scraped)."""
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
        # Nothing to scrape is not a failure — in an --all sweep it is the normal case
        # for a tenant that is not on this marketplace.
        "status": outcome.SKIPPED,
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
    stats = {"snapshots": 0, "rows": 0, "errors": 0, "skipped": 0, "processed": 0,
             "blocked": 0, "recovered": 0, "blocks_by_kind": {}}
    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    n_workers = _clamp_workers(workers, total, provider)

    # What this run sets out to do, as pairs, and what is already in the file. A set,
    # so catalog rows sharing a coordinate count once — they are one request.
    scope = {(kw, l.lat, l.lon) for l in locations for kw in kw_map}
    finished: set[tuple] = set(done)
    done_before = len(scope & finished)
    popped: list = []          # stores taken off the queue, by any worker
    unattempted: list = []     # stores nobody lived to take
    unrecovered: list = []     # (location, [keywords]) still missing after the backlog

    # Every DB read is done — the scrape stages to SQLite and touches no database.
    # Release the pooled connection now: held open across a ~1.5h scrape it goes idle,
    # the Supabase pooler / home NAT silently drops it, and closing it later raises a
    # spurious SQLAlchemy error at the end of an otherwise-clean run. `locations` are
    # already-loaded ORM rows and stay readable detached (expire_on_commit=False).
    await db.close()

    try:
        async with async_playwright() as pw:
            browser = await provider.launch_browser(pw)
            try:
                logger.info(
                    f"orchestrator: tenant {tid} on {mp_slug} — {n_workers} workers × "
                    f"{total} stores, cap={cap}"
                )
                warn_if_co_located(locations, "orchestrator")
                tasks = [
                    asyncio.create_task(_worker(
                        w, provider, browser, seed, queue, kw_map, competitor_list,
                        finished, popped, stg, stats, total, tid, job_id, cap,
                    ))
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)

                # The pool has returned — which means EITHER the queue is empty OR
                # every worker gave up. Only the queue can say which.
                unattempted = _drain(queue)
                misses = _missing(popped, kw_map, finished)
                n_missed = sum(len(kws) for _, kws in misses)

                # Backlog pass: one more look at everything the main pass left
                # unanswered, now that the main queue is fully drained (so this can't
                # starve stores still waiting their first attempt). Same browser,
                # so no new launch overhead.
                #
                # NOT run when stores were left unattempted: that means every worker
                # lost its session, and a backlog pool would open straight into the
                # same wall. The run ends `partial` and --resume picks all of it up.
                if misses and unattempted:
                    logger.warning(
                        f"orchestrator: the workers stopped with {len(unattempted)} "
                        f"stores untouched — skipping the backlog pass ({n_missed} "
                        f"pairs); --resume continues from here"
                    )
                elif misses:
                    logger.info(
                        f"orchestrator: main pass done — {n_missed} pairs missing "
                        f"across {len(misses)} stores, running one backlog pass"
                    )
                    retry_queue: asyncio.Queue = asyncio.Queue()
                    for item in misses:
                        retry_queue.put_nowait(item)
                    retry_tasks = [
                        asyncio.create_task(_retry_worker(
                            w, provider, browser, seed, retry_queue, kw_map,
                            competitor_list, finished, stg, stats, tid, job_id, cap,
                        ))
                        for w in range(1, min(n_workers, len(misses)) + 1)
                    ]
                    await asyncio.gather(*retry_tasks)
                    logger.info(
                        f"orchestrator: backlog pass done — "
                        f"{stats['recovered']}/{n_missed} recovered"
                    )
                unrecovered = _missing(popped, kw_map, finished)
            finally:
                await browser.close()
    except Exception as e:
        staging.update_stats(stg, stats, total)
        staging.finish_run(stg, outcome.FAILED, str(e))
        staging.close(stg)
        logger.error(f"orchestrator: tenant {tid} run failed: {e}")
        raise

    # ── How did it end? Decided from coverage, not from having got this far. ──
    pairs_done = len(scope & finished)
    n_unrecovered = sum(len(kws) for _, kws in unrecovered)
    status = outcome.decide(
        expected=len(scope), done=pairs_done,
        done_this_run=pairs_done - done_before,
        unattempted_stores=len(unattempted),
    )
    note = outcome.describe(
        expected=len(scope), done=pairs_done, unattempted_stores=len(unattempted),
        stores_total=total, unrecovered=n_unrecovered, unit="keyword-store",
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
        snapshots=stats["snapshots"], rows=stats["rows"], errors=stats["errors"],
        skipped=stats["skipped"], status=status, note=note,
        blocked=stats["blocked"], blocks_by_kind=stats["blocks_by_kind"],
        recovered=stats["recovered"],
        unattempted=len(unattempted), unrecovered=n_unrecovered,
        pairs_total=len(scope), pairs_done=pairs_done,
        coverage_pct=outcome.coverage_pct(pairs_done, len(scope)),
    )
    # Four numbers, because they mean four different things:
    #   blocked      we hit a rate limit and waited; costs time, not data
    #   errors       a request genuinely failed (it may have been recovered later)
    #   unrecovered  pairs unanswered at stores that were reached <- data missing
    #   unattempted  stores no worker lived to take               <- data missing
    logger.info(
        f"orchestrator: tenant {tid} {status.upper()} — {note} · "
        f"{stats['snapshots']} snapshots, {stats['rows']} rows, "
        f"{stats['blocked']} blocked (waited out{_kinds(stats)}), "
        f"{stats['errors']} errors, {stats['skipped']} skipped"
    )
    # A count is not actionable — name what is missing.
    if unrecovered:
        logger.warning(
            f"orchestrator: {n_unrecovered} (store, keyword) pair(s) got no answer:"
        )
        for loc, kws in unrecovered[:20]:
            logger.warning(f"    {loc.merchant_id}  {loc.city}  {', '.join(kws)}")
        if len(unrecovered) > 20:
            logger.warning(f"    ... and {len(unrecovered) - 20} more stores")
    if status == outcome.SUCCESS:
        logger.info(
            f"orchestrator: staged to {stg['path'].name} — NOT yet in the database. "
            f"Push it with:  python -m cli scrape load"
        )
    else:
        logger.warning(
            f"orchestrator: {stg['path'].name} is {status} and will NOT be auto-loaded. "
            f"Continue it with --resume, or load what it has with "
            f"`python -m cli scrape load --file {staging.ref(stg['path'])}`"
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
