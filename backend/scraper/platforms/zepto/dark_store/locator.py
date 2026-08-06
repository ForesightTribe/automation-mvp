import asyncio
import itertools
import uuid

from .endpoints import (
    BFF_BASE,
    AUTOCOMPLETE_PATH,
    PLACE_DETAILS_PATH,
    STORE_PAGE_PATH,
    STORE_PAGE_PARAMS,
)


def make_grid(lat_min, lat_max, lng_min, lng_max, step_km=1.0):
    step = step_km / 111.0
    lats, lngs = [], []
    lat = lat_min
    while lat <= lat_max:
        lats.append(round(lat, 5))
        lat += step
    lng = lng_min
    while lng <= lng_max:
        lngs.append(round(lng, 5))
        lng += step
    return list(itertools.product(lats, lngs))


async def autocomplete(query: str, ctx, headers: dict) -> list[dict]:
    """Zepto autocomplete → list of {place_id, description}."""
    try:
        r = await ctx.get(
            f"{BFF_BASE}{AUTOCOMPLETE_PATH}",
            params={"place_name": query},
            headers=headers,
            timeout=10_000,
        )
        if r.status != 200:
            return []
        data = await r.json()
        preds = (
            data.get("data", {}).get("predictions")
            or data.get("predictions")
            or []
        )
        return [
            {"place_id": p["place_id"], "description": p.get("description", "")}
            for p in preds
            if p.get("place_id")
        ]
    except Exception:
        return []


async def place_details(place_id: str, ctx, headers: dict) -> dict | None:
    """Resolve a place_id → {lat, lng, pincode, city}."""
    try:
        r = await ctx.get(
            f"{BFF_BASE}{PLACE_DETAILS_PATH}",
            params={"place_id": place_id},
            headers=headers,
            timeout=10_000,
        )
        if r.status != 200:
            return None
        data = await r.json()
        result = (
            data.get("data", {}).get("result")
            or data.get("result")
            or {}
        )
        geo = result.get("geometry", {}).get("location", {})
        lat, lng = geo.get("lat"), geo.get("lng")
        if not lat or not lng:
            return None
        pincode = city = None
        for comp in result.get("address_components", []):
            types = comp.get("types", [])
            if "postal_code" in types:
                pincode = comp.get("long_name")
            if "locality" in types or "administrative_area_level_2" in types:
                city = city or comp.get("long_name")
        return {"lat": lat, "lng": lng, "pincode": pincode, "city": city}
    except Exception:
        return None


async def fetch_store_at(lat: float, lng: float, ctx, headers: dict) -> dict | None:
    """Probe lat/lng → {store_id, secondary_store_ids, probe_lat, probe_lng} or None."""
    rid = str(uuid.uuid4())
    try:
        r = await ctx.get(
            f"{BFF_BASE}{STORE_PAGE_PATH}",
            params={"latitude": lat, "longitude": lng, **STORE_PAGE_PARAMS},
            headers={**headers, "request_id": rid, "requestid": rid},
            timeout=15_000,
        )
        if r.status != 200:
            return None
        data = await r.json()
        svc = data.get("storeServiceableResponse", {})
        store_id = svc.get("storeId")
        if not store_id:
            return None
        return {
            "store_id": str(store_id),
            "secondary_store_ids": [str(s) for s in svc.get("secondaryStoreIds", [])],
            "probe_lat": lat,
            "probe_lng": lng,
        }
    except Exception:
        return None
