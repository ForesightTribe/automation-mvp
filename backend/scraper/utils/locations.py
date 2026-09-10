"""Resolve a city name to a real dark store, from the catalogue.

Replaces `scraper/utils/cities.py` (deleted 2026-09-04), which was a hardcoded
city → zone → lat/lon table written before the darkstore catalogue existed. Its own
docstring described its coordinates as unverified placeholders — "Replace them with
verified dark-store coordinates once your team has the data" — and the data has been
there since the catalogue landed: 2,059 real Blinkit stores and 1,229 Zepto ones,
synced from `config.xlsx` and carrying the merchant ids the responses confirm.

Two sources of truth for "where is Bengaluru" is one too many, and the stale one was
wired into a live API endpoint. This module is the only remaining answer.

Scope note: this is the AD-HOC path — one keyword at one place, for a quick look. The
real runs (`public-run`, `public-skus`, Explorer) already read `marketplace_locations`
directly through their own orchestrators and never went through the old table.
"""
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.search import MarketplaceLocation


async def resolve_city(db: AsyncSession, mp_slug: str, city: str) -> MarketplaceLocation | None:
    """A representative active store for `city` on `mp_slug`, or None.

    Matches the catalogue's own `city` text, case-insensitively — the names a caller
    sees in `city_names()` and in `cli locations list`. Deliberately NOT the canonical
    city registry with its alias resolution: that exists to translate a MARKETPLACE's
    vocabulary into ours (Blinkit's `Gurugram` inside our `hr-ncr`), and here the
    caller is typing our name already.

    ⚠️ "Representative" means `ORDER BY merchant_id LIMIT 1` — the lowest store id in
    the city, which is deterministic but arbitrary. Fine for an ad-hoc look at one
    keyword; NOT fine as a stand-in for a city's performance. The same shortcut in the
    bid engine is a known open question.
    """
    if not city:
        return None
    return (await db.execute(
        select(MarketplaceLocation)
        .where(
            MarketplaceLocation.mp_slug == mp_slug,
            MarketplaceLocation.is_active == True,  # noqa: E712
            MarketplaceLocation.lat.is_not(None),
            MarketplaceLocation.lon.is_not(None),
            func.lower(MarketplaceLocation.city) == city.strip().lower(),
        )
        .order_by(MarketplaceLocation.merchant_id)
        .limit(1)
    )).scalars().first()


async def city_names(db: AsyncSession, mp_slug: str) -> list[str]:
    """Every city this marketplace has an active store in — for an error message that
    tells the caller what they COULD have typed, instead of pointing at a source file
    they then have to read."""
    return list((await db.execute(
        select(MarketplaceLocation.city)
        .where(
            MarketplaceLocation.mp_slug == mp_slug,
            MarketplaceLocation.is_active == True,  # noqa: E712
        )
        .distinct()
        .order_by(MarketplaceLocation.city)
    )).scalars().all())
