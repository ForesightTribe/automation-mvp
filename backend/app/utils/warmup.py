"""Keep the Overview's expensive reads computed ahead of the reader.

The public scrape lands ONCE A DAY, so the aggregates built on it change once a
day — but each one costs seconds to build, because `search_listings` is 1.8M
rows and the cost is heap I/O rather than CPU. Computing them when someone opens
the page means a person waits for numbers that were already true this morning.

So this recomputes them on a loop instead. The cache entries hold for a day and
this runs far more often than that, so an expiry is refilled here rather than in
front of a request.

⚠️ In-process, like the cache it fills. A restart empties both, and a second
worker would keep its own copy. A shared store (Redis, or a table the scrape
writes) is what removes those two limits; this is the part that needs no new
infrastructure.
"""
import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.tenant import Tenant
from app.dependencies import Pagination
from app.services import (
    ads_service,
    analytics_service,
    competition_service,
    inventory_service,
    overview_service,
    po_service,
    reference_service,
)
from app.utils.logger import logger

# The window the date picker opens on. Anything else stays on demand — warming
# every preset would spend most of its work on windows nobody opened.
DEFAULT_DAYS = 30
# Yesterday at a glance reads its own shorter window and then ONE day out of it,
# so warming the picker's window alone leaves every call that block makes cold.
# Mirrors RECENT_DAYS in the Overview's hooks.
GLANCE_DAYS = 15
INTERVAL_S = 30 * 60


def _window(days: int = DEFAULT_DAYS) -> tuple[date, date, date, date]:
    """The same arithmetic as `get_period`, which the routes use. It has to
    match exactly: a window off by a day is a different cache key and warms
    nothing."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    length = (end - start).days + 1
    return start, end, start - timedelta(days=length), start - timedelta(days=1)


async def warm_once() -> None:
    """One pass over every tenant. Failures are logged and skipped — a warm-up
    that raises must never take the API down with it."""
    start, end, prev_start, prev_end = _window()

    async with AsyncSessionLocal() as session:
        tenants = (await session.execute(select(Tenant.id, Tenant.name))).all()
        marketplaces = [
            mp["slug"]
            for mp in await reference_service.list_marketplaces(session)
            if mp["connected"]
        ]

    for tenant_id, name in tenants:
        window = dict(tenant_id=tenant_id, start=start, end=end)
        prev = dict(prev_start=prev_start, prev_end=prev_end)
        jobs = [
            ("breakdown", lambda s: overview_service.get_marketplace_breakdown(s, **window, **prev)),
            ("mp trends", lambda s: overview_service.get_marketplace_trends(s, **window, marketplaces=marketplaces)),
            ("trends", lambda s: analytics_service.get_trends(s, **window, marketplaces=marketplaces)),
            ("overview", lambda s: analytics_service.get_overview(s, **window, **prev, marketplaces=marketplaces)),
            ("po", lambda s: po_service.insights_by_marketplace(s, **window, **prev, marketplaces=marketplaces)),
            ("reach", lambda s: inventory_service.get_distribution_by_marketplace(s, **window, marketplaces=marketplaces)),
            ("distribution", lambda s: inventory_service.get_distribution(s, **window, marketplaces=marketplaces)),
            ("sov", lambda s: competition_service.get_share_of_voice(s, **window, marketplaces=marketplaces)),
            ("competitors", lambda s: competition_service.get_top_competitors_by_marketplace(s, **window, marketplaces=marketplaces)),
            ("price", lambda s: competition_service.get_price_position(s, **window, marketplaces=marketplaces, by_marketplace=True)),
        ]
        for label, job in jobs:
            try:
                # One session per read, released before the next: this runs for
                # minutes and must not hold a pooled connection throughout.
                async with AsyncSessionLocal() as session:
                    await job(session)
            except Exception as exc:  # noqa: BLE001 - never fail the API
                logger.warning(f"cache warm-up: {name} {label} failed: {exc}")
            # Yield between reads. Back to back across every tenant this is
            # enough load to have the database cancel statements, including
            # the ones a reader is waiting on.
            await asyncio.sleep(settings.WARM_CACHE_GAP_S)

        try:
            await _warm_glance(tenant_id, marketplaces)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cache warm-up: {name} glance failed: {exc}")


async def _warm_glance(tenant_id, marketplaces: list[str]) -> None:
    """The day block: its own lookback, then the one day it settles on.

    Which day that is comes out of the series itself — the latest with complete
    sales — so this has to read the series first and then warm the day, exactly
    as the page does.
    """
    g_end = date.today()
    g_start = g_end - timedelta(days=GLANCE_DAYS - 1)

    async with AsyncSessionLocal() as session:
        rows = await analytics_service.get_trends(
            session,
            tenant_id=tenant_id,
            start=g_start,
            end=g_end,
            marketplaces=marketplaces,
        )

    sold = [r for r in rows if r.get("revenue") is not None]
    if not sold:
        return
    latest = sold[-1]
    i = next(n for n, r in enumerate(rows) if r["date"] == latest["date"])
    # The same day last week, which is what the tiles compare against. Without
    # seven days behind it there is no baseline, and the breakdown takes a
    # window rather than None — so there is nothing to warm yet.
    if i < 7:
        return
    baseline = rows[i - 7]["date"]

    async with AsyncSessionLocal() as session:
        await overview_service.get_marketplace_breakdown(
            session,
            tenant_id=tenant_id,
            start=latest["date"],
            end=latest["date"],
            prev_start=baseline,
            prev_end=baseline,
            include_market=False,
        )

    async with AsyncSessionLocal() as session:
        await ads_service.get_campaigns(
            session,
            tenant_id=tenant_id,
            pagination=Pagination(page=1, limit=50),
            start=latest["date"],
            end=latest["date"],
            marketplaces=marketplaces,
            sort="sales",
            order="desc",
            recent_only=True,
        )


async def warm_forever() -> None:
    while True:
        try:
            await warm_once()
            logger.info("cache warm-up: pass complete")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cache warm-up: pass failed: {exc}")
        await asyncio.sleep(INTERVAL_S)
