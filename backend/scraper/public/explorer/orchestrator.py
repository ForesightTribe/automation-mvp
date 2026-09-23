"""Explorer orchestrator — the ad-hoc, ephemeral scrape engine.

Same worker-pool shape as `scraper/public/orchestrator.py` (one browser, N
context-workers pulling locations off a shared queue, session reused across
keywords), but:

  - inputs come from an `ExplorerSpec`, not a tenant's watchlist;
  - locations come from `marketplace_locations` filtered by city (NOT
    `tenant_locations`), distinct `(lat, lon)`, optionally sampled;
  - results accumulate IN MEMORY and are handed back — NOTHING is written to the
    per-tenant fact tables (`search_snapshots` / `search_listings` /
    `sku_snapshots`);
  - the only DB writes are to `explorer_runs` (status + live progress).

`build_insights` (Phase 2) turns the returned `ExplorerResult` into the workbook
(and, later, a JSON insights endpoint). Workers hold no DB session — the run is
ephemeral, so there is nothing per-worker to persist.
"""
import asyncio
import hashlib
import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import async_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.explorer import ExplorerRun
from app.models.job import JobStatus
from app.models.search import MarketplaceLocation
from app.schemas.explorer import ExplorerSpec
from app.utils.logger import logger
from app.utils.time import now_ist
from scraper.public import guards
from scraper.public.explorer.providers import Provider, get_provider
from scraper.public.orchestrator import warn_if_co_located
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.pack import pack_fields, combo_from_pack
from scraper.utils.search_result import classify_products, slugify

DEFAULT_KEYWORD_CAP = 12
DEFAULT_BRAND_CAP = 60

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a location → skip its remaining keywords
_REFRESH_AFTER = 8      # consecutive failed fetches → session likely stale, re-open
# Fallback only — the real gap comes off the provider (see providers.py), because
# it is per marketplace. Blinkit tolerates 0.05 s between locations; Zepto's
# limiter is per connection and that pace trips it within a minute.
_PACING = 0.05
# Ported from scraper/public/orchestrator.py. Opening a session means loading the
# marketplace homepage and capturing the first search request's headers; workers
# doing that in the same second lose the capture window, and an explorer worker
# that failed simply exited and was never replaced — so a run asked for 4 workers
# and quietly did the whole job on 2.
_WORKER_STAGGER_S = 5
_OPEN_SESSION_RETRY_S = (10, 30)      # waits before attempt 2, attempt 3
_TICK_S = 1.5           # how often live progress is flushed to explorer_runs


@dataclass
class ExplorerResult:
    """In-memory output of a run — the raw material `build_insights` aggregates."""

    run_id: str
    spec: ExplorerSpec
    locations: int
    snapshots: list[dict] = field(default_factory=list)   # per (keyword × location) header
    listings: list[dict] = field(default_factory=list)    # per product (keyword mode)
    sku_rows: list[dict] = field(default_factory=list)     # per own product (catalog mode)
    errors: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    # Locations whose LAST attempt failed, keyed (lat, lon). A store that
    # answered fine and simply had no matching products is NOT in here - that
    # is a real zero, and retrying it would double the run to re-learn it.
    failed_locs: dict = field(default_factory=dict)
    checkpoint_path: str = ""
    resumed_from: int = 0
    # True only when every location was scraped. The CLI keys the checkpoint
    # delete on this: a run that lost its workers to a network outage returns
    # normally and looks like a success, and clearing on that would throw away
    # the only record of what HAD been done.
    complete: bool = False


# ── Location resolution (catalog by city, sampled) ────────────────────────────

def _even_sample(items: list, n: int | None) -> list:
    """An evenly-spread subset of `n` items (representative, not just the first N).
    `n` falsy or ≥ len → all items."""
    if not n or len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


async def _resolve_locations(db: AsyncSession, spec: ExplorerSpec) -> list[MarketplaceLocation]:
    """Catalog locations for the marketplace, filtered by city, deduped to distinct
    `(lat, lon)`, then sampled per city (unless `full`)."""
    q = select(MarketplaceLocation).where(
        MarketplaceLocation.mp_slug == spec.marketplace,
        MarketplaceLocation.is_active == True,  # noqa: E712
    )
    if spec.cities:
        q = q.where(MarketplaceLocation.city.in_(list(spec.cities)))
    rows = (await db.execute(
        q.order_by(MarketplaceLocation.city, MarketplaceLocation.merchant_id)
    )).scalars().all()

    # Warn BEFORE deduping. The explorer collapses co-located rows silently, which
    # is convenient for an ad-hoc run and is also exactly the hiding that
    # `warn_if_co_located` exists to prevent: duplicate coordinates are a CATALOG
    # fault (two rows describing one probe point), and the per-tenant scrapes pay
    # for them in real duplicated work. Surfacing it here keeps the dedupe without
    # letting the underlying problem go unannounced.
    warn_if_co_located(rows, f"explorer/{spec.marketplace}")

    seen: set[tuple] = set()
    by_city: dict[str, list] = {}
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        key = (round(r.lat, 6), round(r.lon, 6))
        if key in seen:
            continue
        seen.add(key)
        by_city.setdefault(r.city, []).append(r)

    n = None if spec.full else spec.sample
    out: list[MarketplaceLocation] = []
    for items in by_city.values():
        out.extend(_even_sample(items, n))
    return out


