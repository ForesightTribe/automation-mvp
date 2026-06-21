"""Global reference data for frontend filter dropdowns (bounded, fetch-all)."""
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand import Brand, Marketplace
from scraper.utils.cities import CITIES


async def list_brands(session: AsyncSession) -> list[Brand]:
    return (await session.execute(select(Brand).order_by(Brand.name))).scalars().all()


async def list_marketplaces(session: AsyncSession) -> list[Marketplace]:
    return (
        await session.execute(select(Marketplace).order_by(Marketplace.name))
    ).scalars().all()


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
