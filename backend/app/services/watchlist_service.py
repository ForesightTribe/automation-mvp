"""Per-client watchlist: which brands (own + competitors) and which
keywords/cities/marketplaces to track. Drives the public-data scrape set and
the client-scoped view of competition data."""
import uuid
from app.utils.time import now_ist

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand import Brand
from app.models.tenant import TenantWatchlist
from app.schemas.watchlist import WatchlistCreate, WatchlistUpdate


async def list_watchlist(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[TenantWatchlist]:
    return (
        await session.execute(
            select(TenantWatchlist)
            .where(TenantWatchlist.tenant_id == tenant_id)
            .order_by(TenantWatchlist.created_at)
        )
    ).scalars().all()


async def get_brands_by_relationship(
    session: AsyncSession, tenant_id: uuid.UUID, relationship: str
) -> list[str]:
    """The watchlist brands of a given relationship ('own' | 'competitor').
    Used to scope the client's view of public competition data."""
    return list(
        (
            await session.execute(
                select(TenantWatchlist.brand_slug).where(
                    TenantWatchlist.tenant_id == tenant_id,
                    TenantWatchlist.relationship == relationship,
                )
            )
        ).scalars().all()
    )


async def brand_exists(session: AsyncSession, slug: str) -> bool:
    return (
        await session.execute(select(Brand.slug).where(Brand.slug == slug))
    ).scalar_one_or_none() is not None


async def create_entry(
    session: AsyncSession, *, tenant_id: uuid.UUID, data: WatchlistCreate
) -> TenantWatchlist:
    entry = TenantWatchlist(
        tenant_id=tenant_id,
        brand_slug=data.brand_slug,
        relationship=data.relationship,
        cities=data.cities,
        keywords=data.keywords,
        marketplaces=data.marketplaces,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def get_entry_for_client(
    session: AsyncSession, *, entry_id: int, tenant_id: uuid.UUID
) -> TenantWatchlist | None:
    entry = await session.get(TenantWatchlist, entry_id)
    if not entry or entry.tenant_id != tenant_id:
        return None
    return entry


async def update_entry(
    session: AsyncSession, *, entry: TenantWatchlist, data: WatchlistUpdate
) -> TenantWatchlist:
    if data.relationship is not None:
        entry.relationship = data.relationship
    if data.cities is not None:
        entry.cities = data.cities
    if data.keywords is not None:
        entry.keywords = data.keywords
    if data.marketplaces is not None:
        entry.marketplaces = data.marketplaces
    entry.updated_at = now_ist()
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def delete_entry(session: AsyncSession, *, entry: TenantWatchlist) -> None:
    await session.delete(entry)
    await session.commit()
