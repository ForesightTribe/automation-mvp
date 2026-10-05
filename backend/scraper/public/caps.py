"""Per-marketplace scrape caps — the ONE place they are read (2026-10-02).

A cap is a number of RESULTS, and each marketplace pages differently: Blinkit returns 12 a
page, Zepto 30. So the caps live per (tracked brand, marketplace) in `tenant_watchlist_caps`,
set from the config workbook's `caps` sheet — not on the watchlist row, where one number had
to serve every marketplace (Sereko's Blinkit-shaped 36 on Zepto fetched two 30-row pages and
threw 24 rows away on every search).

Who reads them, and what wins:

    keyword scrape (orchestrator)   CLI --cap        > tenant's keyword_cap here > provider floor
    own-SKU scrape (targeted)       CLI --brand-cap  > brand's brand_cap here    > provider floor
    bid engine's stock check (CM)                      brand's brand_cap here    > CM_STOCK_DEFAULT_BRAND_CAP

Own brands only. A brand with no row for a marketplace simply has no cap there.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.tenant import TenantWatchlist, TenantWatchlistCap


@dataclass(frozen=True)
class Caps:
    keyword_cap: int | None = None
    brand_cap: int | None = None


async def own_caps(db: AsyncSession, tenant_id: uuid.UUID, mp_slug: str) -> dict[str, Caps]:
    """`{brand_slug: Caps}` for the tenant's OWN brands on `mp_slug`, in watchlist order.
    A brand with no caps row for this marketplace is absent."""
    rows = (await db.execute(
        select(TenantWatchlist.brand_slug, TenantWatchlistCap.keyword_cap,
               TenantWatchlistCap.brand_cap)
        .join(TenantWatchlistCap, TenantWatchlistCap.watchlist_id == TenantWatchlist.id)
        .where(TenantWatchlist.tenant_id == tenant_id,
               TenantWatchlist.relationship == "own",
               TenantWatchlistCap.mp_slug == mp_slug)
        .order_by(TenantWatchlist.id)
    )).all()
    return {brand: Caps(kw, br) for brand, kw, br in rows}


def tenant_keyword_cap(caps: dict[str, Caps]) -> int | None:
    """Pure. The keyword scrape runs per TENANT — every own brand's keywords in one pass — so
    it takes one cap: the first own brand (watchlist order) that sets one."""
    for c in caps.values():
        if c.keyword_cap:
            return c.keyword_cap
    return None


def off_page(cap: int | None, page_size: int | None) -> bool:
    """Pure. A cap that is not a whole number of the marketplace's pages fetches a last page
    only to throw part of it away (36 on Zepto = two 30-row pages, 24 rows discarded)."""
    return bool(cap and page_size and cap % page_size)