# ── Row builders (full field set — Explorer keeps everything the engine extracts) ─

def _listing_row(base: dict, keyword: str, row: dict) -> dict:
    cat = row.get("category") or {}
    pf = pack_fields(row.get("unit"))
    return {
        **base,
        "keyword": keyword,
        "position": row.get("position"),
        # Per-product store — one keyword's results routinely span several.
        "merchant_id": row.get("merchant_id", ""),
        "name": row.get("name", ""),
        "brand": row.get("brand", ""),
        "is_brand": row.get("is_brand", False),
        "brand_slug": row.get("brand_slug", ""),
        "price": row.get("price"),
        "mrp": row.get("mrp"),
        "discount_pct": row.get("discount_pct"),
        "in_stock": row.get("in_stock", True),
        "inventory": row.get("inventory"),
        "product_id": row.get("product_id", ""),
        "unit": row.get("unit", ""),
        "pack_size": pf["pack_size"],
        "pack_uom": pf["pack_uom"],
        "pack_count": pf["pack_count"],
        "rating": row.get("rating"),
        "product_state": row.get("product_state", ""),
        "l0": cat.get("l0"),
        "l1": cat.get("l1"),
        "l2": cat.get("l2"),
        "merchant_type": row.get("merchant_type", ""),
        "image_url": row.get("image_url", ""),
        "is_combo": combo_from_pack(row.get("name", ""), pf["pack_count"]),
        # ── Sponsored placement ──────────────────────────────────────────────
        # The engines fetch and parse this, and the per-tenant path stores it
        # (see `listing_extra` in scraper/utils/search_result.py), but the
        # explorer dropped it here — one step before recording. So an ad-vs-
        # organic question could not be answered from an explorer run at all,
        # and a paid placement was indistinguishable from an earned one.
        #
        # Zepto's `ucl_id` carries the advertiser, the campaign, and the keyword
        # that WON the slot — which is NOT necessarily the keyword searched, so
        # it is kept separately rather than folded into `keyword`.
        "is_ad": bool(row.get("is_ad")),
        **_ad_fields(row),
    }


def _ad_fields(row: dict) -> dict:
    """Flattened ad attribution for one listing, empty-valued on organic rows.

    Blinkit exposes its ids in `ad_meta`; Zepto encodes everything in `ucl_id`.
    Both are normalised to the same column names here so the workbook has one
    ad shape rather than one per marketplace.
    """
    if not row.get("is_ad"):
        return {"ad_advertiser_id": "", "ad_campaign_id": "",
                "ad_keyword": "", "ad_match_type": "", "ad_model": ""}
    meta = dict(row.get("ad_meta") or {})
    ucl = row.get("ucl_id")
    if ucl:
        try:
            from scraper.platforms.zepto.public_data import ads as _zads
            meta.update(_zads.parse_ucl_id(ucl))
        except Exception:
            pass
    return {
        "ad_advertiser_id": meta.get("advertiser_id", ""),
        "ad_campaign_id": str(meta.get("campaign_id")
                              or meta.get("ads_campaign_id") or ""),
        "ad_keyword": meta.get("keyword", ""),
        "ad_match_type": meta.get("match_type", ""),
        "ad_model": meta.get("model") or meta.get("ads_type") or "",
    }


def _sku_row(base: dict, row: dict) -> dict:
    pf = pack_fields(row.get("unit"))
    return {
        **base,
        # The product's OWN store/tier — a brand's catalog can span an express store
        # and one or more longtail hubs at the same coordinate, so this can never be
        # the snapshot's single merchant. See docs/darkstores.md.
        "merchant_id": row.get("merchant_id", ""),
        "merchant_type": row.get("merchant_type", ""),
        "product_id": row.get("product_id", ""),
        "name": row.get("name", ""),
        "brand_slug": row.get("brand_slug", ""),
        "price": row.get("price"),
        "mrp": row.get("mrp"),
        "discount_pct": row.get("discount_pct"),
        "in_stock": row.get("in_stock", True),
        "inventory": row.get("inventory"),
        "rating": row.get("rating"),
        "unit": row.get("unit", ""),
        "pack_size": pf["pack_size"],
        "pack_uom": pf["pack_uom"],
        "pack_count": pf["pack_count"],
        "is_combo": combo_from_pack(row.get("name", ""), pf["pack_count"]),
    }


# ── Scrape helpers ────────────────────────────────────────────────────────────

