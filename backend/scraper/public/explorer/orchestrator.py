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
import uuid
from dataclasses import dataclass, field
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
from scraper.public.explorer.providers import Provider, get_provider
from scraper.utils.browser import PLAYWRIGHT_ARGS
from scraper.utils.search_result import classify_products, is_combo_name, slugify

DEFAULT_KEYWORD_CAP = 12
DEFAULT_BRAND_CAP = 60

_STORE_SKIP_AFTER = 2   # consecutive failed fetches at a location → skip its remaining keywords
_REFRESH_AFTER = 8      # consecutive failed fetches → session likely stale, re-open
_PACING = 0.05          # polite gap between locations (seconds)
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
        q.order_by(MarketplaceLocation.city, MarketplaceLocation.zone)
    )).scalars().all()

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
    return {
        **base,
        "keyword": keyword,
        "position": row.get("position"),
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
        "rating": row.get("rating"),
        "product_state": row.get("product_state", ""),
        "l0": cat.get("l0"),
        "l1": cat.get("l1"),
        "l2": cat.get("l2"),
        "merchant_type": row.get("merchant_type", ""),
        "image_url": row.get("image_url", ""),
        "is_combo": is_combo_name(row.get("name", "")),
    }


def _sku_row(base: dict, merchant_id: str, row: dict) -> dict:
    return {
        **base,
        "merchant_id": merchant_id,
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
        "is_combo": is_combo_name(row.get("name", "")),
    }


# ── Scrape helpers ────────────────────────────────────────────────────────────

async def _safe_search(provider: Provider, session: dict, keyword: str, cap: int,
                       loc: MarketplaceLocation, follow_similarity: bool = False) -> dict:
    try:
        return await provider.search(
            session, keyword, cap, lat=loc.lat, lon=loc.lon,
            follow_similarity=follow_similarity,
        )
    except Exception as e:
        return {"ok": False, "products": [], "error": f"{type(e).__name__}: {e}"}


async def _reopen(provider: Provider, browser, session: dict,
                  loc: MarketplaceLocation, wid: int) -> dict | None:
    await provider.close_session(session)
    new = await provider.open_session(browser, loc.lat, loc.lon)
    if not new:
        logger.warning(f"explorer w{wid}: session refresh failed — worker exiting")
    return new


# ── Worker ────────────────────────────────────────────────────────────────────

