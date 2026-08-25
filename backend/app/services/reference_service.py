"""Global reference data for frontend filter dropdowns (bounded, fetch-all)."""
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand import Brand, Marketplace
from app.models.job import JobStatus, ScrapeJob
from app.models.search import MarketplaceLocation, SearchSnapshot
from scraper.utils.cities import CITIES


async def list_brands(session: AsyncSession) -> list[Brand]:
    return (await session.execute(select(Brand).order_by(Brand.name))).scalars().all()


async def list_marketplaces(session: AsyncSession) -> list[dict]:
    """List marketplaces, flagging which have real data (`connected`) and what
    plane of data they can supply (`data_scope`). Returns dicts so both flags can
    ride alongside the ORM columns.

    Both flags used to be (or risked becoming) a hardcoded config list — brittle,
    because it drifts from the database the moment a marketplace's real
    capability changes without a matching code deploy. Both are derived instead:

    `connected` — is there *any* real scraped row for this marketplace, anywhere.
    This is not client-scoped (see the route's docstring), so it means "some
    tenant has data for it" — the global picker's job is only to decide whether a
    marketplace is selectable at all, not whether the CURRENT client has data for
    it (that's a separate, tenant-scoped check — see
    overview_service.get_marketplace_breakdown).

    `data_scope` — "full" if any successful scrape_jobs row for this platform is
    a PRIVATE job (seller/marketing/scorecard — dashboard values like
    "blinkit_seller_sales", never prefixed "public_"), "public" otherwise. A
    marketplace only gains "full" once real seller-panel data has actually
    landed — never from a hardcoded map someone has to remember to update.
    """
    rows = (
        await session.execute(select(Marketplace).order_by(Marketplace.name))
    ).scalars().all()
    connected = set(
        (await session.execute(select(SearchSnapshot.mp_slug).distinct()))
        .scalars()
        .all()
    )
    full_scope = set(
        (
            await session.execute(
                select(ScrapeJob.platform)
                .where(
                    ScrapeJob.status == JobStatus.success,
                    ~ScrapeJob.dashboard.startswith("public_"),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "slug": m.slug,
            "name": m.name,
            "color": m.color,
            "connected": m.slug in connected,
            "data_scope": "full" if m.slug in full_scope else "public",
        }
        for m in rows
    ]


def list_cities() -> list[dict]:
    """Flatten the hardcoded CITIES dict into city -> per-platform zones."""
    cities = []
    for slug, city in CITIES.items():
        platforms = {
            pname: [
                {"zone": z["zone"], "pincode": z["pincode"]}
                for z in pconf.get("zones", [])
            ]
            for pname, pconf in city.get("platforms", {}).items()
        }
        cities.append(
            {
                "slug": slug,
                "name": city["name"],
                "state": city["state"],
                "platforms": platforms,
            }
        )
    return cities


async def list_blinkit_zones(session: AsyncSession, mp_slug: str = "blinkit") -> list[dict]:
    """Return a marketplace's active dark store locations from marketplace_locations.
    Falls back to hardcoded CITIES if the table is empty (not yet populated by scraper).

    Defaults to Blinkit for the existing route; catalogs are per-marketplace, so the
    caller picks. (The `blinkit` in the name is historical — rename with the route.)
    """
    rows = (
        await session.execute(
            select(MarketplaceLocation)
            .where(
                MarketplaceLocation.mp_slug == mp_slug,
                MarketplaceLocation.is_active == True,
                MarketplaceLocation.lat.is_not(None),
                MarketplaceLocation.lon.is_not(None),
            )
            .order_by(MarketplaceLocation.city, MarketplaceLocation.location_name)
        )
    ).scalars().all()

    if rows:
        # Deduplicate: one representative dark store per (city, area) pair, where area
        # is the store's sub-city name ("Shahganj"), falling back to pincode.
        seen: set[str] = set()
        zones = []
        for r in rows:
            area = (r.location_name.strip() if r.location_name and r.location_name.strip()
                    else (r.pincode.strip() if r.pincode and r.pincode.strip() else ""))
            key = f"{r.city}|{area}"
            if key in seen:
                continue
            seen.add(key)
            label = f"{r.city} — {area}" if area else r.city
            zones.append({
                "label": label,
                "city": r.city,
                "zone": area,
                "state": r.state or "",
                "pincode": area,
                "merchant_id": r.merchant_id or "",
                "lat": r.lat,
                "lon": r.lon,
            })
        return zones

    # Fallback: hardcoded CITIES dict so the dropdown is never empty
    zones = []
    for slug, city in CITIES.items():
        blinkit = city.get("platforms", {}).get("blinkit", {})
        for z in blinkit.get("zones", []):
            zones.append({
                "label": f"{city['name']} — {z['zone']}",
                "city": city["name"],
                "zone": z["zone"],
                "state": city.get("state", ""),
                "pincode": z.get("pincode", ""),
                "merchant_id": "",
                "lat": z["lat"],
                "lon": z["lon"],
            })
    return zones
