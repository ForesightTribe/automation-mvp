import asyncio

import httpx

from app.utils.logger import logger
from scraper.utils.search_result import HEADERS_COMMON

_HEADERS = {
    **HEADERS_COMMON,
    "Referer": "https://www.swiggy.com/instamart/",
}


async def fetch_store(pincode: str) -> dict | None:
    url = f"https://www.swiggy.com/api/v1/instamart/store?pincode={pincode}"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers=_HEADERS)
            if r.status_code == 200:
                data = r.json()
                stores = data if isinstance(data, list) else (data.get("stores") or data.get("data") or [])
                if stores:
                    s = stores[0] if isinstance(stores, list) else stores
                    return {
                        "id": s.get("id") or s.get("store_id"),
                        "name": s.get("name") or s.get("store_name"),
                        "lat": s.get("lat") or s.get("latitude"),
                        "lng": s.get("lng") or s.get("longitude"),
                    }
    except Exception as e:
        logger.warning(f"Instamart store lookup failed for pincode {pincode}: {e}")
    return None


async def fetch_stores(pincodes: list[str]) -> list[dict | None]:
    return list(await asyncio.gather(*[fetch_store(p) for p in pincodes]))