async def _worker(wid: int, provider: Provider, browser, seed: tuple, queue: asyncio.Queue,
                  spec: ExplorerSpec, ctx: dict, result: ExplorerResult, stats: dict) -> None:
    """One concurrent worker: its own browser context + session, pulling locations
    off the shared queue and appending classified rows to the shared accumulators
    (safe under asyncio — appends never interleave across awaits)."""
    kw_cap = spec.cap or DEFAULT_KEYWORD_CAP
    brand_cap = spec.brand_cap or DEFAULT_BRAND_CAP
    do_keyword = spec.mode in ("keyword", "both")
    do_catalog = spec.mode in ("catalog", "both")
    brand_query = ctx["aliases"][0] if ctx["aliases"] else ctx["brand_slug"].replace("-", " ")

    session = await provider.open_session(browser, seed[0], seed[1])
    if not session:
        logger.warning(f"explorer w{wid}: could not open session — exiting")
        return
    stale = 0
    try:
        while True:
            try:
                loc = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            base = {"city": loc.city, "zone": loc.zone or "", "pincode": loc.pincode or "",
                    "lat": loc.lat, "lon": loc.lon}
            store_fail = 0
            try:
                if do_keyword:
                    for kw in spec.keywords:
                        if store_fail >= _STORE_SKIP_AFTER:
                            break
                        res = await _safe_search(provider, session, kw, kw_cap, loc)
                        if not res.get("ok"):
                            store_fail += 1
                            stale += 1
                            stats["errors"] += 1
                            result.errors.append({**base, "keyword": kw,
                                                  "error": res.get("error") or "no result"})
                            if stale >= _REFRESH_AFTER:
                                session = await _reopen(provider, browser, session, loc, wid)
                                stale = 0
                                if session is None:
                                    return
                            continue
                        stale = 0
                        products = res.get("products") or []
                        if not products:
                            continue
                        cls = classify_products(products, ctx["brand_slug"], ctx["aliases"], ctx["competitors"])
                        result.snapshots.append({
                            **base, "keyword": kw,
                            "merchant_id": res.get("merchant_id", ""),
                            "total_results": res.get("total_results") or len(cls["listings"]),
                            "brand_rank": cls["brand_rank"],
                            "brand_sov_pct": cls["brand_sov_pct"],
                            "brand_product_count": cls["brand_product_count"],
                        })
                        stats["snapshots"] += 1
                        for row in cls["listings"]:
                            result.listings.append(_listing_row(base, kw, row))
                            stats["rows"] += 1

                if do_catalog:
                    res = await _safe_search(provider, session, brand_query, brand_cap, loc,
                                             follow_similarity=True)
                    if res.get("ok") and res.get("products"):
                        stale = 0
                        cls = classify_products(res["products"], ctx["brand_slug"], ctx["aliases"], competitors=[])
                        for row in cls["listings"]:
                            result.sku_rows.append(_sku_row(base, res.get("merchant_id", ""), row))
                            stats["skus"] += 1
                    elif not res.get("ok"):
                        stale += 1
                        stats["errors"] += 1
                        result.errors.append({**base, "keyword": f"[brand:{brand_query}]",
                                              "error": res.get("error") or "no result"})
                        if stale >= _REFRESH_AFTER:
                            session = await _reopen(provider, browser, session, loc, wid)
                            stale = 0
                            if session is None:
                                return
            except Exception as e:
                # One bad location must not abort the whole run — log, count, move on.
                stats["errors"] += 1
                result.errors.append({**base, "keyword": "[location]",
                                      "error": f"{type(e).__name__}: {e}"})
                logger.warning(
                    f"explorer w{wid}: {loc.city} ({loc.lat},{loc.lon}) errored: "
                    f"{type(e).__name__}: {e}"
                )

            stats["processed"] += 1
            await asyncio.sleep(_PACING)
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
    if error is not None:
        await db.rollback()  # clear any aborted txn so the failure record itself commits
    await db.execute(update(ExplorerRun).where(ExplorerRun.id == run_id).values(
        status=status, processed=processed, snapshots=stats.get("snapshots", 0),
        rows=_row_total(stats), errors=stats.get("errors", 0),
        completed_at=now_ist(), error=error,
    ))
    await db.commit()


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
    result.run_id = str(run.id)

    if not locations:
        logger.warning("explorer: no catalog locations matched the requested cities — nothing to scrape")
        await _finalize(db, run.id, JobStatus.success, stats, 0)
        return result
    if spec.mode in ("keyword", "both") and not spec.keywords:
        logger.warning("explorer: keyword mode but no keywords supplied")

    total = len(locations)
    queue: asyncio.Queue = asyncio.Queue()
    for loc in locations:
        queue.put_nowait(loc)
    seed = (locations[0].lat, locations[0].lon)
    n_workers = max(1, min(spec.workers, total))

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=PLAYWRIGHT_ARGS)
            ticker = asyncio.create_task(_progress_ticker(run.id, stats, total, on_progress))
            try:
                logger.info(
                    f"explorer: run {run.id} — {n_workers} workers × {total} locations, "
                    f"mode={spec.mode}, brand={brand_slug}"
                )
                tasks = [
                    asyncio.create_task(
                        _worker(w, provider, browser, seed, queue, spec, ctx, result, stats)
                    )
                    for w in range(1, n_workers + 1)
                ]
                await asyncio.gather(*tasks)
            finally:
                ticker.cancel()
                try:
                    await ticker
                except asyncio.CancelledError:
                    pass
                await browser.close()
        await _finalize(db, run.id, JobStatus.success, stats, total)
    except Exception as e:
        await _finalize(db, run.id, JobStatus.failed, stats, stats["processed"], error=str(e))
        logger.error(f"explorer: run {run.id} failed: {e}")
        raise

    logger.info(
        f"explorer: run {run.id} done — {stats['snapshots']} snapshots, "
        f"{stats['rows']} listings, {stats['skus']} skus, {stats['errors']} errors"
    )
    return result