async def _safe_search(provider: Provider, session: dict, keyword: str, cap: int,
                       loc: MarketplaceLocation, follow_similarity: bool = False,
                       distinct_ad_slots: bool = True) -> dict:
    """Every explorer search goes through here, which is why the per-marketplace
    gap lives here rather than at each call site.

    The gap is UNCONDITIONAL — in a `finally`, so it fires on a failed search too.
    A marketplace that rate-limits per connection counts the blocked request as
    well, so skipping the gap on failure is how a run digs itself deeper.
    """
    try:
        # Pass the store id, not just the coordinate. The catalog row IS the store,
        # so a lookup is never needed — and on a marketplace that binds by header
        # (Zepto) omitting it spends an extra `get_page` per store against a
        # SECOND, independently rate-limited budget. See providers.py.
        return await provider.search(
            session, keyword, cap, lat=loc.lat, lon=loc.lon,
            merchant_id=getattr(loc, "merchant_id", None) or None,
            follow_similarity=follow_similarity,
            distinct_ad_slots=distinct_ad_slots,
        )
    except Exception as e:
        return {"ok": False, "products": [], "error": f"{type(e).__name__}: {e}"}
    finally:
        if provider.search_gap_s:
            await asyncio.sleep(provider.search_gap_s)


async def _reopen(provider: Provider, browser, session: dict,
                  loc: MarketplaceLocation, wid: int) -> dict | None:
    """Rebuild a worker's session, retrying on the same ladder as the first open.

    This used to make ONE attempt and, on failure, exit the worker for good. That
    is the difference between riding out a 90-second network blip and silently
    finishing a multi-hour run on half the pool — a worker that exits is never
    replaced, and nothing in the output says the pool shrank. A mid-run reopen is
    strictly MORE likely to hit a transient than the first one, because by then
    the run has been hammering the same IP for hours.
    """
    await provider.close_session(session)
    for attempt, wait in enumerate((*_OPEN_SESSION_RETRY_S, None), start=1):
        new = await provider.open_session(browser, loc.lat, loc.lon)
        if new:
            if attempt > 1:
                logger.info(f"explorer w{wid}: session refreshed on attempt {attempt}")
            return new
        if wait is None:
            break
        logger.warning(f"explorer w{wid}: session refresh failed "
                       f"(attempt {attempt}) — retrying in {wait}s")
        await asyncio.sleep(wait)
    logger.warning(f"explorer w{wid}: session refresh failed after "
                   f"{len(_OPEN_SESSION_RETRY_S) + 1} attempts — worker exiting")
    return None


def _unscraped(locations, result) -> list:
    """Locations whose last attempt FAILED - not merely ones that returned nothing.

    The distinction is the whole point. On a brand-presence census most stores
    legitimately return no matching product, and retrying those would double the
    run to re-learn the same zero. Only a store we never got a clean answer out of
    is a hole worth going back for.
    """
    return list(result.failed_locs.values())


_JITTER_FRAC = 0.25


def _jittered(base_s: float) -> float:
    """`base_s` +/- `_JITTER_FRAC`. Workers hit the same gate within seconds of each
    other, so an un-jittered wait makes them recover in lockstep and retry as one
    synchronized burst - which just trips the gate again."""
    spread = base_s * _JITTER_FRAC
    return max(1.0, base_s + random.uniform(-spread, spread))


async def _search_with_recovery(provider: Provider, session: dict, browser, keyword: str,
                                cap: int, loc: MarketplaceLocation, wid: int,
                                follow_similarity: bool = False,
                                distinct_ad_slots: bool = True) -> tuple[dict, dict | None]:
    """Search, treating a BLOCK as something to wait out rather than a result.

    The explorer used to record a block as a permanent failure and move on to the
    next store. On Zepto that is wrong in the most damaging way available: a 299
    LOGIN_REQUIRED is connection-wide and clears in ~60 s, so one gate turned into a
    run of ~45 consecutive stores filed as "brand not present". Those are holes, and
    an insights workbook cannot tell a hole from a zero.

    This mirrors the recovery `scraper/public/orchestrator.py` already does for the
    per-tenant scrapes; the tunables come off the provider, which already carries
    them (`probe_every_s`, `max_block_waits`).

    Returns (result, session) - the session may have been replaced, and is None if
    it could not be rebuilt, which the caller must treat as "this worker is done".
    """
    res = await _safe_search(provider, session, keyword, cap, loc,
                             follow_similarity, distinct_ad_slots)
    if res.get("ok") or not res.get("blocked") or not provider.probe_every_s:
        return res, session

    waits = 0
    while waits < provider.max_block_waits:
        waits += 1
        logger.warning(
            f"explorer w{wid}: blocked ({res.get('kind') or 'block'}) at {loc.city} - "
            f"waiting {provider.probe_every_s}s ({waits}/{provider.max_block_waits})"
        )
        await asyncio.sleep(_jittered(provider.probe_every_s))
        session = await _reopen(provider, browser, session, loc, wid)
        if session is None:
            return res, None
        res = await _safe_search(provider, session, keyword, cap, loc,
                                 follow_similarity, distinct_ad_slots)
        if res.get("ok") or not res.get("blocked"):
            return res, session
    logger.warning(f"explorer w{wid}: still blocked at {loc.city} after "
                   f"{provider.max_block_waits} waits - giving up on this location")
    return res, session


