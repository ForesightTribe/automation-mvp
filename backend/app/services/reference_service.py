"""Global reference data for frontend filter dropdowns (bounded, fetch-all)."""
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.brand import Brand, Marketplace
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
