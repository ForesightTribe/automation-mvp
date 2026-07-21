"""Global reference data for frontend filter dropdowns (bounded, fetch-all)."""
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.brand import Brand, Marketplace
from app.models.search import MarketplaceLocation
from scraper.utils.cities import CITIES


async def list_brands(session: AsyncSession) -> list[Brand]:
    return (await session.execute(select(Brand).order_by(Brand.name))).scalars().all()


async def list_marketplaces(session: AsyncSession) -> list[dict]:
    """List marketplaces, flagging which have real data (`connected`). Returns
    dicts so the connectivity flag can ride alongside the ORM columns."""
    rows = (
        await session.execute(select(Marketplace).order_by(Marketplace.name))
    ).scalars().all()
    connected = set(settings.CONNECTED_MARKETPLACES)
    return [
        {
            "slug": m.slug,
            "name": m.name,
            "color": m.color,
            "connected": m.slug in connected,
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


async def list_blinkit_zones(session: AsyncSession) -> list[dict]:
    """Return active Blinkit dark store locations from marketplace_locations.
    Falls back to hardcoded CITIES if the table is empty (not yet populated by scraper)."""
    rows = (
        await session.execute(
            select(MarketplaceLocation)
            .where(
                MarketplaceLocation.mp_slug == "blinkit",
                MarketplaceLocation.is_active == True,
                MarketplaceLocation.lat.is_not(None),
                MarketplaceLocation.lon.is_not(None),
            )
            .order_by(MarketplaceLocation.city, MarketplaceLocation.pincode)
        )
    ).scalars().all()

    if rows:
        # Deduplicate: one representative dark store per (city, pincode) pair
        seen: set[str] = set()
        zones = []
        for r in rows:
            area = r.pincode.strip() if r.pincode and r.pincode.strip() else ""
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