# ── Checkpoint / resume ──────────────────────────────────────────────────────
#
# A pan-India census is a multi-hour job, and the explorer accumulates everything
# IN MEMORY until the workbook is written at the very end. Without a checkpoint a
# dropped connection nine hours in loses nine hours of scraping — and re-running
# it re-asks Zepto every question it already answered.
#
# The checkpoint unit is ONE COMPLETED STORE, because that is what the outer loop
# iterates. Each finished store appends one JSON line carrying its own rows, so a
# resume replays the file into the accumulators and skips those stores.
#
# It is a LOCAL file on purpose. The DB and the network are exactly what fail, so
# a checkpoint that needs either is a checkpoint that is absent when it matters.

def _ckpt_dir() -> Path:
    """`backend/state/explorer`, resolved defensively.

    Walks up looking for the `backend` package root rather than indexing a fixed
    number of parents: a hard `parents[3]` raises IndexError at IMPORT time if this
    module is ever moved or loaded from another path, which takes down the whole
    CLI rather than just the checkpoint.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "backend":
            return parent / "state" / "explorer"
    return here.parent / "state" / "explorer"


_CKPT_DIR = _ckpt_dir()
_CKPT_MAX_AGE = timedelta(days=2)


def _ckpt_key(spec: ExplorerSpec) -> str:
    """Identity of a run, so a different keyword set can never resume this one.

    Deliberately covers everything that changes WHICH stores get asked WHAT:
    marketplace, brand, keywords, cities, mode and census-vs-sample. Cosmetics
    (label, output path, worker count) are excluded — re-running the same scrape
    with more workers should resume, not restart.
    """
    ident = json.dumps({
        "marketplace": spec.marketplace,
        "brand": slugify(spec.brand),
        "keywords": sorted(k.lower().strip() for k in (spec.keywords or [])),
        "cities": sorted(c.lower().strip() for c in (spec.cities or [])),
        "mode": spec.mode,
        "full": bool(spec.full),
        "sample": None if spec.full else spec.sample,
    }, sort_keys=True)
    return hashlib.sha1(ident.encode()).hexdigest()[:16]


class _Checkpoint:
    """Append-only, one JSON line per completed store.

    Every write is wrapped: a checkpoint failure must never take down the job it
    exists to protect. A torn final line (killed mid-write) is discarded on read,
    which costs at most one store.
    """

    def __init__(self, spec: ExplorerSpec):
        self.path = _CKPT_DIR / f"{_ckpt_key(spec)}.jsonl"
        self.enabled = True

    def load(self) -> tuple[set, list]:
        """(done store keys, records) from a checkpoint that is still applicable."""
        try:
            if not self.path.exists():
                return set(), []
            age = datetime.now() - datetime.fromtimestamp(self.path.stat().st_mtime)
            if age > _CKPT_MAX_AGE:
                logger.info(f"explorer: checkpoint {self.path.name} is {age.days}d old — ignoring")
                return set(), []
            records, done = [], set()
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue  # torn final line
                    key = (rec.get("lat"), rec.get("lon"))
                    if key in done:
                        # A retried store appears twice; the later record wins.
                        records = [r for r in records if (r.get("lat"), r.get("lon")) != key]
                    done.add(key)
                    records.append(rec)
            return done, records
        except Exception as e:
            logger.warning(f"explorer: could not read checkpoint ({e}) — starting fresh")
            return set(), []

    def append(self, rec: dict) -> None:
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning(f"explorer: checkpoint write failed ({e}) — continuing unprotected")
            self.enabled = False

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


def clear_checkpoint(spec: ExplorerSpec) -> None:
    """Called by the CLI once the workbook is safely on disk.

    Clearing inside the engine would mean a failed export costs the whole scrape,
    which is the one thing this machinery exists to prevent.
    """
    _Checkpoint(spec).clear()


async def _open_session_resilient(provider: Provider, browser, seed: tuple,
                                  wid: int) -> dict | None:
    """Stagger, then up to three attempts at opening a worker's session.

    Both behaviours come from `scraper/public/orchestrator.py`, which learned them
    on the VM: simultaneous starts blow the header-capture window, and the thing
    that kills the survivors is a short-lived IP rate-limit rather than a slow
    page — so waiting and retrying rescues most of them. The explorer had neither,
    and a failed worker exited silently, which looks identical to a smaller pool.
    """
    if _WORKER_STAGGER_S:
        await asyncio.sleep(_WORKER_STAGGER_S * (wid - 1))
    for attempt, wait in enumerate((*_OPEN_SESSION_RETRY_S, None), start=1):
        session = await provider.open_session(browser, seed[0], seed[1])
        if session:
            if attempt > 1:
                logger.info(f"explorer w{wid}: session opened on attempt {attempt}")
            return session
        if wait is None:
            break
        logger.warning(f"explorer w{wid}: could not open session (attempt {attempt}) "
                       f"— retrying in {wait}s")
        await asyncio.sleep(wait)
    logger.warning(f"explorer w{wid}: could not open session after "
                   f"{len(_OPEN_SESSION_RETRY_S) + 1} attempts — worker exiting")
    return None


def _served_wrong_store(loc, res: dict, wid: int, keyword: str) -> bool:
    """True when the response came from a store other than the one asked for.

    Mirrors the check `targeted.py` gained in d914621. It can only bite a
    marketplace that binds by COORDINATE (Blinkit picks the store itself and tells
    you which one answered); a header-bound marketplace returns what it was given.
    Filing those rows under the requested store would be silent mis-attribution,
    so they are dropped instead — a missing store is visible, a wrong one is not.
    """
    asked = getattr(loc, "merchant_id", None)
    got = res.get("merchant_id")
    if not asked or not got or str(asked) == str(got):
        return False
    logger.warning(
        f"explorer w{wid} {loc.city} [{keyword}]: asked store {str(asked)[:8]} but "
        f"got {str(got)[:8]} — dropping rather than mis-filing"
    )
    return True


# ── Worker ────────────────────────────────────────────────────────────────────

async def _worker(wid: int, provider: Provider, browser, seed: tuple, queue: asyncio.Queue,
                  spec: ExplorerSpec, ctx: dict, result: ExplorerResult, stats: dict,
                  ckpt: "_Checkpoint | None" = None,
                  stop: "asyncio.Event | None" = None) -> None:
    """One concurrent worker: its own browser context + session, pulling locations
    off the shared queue and appending classified rows to the shared accumulators
    (safe under asyncio — appends never interleave across awaits)."""
    kw_cap = spec.cap or DEFAULT_KEYWORD_CAP
    brand_cap = spec.brand_cap or DEFAULT_BRAND_CAP
    do_keyword = spec.mode in ("keyword", "both")
    do_catalog = spec.mode in ("catalog", "both")
    brand_query = ctx["aliases"][0] if ctx["aliases"] else ctx["brand_slug"].replace("-", " ")

    session = await _open_session_resilient(provider, browser, seed, wid)
    if not session:
        return
    stale = 0
    searches = 0
    try:
        while True:
            # The stall watchdog sets this when no rows have landed for
            # guards.STALL_AFTER_S. Workers exit cleanly so the run finalises with
            # what it has, instead of a wedged pool sitting inside a 12-hour job
            # ceiling. Checked here, at the top of a store, so a location is never
            # abandoned half-scraped.
            if stop is not None and stop.is_set():
                logger.warning(f"explorer w{wid}: stall detected — exiting cleanly")
                break
            try:
                loc = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            base = {"city": loc.city, "zone": loc.location_name or "", "pincode": loc.pincode or "",
                    "lat": loc.lat, "lon": loc.lon}
            store_fail = 0
            # Per-location buffers. Workers interleave on the shared accumulators,
            # so a store's own rows cannot be recovered by slicing them afterwards —
            # they have to be collected separately to be checkpointed as a unit.
            loc_snaps: list[dict] = []
            loc_rows: list[dict] = []
            loc_skus: list[dict] = []
            loc_errs: list[dict] = []
            try:
                if do_keyword:
                    for kw in spec.keywords:
                        if store_fail >= _STORE_SKIP_AFTER:
                            break
                        res, session = await _search_with_recovery(
                            provider, session, browser, kw, kw_cap, loc, wid)
                        if session is None:
                            return
                        if not res.get("ok"):
                            store_fail += 1
                            stale += 1
                            stats["errors"] += 1
                            result.failed_locs[(loc.lat, loc.lon)] = loc
                            loc_errs.append({**base, "keyword": kw,
                                             "error": res.get("error") or "no result"})
                            if stale >= _REFRESH_AFTER:
                                session = await _reopen(provider, browser, session, loc, wid)
                                stale = 0
                                if session is None:
                                    return
                            continue
                        stale = 0
                        # Answered cleanly - whatever it returned is the truth here.
                        result.failed_locs.pop((loc.lat, loc.lon), None)
                        if _served_wrong_store(loc, res, wid, kw):
                            continue
                        products = res.get("products") or []
                        if not products:
                            continue
                        cls = classify_products(products, ctx["brand_slug"], ctx["aliases"], ctx["competitors"])
                        loc_snaps.append({
                            **base, "keyword": kw,
                            "merchant_id": res.get("merchant_id", ""),
                            "total_results": res.get("total_results") or len(cls["listings"]),
                            "brand_rank": cls["brand_rank"],
                            "brand_sov_pct": cls["brand_sov_pct"],
                            "brand_product_count": cls["brand_product_count"],
                        })
                        stats["snapshots"] += 1
                        for row in cls["listings"]:
                            loc_rows.append(_listing_row(base, kw, row))
                            stats["rows"] += 1

                if do_catalog:
                    # Catalog mode builds SKU rows (a product's state at a store), so
                    # it collapses ad+organic to one row exactly as `targeted.py` does.
                    # The keyword loop above keeps them apart — same reasoning, opposite
                    # answer, because it is measuring placements. See providers.py.
                    res, session = await _search_with_recovery(
                        provider, session, browser, brand_query, brand_cap, loc, wid,
                        follow_similarity=True, distinct_ad_slots=False)
                    if session is None:
                        return
                    if res.get("ok"):
                        result.failed_locs.pop((loc.lat, loc.lon), None)
                    if res.get("ok") and res.get("products"):
                        stale = 0
                        cls = classify_products(res["products"], ctx["brand_slug"], ctx["aliases"], competitors=[])
                        for row in cls["listings"]:
                            loc_skus.append(_sku_row(base, row))
                            stats["skus"] += 1
                    elif not res.get("ok"):
                        stale += 1
                        stats["errors"] += 1
                        result.failed_locs[(loc.lat, loc.lon)] = loc
                        loc_errs.append({**base, "keyword": f"[brand:{brand_query}]",
                                         "error": res.get("error") or "no result"})
                        if stale >= _REFRESH_AFTER:
                            session = await _reopen(provider, browser, session, loc, wid)
                            stale = 0
                            if session is None:
                                return
            except Exception as e:
                # One bad location must not abort the whole run — log, count, move on.
                stats["errors"] += 1
                loc_errs.append({**base, "keyword": "[location]",
                                 "error": f"{type(e).__name__}: {e}"})
                logger.warning(
                    f"explorer w{wid}: {loc.city} ({loc.lat},{loc.lon}) errored: "
                    f"{type(e).__name__}: {e}"
                )

            # Publish this location's rows as one unit, then record it as done.
            # Order matters: the checkpoint must never claim a store whose rows
            # are not yet in the result.
            result.snapshots.extend(loc_snaps)
            result.listings.extend(loc_rows)
            result.sku_rows.extend(loc_skus)
            result.errors.extend(loc_errs)
            # Scheduled rest, if this marketplace wants one. Zepto sets none
            # (there is no volume quota to rest before); a marketplace that does
            # would otherwise crash into its wall mid-run. From orchestrator.py.
            searches += 1
            if provider.pause_every and searches % provider.pause_every == 0:
                logger.info(f"explorer w{wid}: scheduled rest "
                            f"{provider.pause_s}s after {searches} searches")
                await asyncio.sleep(provider.pause_s)

            stats["processed"] += 1
            if ckpt is not None:
                ckpt.append({
                    "lat": loc.lat, "lon": loc.lon,
                    "snapshots": loc_snaps, "listings": loc_rows,
                    "sku_rows": loc_skus, "errors": loc_errs,
                    "failed": (loc.lat, loc.lon) in result.failed_locs,
                })
            await asyncio.sleep(provider.store_gap_s)
    finally:
        if session:
            await provider.close_session(session)


# ── Progress + run-record lifecycle ───────────────────────────────────────────

def _row_total(stats: dict) -> int:
    return stats.get("rows", 0) + stats.get("skus", 0)


async def _progress_ticker(run_id: uuid.UUID, stats: dict, total: int,
                           on_progress: Callable[[int, int], None] | None) -> None:
    """Flush live progress to `explorer_runs` every _TICK_S so a polling UI (and the
    optional callback) can watch the run advance.

    Uses its OWN DB session — an `AsyncSession` must never be shared across
    concurrent tasks (doing so raises `greenlet_spawn has not been called`), so the
    ticker cannot touch the caller's `db` used for create/finalize.
    """
    try:
        async with AsyncSessionLocal() as tdb:
            while True:
                await asyncio.sleep(_TICK_S)
                await tdb.execute(update(ExplorerRun).where(ExplorerRun.id == run_id).values(
                    processed=stats["processed"], snapshots=stats["snapshots"],
                    rows=_row_total(stats), errors=stats["errors"],
                ))
                await tdb.commit()
                if on_progress:
                    on_progress(stats["processed"], total)
    except asyncio.CancelledError:
        return


async def _finalize(db: AsyncSession, run_id: uuid.UUID, status: JobStatus, stats: dict,
                    processed: int, error: str | None = None) -> None:
    stmt = update(ExplorerRun).where(ExplorerRun.id == run_id).values(
        status=status, processed=processed, snapshots=stats.get("snapshots", 0),
        rows=_row_total(stats), errors=stats.get("errors", 0),
        completed_at=now_ist(), error=error,
    )
    if error is None:
        await db.execute(stmt)
        await db.commit()
        return

    # Failure path. The caller's session has just carried a run that may have
    # lasted hours, and it can be aborted or its connection already gone — a
    # rollback on it then raises rather than clearing anything. Recording the
    # failure must not itself fail: an incomplete run that cannot write its own
    # record took down the export as well, losing a finished scrape. So the
    # rollback is best-effort and the write goes on a session of our own.
    try:
        await db.rollback()
    except Exception as e:  # noqa: BLE001 - never mask the original failure
        logger.warning(f"explorer: rollback before failure record failed: {e}")
    try:
        async with AsyncSessionLocal() as fresh:
            await fresh.execute(stmt)
            await fresh.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"explorer: could not write failure record for {run_id}: {e}")


def _uuid_or_none(v: str | None) -> uuid.UUID | None:
    return uuid.UUID(v) if v else None


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_explorer(db: AsyncSession, spec: ExplorerSpec,
                       on_progress: Callable[[int, int], None] | None = None) -> ExplorerResult:
    """Run one ad-hoc Explorer scrape and return its in-memory result.

    Opens an `explorer_runs` record, resolves catalog locations (sampled), runs the
    worker pool, and finalizes the record — without writing a single row to the
    per-tenant fact tables. Async and background-runnable: a future API endpoint
    launches this as a task and polls `explorer_runs`; the CLI just awaits it.
    """
    provider = get_provider(spec.marketplace)
    brand_slug = slugify(spec.brand)
    aliases = [a.strip() for a in (spec.aliases or []) if a.strip()] or [spec.brand.lower()]
    competitors = [(slugify(c), [c.lower()]) for c in spec.competitors if c.strip()] or None
    ctx = {"brand_slug": brand_slug, "aliases": aliases, "competitors": competitors}

    locations = await _resolve_locations(db, spec)
    stats = {"processed": 0, "snapshots": 0, "rows": 0, "skus": 0, "errors": 0}
    result = ExplorerResult(run_id="", spec=spec, locations=len(locations), stats=stats)

    # Resume, if a checkpoint for THIS spec is present and still fresh.
    #
    # A store that FAILED is deliberately not treated as done: it gets re-queued
    # so a resume retries it. Filing a blocked store as complete is exactly the
    # hole-vs-zero confusion this engine already had once.
    ckpt = _Checkpoint(spec)
    result.checkpoint_path = str(ckpt.path)
    done_keys, done_records = ckpt.load()
    done_keys = set()
    for rec in done_records:
        if rec.get("failed"):
            continue
        done_keys.add((rec.get("lat"), rec.get("lon")))
        result.snapshots.extend(rec.get("snapshots") or [])
        result.listings.extend(rec.get("listings") or [])
        result.sku_rows.extend(rec.get("sku_rows") or [])
        result.errors.extend(rec.get("errors") or [])
    if done_keys:
        stats["snapshots"] = len(result.snapshots)
        stats["rows"] = len(result.listings)
        stats["skus"] = len(result.sku_rows)
        stats["errors"] = len(result.errors)
        stats["processed"] = len(done_keys)
        result.resumed_from = len(done_keys)
        logger.info(
            f"explorer: resuming from checkpoint {ckpt.path.name} — "
            f"{len(done_keys)}/{len(locations)} stores already done, "
            f"{len(result.listings)} rows recovered"
        )

    run = ExplorerRun(
        account_id=_uuid_or_none(spec.account_id),
        tenant_id=_uuid_or_none(spec.tenant_id),
        marketplace=spec.marketplace, mode=spec.mode, brand_slug=brand_slug,
        label=spec.label or "", params=spec.model_dump(mode="json"),
        status=JobStatus.running, total=len(locations),
        keywords=len(spec.keywords), locations=len(locations), started_at=now_ist(),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    # Hold the id as a plain value, and never read it off the ORM object again.
    # A rollback expires every instance in the session regardless of
    # expire_on_commit, so a later `run.id` is a lazy refresh — sync IO from an
    # async context, which raises MissingGreenlet. That killed the export of a
    # finished scrape whenever a run ended with an unresolved location.
    run_id = run.id
    result.run_id = str(run_id)

    if not locations:
        logger.warning("explorer: no catalog locations matched the requested cities — nothing to scrape")
        await _finalize(db, run_id, JobStatus.success, stats, 0)
        return result
    if spec.mode in ("keyword", "both") and not spec.keywords:
        logger.warning("explorer: keyword mode but no keywords supplied")

    total = len(locations)
    pending = [l for l in locations if (l.lat, l.lon) not in done_keys]
    queue: asyncio.Queue = asyncio.Queue()
    for loc in pending:
        queue.put_nowait(loc)
    seed = (pending[0].lat, pending[0].lon) if pending else (locations[0].lat, locations[0].lon)
    n_workers = max(1, min(spec.workers, len(pending) or 1))

    try:
        async with async_playwright() as pw:
            # ONE BROWSER PROCESS PER WORKER — not N contexts on one browser.
            #
            # Chromium multiplexes every request to an origin onto a SINGLE HTTP/2
            # connection per process. A browser context isolates cookies and storage;
            # it does not isolate the socket pool. So on a marketplace whose limiter
            # is per connection (Zepto), N contexts on one browser all queue behind
            # one budget.
            #
            # That is what the old "4 workers buys 1.02x, so scale with IPs not
            # workers" measurement actually showed: it never opened a second
            # connection, so it could not tell "per connection" from "per IP".
            # N processes get N connections from the SAME IP.
            #
            # Blinkit is unaffected: its limiter is time-based, so it scaled on
            # contexts before and scales on processes now.
            browsers = [
                await pw.chromium.launch(headless=provider.headless, args=PLAYWRIGHT_ARGS)
                for _ in range(n_workers)
            ]
            ticker = asyncio.create_task(_progress_ticker(run_id, stats, total, on_progress))
            # Progress watchdog. A job timeout cannot tell a slow run from a dead
            # one — a national census legitimately runs for hours, so its ceiling
            # has to sit high enough that a wedged run stalls for most of a day
            # before anything notices. Watches rows instead. From guards.py, which
            # orchestrator.py and targeted.py already use.
            stop = asyncio.Event()
            watchdog = asyncio.create_task(
                guards.watch_for_stall(stats, stop, label="explorer")
            )
            try:
                logger.info(
                    f"explorer: run {run_id} — {n_workers} workers × {len(pending)} "
                    f"location(s) to do of {total}, mode={spec.mode}, brand={brand_slug}"
                    + (f" (resumed, {result.resumed_from} already done)"
                       if result.resumed_from else "")
                )
                tasks = [
                    asyncio.create_task(
                        _worker(w, provider, browsers[w - 1], seed, queue, spec, ctx,
                                result, stats, ckpt, stop)
                    )
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)

                # ── Retry pass ────────────────────────────────────────────────
                # A location that produced no snapshot is not evidence the brand is
                # absent there. On Zepto the dominant failure is a dead session (the
                # WAF pass expires after 4-6 min and the worker only notices after
                # _REFRESH_AFTER consecutive misses), which burns a run of stores
                # that were never actually asked. Those are holes, and an insights
                # workbook cannot tell a hole from a zero — it reports both as "not
                # present". Retry them once on fresh sessions before finalising.
                missed = _unscraped(locations, result)
                if missed:
                    logger.info(
                        f"explorer: retry pass — {len(missed)} location(s) returned "
                        f"no snapshot on the first pass"
                    )
                    for loc in missed:
                        queue.put_nowait(loc)
                    retry_workers = max(1, min(n_workers, len(missed)))
                    # Hard ceiling, as orchestrator.py puts on its backlog pass:
                    # every location in here has already failed, so this is a
                    # courtesy retry and must never outlast the pass that made it.
                    await guards.run_with_deadline(
                        asyncio.gather(*[
                            asyncio.create_task(
                                _worker(w, provider, browsers[w - 1], seed, queue, spec,
                                        ctx, result, stats, ckpt)
                            )
                            for w in range(1, retry_workers + 1)
                        ]),
                        guards.RETRY_DEADLINE_S,
                        "explorer: retry pass",
                    )
                    # Drop the first-pass errors for locations the retry recovered,
                    # so `errors` counts real failures rather than transient ones.
                    done = {(s["lat"], s["lon"]) for s in result.snapshots}
                    result.errors = [e for e in result.errors
                                     if (e.get("lat"), e.get("lon")) not in done]
                    stats["errors"] = len(result.errors)
                    stats["processed"] = total
                    logger.info(
                        f"explorer: retry pass done — "
                        f"{len(missed) - len(_unscraped(locations, result))} recovered, "
                        f"{len(_unscraped(locations, result))} still missing"
                    )
            finally:
                ticker.cancel()
                watchdog.cancel()
                for t in (ticker, watchdog):
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                for b in browsers:
                    try:
                        await b.close()
                    except Exception:
                        pass
        missing = _unscraped(locations, result)
        scraped = stats["processed"] >= total
        result.complete = scraped and not missing
        if not result.complete:
            logger.warning(
                f"explorer: run {run_id} finished INCOMPLETE — "
                f"{stats['processed']}/{total} locations processed, "
                f"{len(missing)} unresolved. Checkpoint kept for resume."
            )
        await _finalize(
            db, run_id,
            JobStatus.success if result.complete else JobStatus.failed,
            stats, stats["processed"],
            error=None if result.complete else
            f"incomplete: {stats['processed']}/{total} processed, {len(missing)} unresolved",
        )
    except Exception as e:
        await _finalize(db, run_id, JobStatus.failed, stats, stats["processed"], error=str(e))
        logger.error(f"explorer: run {run_id} failed: {e}")
        raise

    logger.info(
        f"explorer: run {run_id} done — {stats['snapshots']} snapshots, "
        f"{stats['rows']} listings, {stats['skus']} skus, {stats['errors']} errors"
    )
    return result
