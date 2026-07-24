"""Direct HTTP client for Blinkit adservice — no Playwright required.

Extracts the Firebase refresh token from the stored Playwright session's IndexedDB
data, refreshes it via Firebase REST API, then calls Blinkit adservice directly.
This avoids launching a browser entirely, which lets keywords/products load fast
even on Render's free tier (where Playwright times out navigating to Blinkit).
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
BASE_URL = "https://brands.blinkit.com"
_FIREBASE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"


def _extract_firebase_creds(storage_state: dict) -> tuple[str, str] | tuple[None, None]:
    """Return (firebase_api_key, refresh_token) from stored IndexedDB data."""
    for item in storage_state.get("indexedDB", []):
        key = item.get("fbase_key", "")
        prefix = "firebase:authUser:"
        suffix = ":[DEFAULT]"
        if key.startswith(prefix) and key.endswith(suffix):
            api_key = key[len(prefix):-len(suffix)]
            stm = item.get("value", {}).get("stsTokenManager", {})
            rt = stm.get("refreshToken")
            if api_key and rt:
                return api_key, rt
    return None, None


async def get_firebase_token(storage_state: dict) -> str:
    """Exchange the stored refresh token for a fresh Firebase ID token."""
    api_key, refresh_token = _extract_firebase_creds(storage_state)
    if not api_key or not refresh_token:
        raise RuntimeError(
            "No Firebase credentials in session. "
            "Please reconnect Blinkit from the Campaign Manager page."
        )
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(
            _FIREBASE_TOKEN_URL,
            params={"key": api_key},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
    return resp.json()["id_token"]


def _session_cookies(storage_state: dict) -> dict[str, str]:
    """Extract cookies for brands.blinkit.com from Playwright storage state."""
    out: dict[str, str] = {}
    for c in storage_state.get("cookies", []):
        domain = c.get("domain", "")
        if "blinkit.com" in domain:
            out[c["name"]] = c["value"]
    return out


def _auth_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "firebase_user_token": token,
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/dashboard",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }


def _date_range(days: int = 7) -> tuple[str, str]:
    today = datetime.now(_IST)
    start = today - timedelta(days=days)
    fmt = lambda d: f"{d.month}/{d.day}/{d.year}"
    return fmt(start), fmt(today)


async def get_campaign_keywords(campaign_id: int, storage_state: dict) -> list[dict]:
    """Return keywords with CPM + position/impressions — no browser."""
    token = await get_firebase_token(storage_state)
    headers = _auth_headers(token)
    cookies = _session_cookies(storage_state)

    async with httpx.AsyncClient(timeout=30, base_url=BASE_URL, cookies=cookies) as http:
        detail_resp = await http.get(
            f"/adservice/v1/campaigns/{campaign_id}",
            headers=headers,
        )
        detail_resp.raise_for_status()
        campaign = detail_resp.json().get("data", {}).get("campaign", {})
        raw_keywords = campaign.get("keywords", [])

        if not raw_keywords:
            log.info("[direct] no keywords for campaign %s", campaign_id)
            return []

        from_date, to_date = _date_range(days=7)
        report_resp = await http.post(
            f"/adservice/v1/campaigns/reports/{campaign_id}",
            json={"from_date": from_date, "to_date": to_date},
            headers=headers,
        )
        report_resp.raise_for_status()
        report_resp.raise_for_status()
        reporting = report_resp.json().get("data", {}).get("reporting", {})

    report_map: dict[str, dict] = {}
    for entries in reporting.values():
        if isinstance(entries, list):
            for r in entries:
                kw = r.get("keyword", "")
                if kw:
                    report_map[kw] = r

    result = []
    for kw in raw_keywords:
        kw_name = kw.get("keyword", "")
        bids = kw.get("bids", [])
        current_cpm = bids[0].get("cpm", 0) if bids else 0
        match_type = bids[0].get("match_type", "EXACT") if bids else "EXACT"
        row = report_map.get(kw_name, {})
        result.append({
            "keyword": kw_name,
            "match_type": match_type,
            "current_cpm": current_cpm,
            "position": row.get("most_viewed_position"),
            "impressions": row.get("impressions", 0),
        })

    return sorted(result, key=lambda x: (x["position"] is None, x["position"] or 999))


async def get_campaign_products(campaign_id: int, storage_state: dict) -> list[dict]:
    """Return products in a campaign — no browser."""
    token = await get_firebase_token(storage_state)
    cookies = _session_cookies(storage_state)

    async with httpx.AsyncClient(timeout=30, base_url=BASE_URL, cookies=cookies) as http:
        resp = await http.get(
            f"/adservice/v1/campaigns/{campaign_id}",
            headers=_auth_headers(token),
        )
        resp.raise_for_status()
        detail = resp.json().get("data", {}).get("campaign", {})

    raw_products = detail.get("products", [])
    result = []
    for p in raw_products:
        pid = p.get("pid") or p.get("id") or p.get("product_id") or p.get("sku_id")
        name = (p.get("name") or p.get("product_name") or "").strip()
        brand = (p.get("brand") or p.get("brand_name") or "").strip()
        if not brand and name:
            brand = name.split()[0]
        if pid and name:
            result.append({"pid": str(pid), "name": name, "brand": brand})

    if result:
        return result

    # Fallback: return PIDs from pids / highlighted_pids / campaign_data.pids
    for key in ("pids", "highlighted_pids"):
        val = detail.get(key)
        if isinstance(val, str) and val:
            pids = [p.strip() for p in val.split(",") if p.strip()]
            if pids:
                log.info("[direct] %d pid-only fallbacks for campaign %s", len(pids), campaign_id)
                return [{"pid": pid, "name": f"Product (ID: {pid})", "brand": ""} for pid in pids]
        if isinstance(val, list) and val:
            return [{"pid": str(p), "name": f"Product (ID: {p})", "brand": ""} for p in val if p]

    inner_pids = (detail.get("campaign_data") or {}).get("pids")
    if isinstance(inner_pids, list) and inner_pids:
        return [{"pid": str(p), "name": f"Product (ID: {p})", "brand": ""} for p in inner_pids if p]

    log.warning("[direct] no products found for campaign %s", campaign_id)
    return []
