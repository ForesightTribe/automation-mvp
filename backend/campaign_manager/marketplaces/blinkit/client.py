"""Blinkit Ad Campaign API client."""
import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

_AD_CAMPAIGNS_DIR = Path(__file__).parent

log = logging.getLogger(__name__)

from playwright.async_api import async_playwright, Page

from app.core.database import AsyncSessionLocal
from platform_auth import service as auth_service
from scraper.utils.browser import create_browser_context

_IST = timezone(timedelta(hours=5, minutes=30))

BASE_URL = "https://brands.blinkit.com"
CAMPAIGNS_PAGE = "/dashboard"
ADVERTISER_ID = 234  # Blinkit account-specific — update if account changes

# Fallback only. Blinkit 400s the WHOLE request if it is sent a type the advertiser does
# not have enabled ("[...] are not enabled for given advertiser") and `_fetch` turns that
# into `{}` — so sending this list blindly yields a silently empty campaign list. Read the
# live set from CAMPAIGN_CONFIG_API instead; this is only the last resort if that fails.
ALL_CAMPAIGN_TYPES = [
    "PRODUCT_LISTING", "PRODUCT_RECOMMENDATION", "SEARCH_SUGGESTION",
    "SHELF_DIY", "STORY_DIY", "BANNER_DIY", "BRAND_SPOTLIGHT_DIY",
    "BANNER_LISTING", "BRAND_BOOSTER",
]

# Publishes the campaign (asset) types enabled for the logged-in advertiser, grouped under
# objective_types[].asset_types — the same call the dashboard itself makes.
CAMPAIGN_CONFIG_API = "/adservice/v2/campaigns/config"


def _decode_email(token: str) -> str:
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.b64decode(payload)).get("email", "")
    except Exception:
        return ""


def _date_range(days: int = 90):
    today = datetime.now(_IST)
    start = today - timedelta(days=days)
    return f"{start.month}/{start.day}/{start.year}", f"{today.month}/{today.day}/{today.year}"


def _fmt_date(ts: str) -> str:
    """Convert ISO timestamp to M/D/YYYY for PUT payload.
    Year 9999 = infinite campaign → return '12/31/9999' (Blinkit requires this, not empty string)."""
    if not ts:
        return ""
    try:
        ts_clean = ts.replace("+00:00", "").replace("Z", "")
        d = datetime.fromisoformat(ts_clean)
        return f"{d.month}/{d.day}/{d.year}"
    except Exception:
        return ts


async def _inject_firebase_idb(context, idb_data: list) -> None:
    idb_json = json.dumps(idb_data)
    await context.add_init_script(f"""(function(){{
        var D={idb_json};
        if(!D||!D.length)return;
        var r=indexedDB.open('firebaseLocalStorageDb',1);
        r.onupgradeneeded=function(e){{
            var db=e.target.result;
            if(!db.objectStoreNames.contains('firebaseLocalStorage'))
                db.createObjectStore('firebaseLocalStorage',{{keyPath:'fbase_key'}});
        }};
        r.onsuccess=function(e){{
            var db=e.target.result;
            var tx=db.transaction('firebaseLocalStorage','readwrite');
            var store=tx.objectStore('firebaseLocalStorage');
            D.forEach(function(item){{store.put(item);}});
        }};
    }})();""")


class BlinkitClient:
    def __init__(self, page: Page, token: str):
        self._page = page
        self._token = token
        self._email = _decode_email(token)

    async def _fetch(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{BASE_URL}{path}"
        # GET/HEAD cannot have a body — move params to query string
        if method in ("GET", "HEAD") and body:
            url = f"{url}?{urlencode(body)}"
            body = None
        return await self._page.evaluate(
            """async ([method, url, fallback_token, body]) => {
                // Use Firebase SDK's live token if available — avoids stale stored token
                let token = fallback_token;
                try {
                    const auth = window.firebase && window.firebase.auth && window.firebase.auth();
                    if (auth && auth.currentUser) {
                        const t = await auth.currentUser.getIdToken(false);
                        if (t) token = t;
                    }
                } catch(e) {}
                const resp = await fetch(url, {
                    method,
                    headers: {
                        'content-type': 'application/json',
                        'firebase_user_token': token
                    },
                    body: body ? JSON.stringify(body) : null
                });
                const text = await resp.text();
                try { return JSON.parse(text); } catch(e) { return {}; }
            }""",
            [method, url, self._token, body],
        )

    async def get_enabled_campaign_types(self) -> list[str]:
        """Campaign types enabled for this advertiser, read from the config call the
        dashboard makes. Never send the full hardcoded list when this succeeds — Blinkit
        rejects the entire request if one type is disabled (see ALL_CAMPAIGN_TYPES)."""
        resp = await self._fetch("GET", CAMPAIGN_CONFIG_API)
        objectives = (resp.get("data") or {}).get("objective_types") or []
        types = sorted({t for o in objectives for t in (o.get("asset_types") or [])})
        if not types:
            log.warning("[get_enabled_campaign_types] could not read enabled types — "
                        "falling back to all %d; expect an empty list if any is disabled.",
                        len(ALL_CAMPAIGN_TYPES))
            return ALL_CAMPAIGN_TYPES
        return types

    async def get_campaigns(self, days: int = 90) -> list[dict]:
        from_date, to_date = _date_range(days)
        resp = await self._fetch("POST", "/adservice/v1/advertisers/campaigns", {
            "from_date": from_date,
            "to_date": to_date,
            "campaign_types": await self.get_enabled_campaign_types(),
        })
        data = resp.get("data", {})
        if isinstance(data, dict):
            log.debug("[get_campaigns] data keys=%s advertiser_id=%r",
                        list(data.keys()), data.get("advertiser_id"))
        return data.get("campaigns", []) if isinstance(data, dict) else []

    async def get_campaign_detail(self, campaign_id: int) -> tuple[dict, dict]:
        """Returns (campaign_detail, min_cpm_config)."""
        resp = await self._fetch("GET", f"/adservice/v1/campaigns/{campaign_id}")
        data = resp.get("data", {})
        return data.get("campaign", {}), data.get("min_cpm_config", {})

    async def get_campaign_report(self, campaign_id: int, days: int = 7) -> list[dict]:
        """Returns keyword-level report rows with most_viewed_position and cpm."""
        from_date, to_date = _date_range(days)
        resp = await self._fetch(
            "POST",
            f"/adservice/v1/campaigns/reports/{campaign_id}",
            {"from_date": from_date, "to_date": to_date},
        )
        reporting = resp.get("data", {}).get("reporting", {})
        # Flatten all groups (keyword, product_recommendation, etc.) into one list
        rows = []
        for entries in reporting.values():
            if isinstance(entries, list):
                rows.extend(entries)
        return rows

    async def get_campaign_keywords(self, campaign_id: int, days: int = 7) -> list[dict]:
        """Returns keyword list with current CPM bid and position/impressions over last 7 days."""
        detail, _ = await self.get_campaign_detail(campaign_id)
        report = await self.get_campaign_report(campaign_id, days=days)

        report_map = {r.get("keyword", ""): r for r in report}

        raw_keywords = detail.get("keywords", [])

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

    async def get_campaign_products(self, campaign_id: int) -> list[dict]:
        """Returns products in the campaign with pid, name, and brand.

        Tries in order:
        1. API response detail["products"] — if it has names
        2. Network interception — captures the catalog call the campaign page makes internally
        """
        detail, _ = await self.get_campaign_detail(campaign_id)
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

        # Intercept network responses the campaign page fires (finds the catalog lookup call)
        log.debug("[get_campaign_products] intercepting network for campaign page %s", campaign_id)
        captured: list[dict] = []

        async def _on_response(response):
            url = response.url
            if not any(x in url for x in ["catalogue", "products", "catalog", "sku", "inventory"]):
                return
            try:
                data = await response.json()
                log.debug("[get_campaign_products] captured url=%s keys=%s", url, list(data.keys()) if isinstance(data, dict) else type(data))
                items = (
                    (data.get("data") or {}).get("products")
                    or (data.get("data") or {}).get("items")
                    or data.get("products")
                    or data.get("items")
                    or []
                )
                for p in items:
                    pid = p.get("pid") or p.get("id") or p.get("sku_id") or ""
                    name = (p.get("name") or p.get("product_name") or "").strip()
                    brand = (p.get("brand") or p.get("brand_name") or "").strip()
                    if name:
                        captured.append({
                            "pid": str(pid),
                            "name": name,
                            "brand": brand or (name.split()[0] if name else ""),
                        })
            except Exception:
                pass

        self._page.on("response", _on_response)
        try:
            await self._page.goto(
                f"{BASE_URL}/diy/campaign/{campaign_id}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            await self._page.wait_for_timeout(2000)
        finally:
            self._page.remove_listener("response", _on_response)

        if captured:
            log.debug("[get_campaign_products] captured %d products via network interception", len(captured))
            return captured

        # Last resort: return PIDs from detail so UI at least shows something
        def _pids_from_detail(d: dict) -> list[str]:
            for key in ("pids", "highlighted_pids"):
                val = d.get(key)
                if isinstance(val, list) and val:
                    return [str(p) for p in val if p]
                if isinstance(val, str) and val:
                    return [p.strip() for p in val.split(",") if p.strip()]
            inner = (d.get("campaign_data") or {}).get("pids")
            if isinstance(inner, list) and inner:
                return [str(p) for p in inner if p]
            return []

        fallback_pids = _pids_from_detail(detail)
        if fallback_pids:
            log.debug("[get_campaign_products] returning %d pid-only fallbacks for campaign %s", len(fallback_pids), campaign_id)
            return [{"pid": pid, "name": f"Product (ID: {pid})", "brand": ""} for pid in fallback_pids]

        log.warning("[get_campaign_products] no products found for campaign %s", campaign_id)
        return []

    async def update_keyword_bids(self, campaign_id: int, keyword_updates: list[dict],
                                  *, advertiser_id: int | None = None) -> dict:
        """
        Update CPM bids for specific keywords.
        keyword_updates: [{"keyword": "mojito", "match_type": "EXACT", "cpm": 400}]

        advertiser_id: optional explicit account override (campaign-manager v2 passes the
        per-tenant stored id here). Falls back to get_advertiser_id() when None.
        """
        detail, min_cpm_config = await self.get_campaign_detail(campaign_id)
        if not detail:
            raise RuntimeError(f"Could not fetch details for campaign {campaign_id}")

        repeat_order = detail.get("repeat_order_suggestion") or {}
        if not repeat_order.get("bidding_strategy"):
            min_cpm = min_cpm_config.get(detail.get("campaign_type", ""), 500)
            repeat_order = {"bidding_strategy": {"cpm": min_cpm}}

        # pids: try pids → highlighted_pids → campaign_data.pids → products
        def _extract_pids(val):
            if not val:
                return ""
            if isinstance(val, str):
                return val
            return ",".join(str(p) for p in val if p)

        pids_str = (
            _extract_pids(detail.get("pids"))
            or _extract_pids(detail.get("highlighted_pids"))
            or _extract_pids((detail.get("campaign_data") or {}).get("pids"))
            or _extract_pids([
                p.get("pid") or p.get("id") or p.get("sku_id")
                for p in detail.get("products", [])
                if p.get("pid") or p.get("id") or p.get("sku_id")
            ])
        )

        # Ensure products list has 'pid' key for PUT validator
        raw_products_kw = detail.get("products", [])
        products_for_put_kw = []
        for p in raw_products_kw:
            pid_val = p.get("pid") or p.get("id") or p.get("product_id") or p.get("sku_id")
            if pid_val and not p.get("pid"):
                products_for_put_kw.append({**p, "pid": int(pid_val)})
            else:
                products_for_put_kw.append(p)

        # Build minimal product dicts from pids_str if products list is empty
        if not products_for_put_kw and pids_str:
            products_for_put_kw = [{"pid": int(p)} for p in pids_str.split(",") if p]

        # True no-product campaign — do not send products/pids in payload at all
        # (sending products:[] triggers Blinkit's "Please select atleast one PID" validation)
        has_products = bool(pids_str) or bool(products_for_put_kw)

        actual_advertiser_id = advertiser_id if advertiser_id is not None else await self.get_advertiser_id()

        # Build update map: keyword → {cpm, match_type}
        update_map = {u["keyword"]: u for u in keyword_updates}

        # Preserve ALL existing keywords — only update CPM for the ones in update_map.
        # Sending only updated keywords in the PUT replaces the entire keyword list.
        existing_kws = (
            detail.get("campaign_targeting") or {}
        ).get("keyword_targeting", {}).get("keywords", [])
        # Blinkit API returns keywords at top-level too — use as fallback
        if not existing_kws:
            existing_kws = detail.get("keywords", [])

        merged_keywords = []
        updated_names = set()
        for kw in existing_kws:
            kw_name = kw.get("keyword", "")
            if kw_name in update_map:
                upd = update_map[kw_name]
                bids = kw.get("bids", [{"match_type": "EXACT", "cpm": 0, "max_boost": None}])
                new_bids = [{**b, "cpm": int(upd["cpm"])} for b in bids]
                merged_keywords.append({**kw, "bids": new_bids})
                updated_names.add(kw_name)
            else:
                merged_keywords.append(kw)

        # Add any keywords from update_map not already in existing list
        for kw_name, upd in update_map.items():
            if kw_name not in updated_names:
                merged_keywords.append({
                    "keyword": kw_name,
                    "bids": [{"match_type": upd.get("match_type", "EXACT"), "cpm": int(upd["cpm"]), "max_boost": None}],
                })

        kw_targeting = {"keywords": merged_keywords}

        # If campaign has no products at all, Blinkit blocks bid updates even from their own dashboard.
        if not has_products:
            raise RuntimeError(
                "This campaign has no products (PIDs). Blinkit requires at least one product "
                "to update keyword bids — even their own dashboard shows this error. "
                "Fix: open this campaign in the Blinkit Ads dashboard and add at least one product."
            )

        # Build payload matching exactly what Blinkit's own dashboard sends (captured from network).
        # Key points:
        #   - highlighted_pids = pids_str (not "")
        #   - campaign_data includes brand_ids, category_ids, ro_details (not just pids)
        #   - products field is NOT sent (Blinkit doesn't include it)
        existing_campaign_data = detail.get("campaign_data") or {}
        payload = {
            "source_platform": "diy_dashboard_web",
            "requested_by": self._email,
            "advertiser_id": actual_advertiser_id,
            "campaign_request_type": "UPDATE",
            "campaign_id": campaign_id,
            "asset_type": detail.get("campaign_type", ""),
            "name": detail.get("name", ""),
            "infinite_campaign": detail.get("infinite_campaign", False),
            "campaign_start": _fmt_date(detail.get("start_ts", "")),
            "campaign_end": _fmt_date(detail.get("end_ts", "")),
            "objective_type": detail.get("objective_type", "PERFORMANCE"),
            "brand_ids": detail.get("brand_ids", ""),
            "brand_name": detail.get("brand_name", ""),
            "brand_page_id": detail.get("brand_page_id") or "",
            "collection_id": detail.get("collection_id", ""),
            "cpm": detail.get("cpm", 0),
            "creative_type": detail.get("creative_type", ""),
            "header_title": detail.get("header_title", ""),
            "highlighted_pids": pids_str,
            "image_url": detail.get("mobile_image_url", ""),
            "is_extendable": None,
            "store_name": detail.get("store_name", ""),
            "pids": pids_str,
            "campaign_data": {
                "pids": pids_str,
                "brand_ids": existing_campaign_data.get("brand_ids", ""),
                "category_ids": existing_campaign_data.get("category_ids"),
                "ro_details": existing_campaign_data.get("ro_details") or {
                    "ro_issue_date": None,
                    "proof_url": None,
                },
            },
            "bidding_strategy": {
                "total_budget": detail.get("campaign_budget", 0),
                "pacing_type": detail.get("pacing_type", "DAILY"),
            },
            "campaign_targeting": {
                "city_ids": "-1",
                "is_extendable": False,
                "negative_keywords": detail.get("negative_keywords") or [],
                "repeat_order_suggestion": repeat_order,
                "keyword_targeting": kw_targeting,
            },
        }

        resp = await self._fetch("PUT", "/adservice/v3/campaigns", payload)
        if resp.get("status") or resp.get("success"):
            return resp

        msg = resp.get("message") or resp
        raise RuntimeError(f"Blinkit bid update failed: {msg}")

    async def get_advertiser_id(self) -> int:
        """Fetch the real advertiser_id for this account from Blinkit's API."""
        from_date, to_date = _date_range(1)
        resp = await self._fetch("POST", "/adservice/v1/advertisers/campaigns", {
            "from_date": from_date,
            "to_date": to_date,
            "campaign_types": ["PRODUCT_LISTING"],
        })
        adv_id = resp.get("data", {}).get("advertiser_id", ADVERTISER_ID)
        log.debug("[get_advertiser_id] advertiser_id=%r (hardcoded=%r)", adv_id, ADVERTISER_ID)
        return adv_id

    async def update_campaign(self, campaign_id: int, changes: dict, *, empty_pids: bool = False,
                              advertiser_id: int | None = None) -> dict:
        """Minimal PUT payload for campaign updates (e.g. budget).
        empty_pids=True skips product/pids validation — use when catalog PIDs are delisted.
        advertiser_id: optional explicit account override (campaign-manager v2 passes the
        per-tenant stored id here). Falls back to get_advertiser_id() when None."""
        actual_advertiser_id = advertiser_id if advertiser_id is not None else await self.get_advertiser_id()
        detail, min_cpm_config = await self.get_campaign_detail(campaign_id)
        if not detail:
            raise RuntimeError(f"Could not fetch details for campaign {campaign_id}")

        raw_pids = detail.get("pids", [])
        if isinstance(raw_pids, str):
            pids_str = raw_pids
        elif raw_pids:
            pids_str = ",".join(str(p) for p in raw_pids)
        else:
            pids_str = ",".join(
                str(p.get("id") or p.get("pid"))
                for p in detail.get("products", [])
                if p.get("id") or p.get("pid")
            )

        repeat_order = detail.get("repeat_order_suggestion") or {}
        if not repeat_order.get("bidding_strategy"):
            min_cpm = min_cpm_config.get(detail.get("campaign_type", ""), 500)
            repeat_order = {"bidding_strategy": {"cpm": min_cpm}}

        existing_kws = detail.get("keywords", [])
        raw_products = detail.get("products", [])

        # Ensure products have 'pid' key — Blinkit PUT validator checks products[i].pid
        products_for_put = []
        for p in raw_products:
            pid_val = p.get("pid") or p.get("id") or p.get("product_id") or p.get("sku_id")
            if pid_val and not p.get("pid"):
                products_for_put.append({**p, "pid": int(pid_val)})
            else:
                products_for_put.append(p)

        def _norm_bids(bids: list) -> list:
            result = []
            for b in bids:
                match = b.get("match_type", "EXACT")
                if match == "EXACT_MATCH":
                    match = "EXACT"
                result.append({"match_type": match, "cpm": int(b.get("cpm", 0)), "max_boost": None})
            return result

        # Build region_ids for campaign_targeting.city_ids
        region_ids_raw = detail.get("region_ids")
        if isinstance(region_ids_raw, list):
            city_ids_str = ",".join(str(r) for r in region_ids_raw) if region_ids_raw else "-1"
        elif region_ids_raw is not None:
            city_ids_str = str(region_ids_raw)
        else:
            city_ids_str = "-1"

        campaign_type = detail.get("campaign_type", "")

        # campaign_data structure matches what the Blinkit frontend actually sends.
        # For BANNER_LISTING: no image URL fields — any image field in campaign_data
        # triggers the "Cannot change listing spotlight image" validator even when
        # the value is unchanged. The working frontend sends exactly these 3 fields.
        # highlighted_pids must be "" (string), not [] (list).
        # For all other types: original structure that was working before.
        if campaign_type == "BANNER_LISTING":
            campaign_data_payload = {
                "creative_type": "",
                "collection_id": detail.get("collection_id", ""),
                "highlighted_pids": "",
            }
        else:
            # Blinkit validates campaign_data.pids for product campaigns (confirmed
            # from DevTools capture of working frontend PUT request).
            campaign_data_payload = {
                "creative_type": detail.get("creative_type", ""),
                "collection_id": detail.get("collection_id", ""),
                "pids": "" if empty_pids else pids_str,
            }

        payload = {
            "source_platform": "diy_dashboard_web",
            "requested_by": self._email,
            "advertiser_id": actual_advertiser_id,
            "campaign_request_type": "UPDATE",
            "campaign_id": campaign_id,
            "asset_type": campaign_type,
            "name": detail.get("name", ""),
            "infinite_campaign": detail.get("infinite_campaign", False),
            "campaign_start": _fmt_date(detail.get("start_ts", "")),
            "campaign_end": _fmt_date(detail.get("end_ts", "")),
            "objective_type": detail.get("objective_type", "PERFORMANCE"),
            "pids": "" if empty_pids else pids_str,
            "brand_ids": detail.get("brand_ids", ""),
            "brand_name": detail.get("brand_name", ""),
            "cpm": detail.get("cpm", 0),
            "header_title": detail.get("header_title", ""),
            "is_extendable": None,
            "bidding_strategy": {
                "total_budget": detail.get("campaign_budget", 0),
                "pacing_type": detail.get("pacing_type", "DAILY"),
            },
            "campaign_targeting": {
                "city_ids": city_ids_str,
                "is_extendable": False,
                "negative_keywords": detail.get("negative_keywords") or [],
                **({"keyword_targeting": {"keywords": [
                    {"keyword": k.get("keyword", ""), "bids": _norm_bids(k.get("bids", []))}
                    for k in existing_kws
                ]}} if existing_kws else {}),
            },
            "campaign_data": campaign_data_payload,
        }

        payload.update(changes)
        log.debug("[update_campaign] campaign=%d pids=%r empty_pids=%s budget=%s",
                    campaign_id, "" if empty_pids else pids_str, empty_pids,
                    payload.get("bidding_strategy", {}).get("total_budget"))
        if campaign_type == "BANNER_LISTING":
            log.debug("[update_campaign] FULL PAYLOAD=%s", json.dumps(payload, default=str))
        resp = await self._fetch("PUT", "/adservice/v3/campaigns", payload)
        log.debug("[update_campaign] RESP=%r", resp)
        return resp

    async def update_campaign_budget_via_ui(self, campaign_id: int, budget: float) -> dict:
        """
        On the Blinkit campaign list page, find the campaign row, open its edit
        panel, fill the budget, and click Update. Intercepts the PUT to capture
        Blinkit's own payload format (guaranteed correct).
        """
        result: dict = {}

        async def _handle(route):
            # Only intercept PUT (campaign update), let POST (create) pass through
            if route.request.method != "PUT":
                await route.continue_()
                return
            req = route.request
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:
                body = {}
            log.warning("[blinkit_ui] intercepted PUT — pids=%r products_count=%d",
                        body.get("pids"), len(body.get("products", [])))
            body.setdefault("bidding_strategy", {})["total_budget"] = float(budget)
            try:
                resp = await route.fetch(post_data=json.dumps(body))
                raw = await resp.body()
                result["resp"] = json.loads(raw)
                await route.fulfill(response=resp, body=raw)
            except Exception as e:
                log.error("[blinkit_ui] forward error: %s", e)
                result["err"] = str(e)
                await route.continue_()

        await self._page.route("**/adservice/v3/campaigns", _handle)
        try:
            # Use the /edit/ URL — it shows the full campaign wizard with a clear "Save campaign" button
            campaign_url = f"{BASE_URL}/diy/edit/campaign/{campaign_id}"
            log.warning("[blinkit_ui] navigating to campaign edit page: %s", campaign_url)
            await self._page.goto(campaign_url, wait_until="load", timeout=60_000)
            log.warning("[blinkit_ui] landed on: %s", self._page.url)
            await self._page.wait_for_timeout(3000)

            # Dismiss any popup/modal (e.g. "What's new?") that overlaps the page
            for _ in range(3):
                try:
                    await self._page.keyboard.press("Escape")
                    await self._page.wait_for_timeout(400)
                except Exception:
                    pass
            # Find "What's new?" popup and click the button nearest to it (its X/close button)
            try:
                await self._page.evaluate("""
                    () => {
                        // Find element containing "What's new?" text
                        const allEls = Array.from(document.querySelectorAll('*'));
                        const whatsNew = allEls.find(el =>
                            el.children.length === 0 &&
                            (el.textContent || '').trim() === "What's new?"
                        );
                        if (whatsNew) {
                            // Walk up to find a container, then find last button (usually X)
                            let container = whatsNew.parentElement;
                            for (let i = 0; i < 6 && container; i++) {
                                const btns = Array.from(container.querySelectorAll('button, [role="button"]'))
                                    .filter(b => b.offsetParent !== null && (b.textContent || '').trim() !== "What's new?");
                                if (btns.length) {
                                    btns[btns.length - 1].click();
                                    return 'closed-whats-new';
                                }
                                container = container.parentElement;
                            }
                        }
                        // Generic: close button by aria-label or class
                        const closeSelectors = [
                            '[aria-label="close"]', '[aria-label="Close"]',
                            'button.close', '[data-dismiss]',
                            'button[class*="close"]', 'button[class*="Close"]',
                        ];
                        for (const sel of closeSelectors) {
                            const el = document.querySelector(sel);
                            if (el && el.offsetParent !== null) { el.click(); return 'closed-generic'; }
                        }
                    }
                """)
                await self._page.wait_for_timeout(800)
            except Exception:
                pass

            # On the /edit/ page the budget input is directly visible — no tabs to click
            # Just wait for the page to render the form
            try:
                await self._page.wait_for_selector("input[placeholder*='Budget' i]", timeout=15_000)
                log.warning("[blinkit_ui] budget input found on edit page")
            except Exception as e:
                log.warning("[blinkit_ui] budget input not found: %s", e)

            # On the /edit/ page the budget input is already visible — no pencil icon needed

            # Debug: dump all visible inputs to diagnose selector issues
            visible_inputs = await self._page.evaluate("""
                () => Array.from(document.querySelectorAll('input')).filter(
                    i => i.offsetParent !== null
                ).map(i => ({type: i.type, placeholder: i.placeholder, value: i.value}))
            """)
            log.warning("[blinkit_ui] visible inputs on page: %s", visible_inputs)

            # Step 3: Fill the budget input
            filled = False
            for sel in [
                "input[placeholder*='Budget' i]",
                "input[placeholder*='budget' i]",
                "input[placeholder*='amount' i]",
                "input[type='number']",
                "input[placeholder]",
            ]:
                try:
                    await self._page.click(sel, timeout=3_000)
                    await self._page.fill(sel, str(int(budget)), timeout=3_000)
                    filled = True
                    log.warning("[blinkit_ui] filled budget via: %s", sel)
                    break
                except Exception:
                    pass

            if not filled:
                log.warning("[blinkit_ui] could not find budget input")

            # Step 4: Click Done / Update / Save
            # First attempt: press Enter on the budget input — Blinkit wizard often submits on Enter
            if filled:
                try:
                    last_sel = None
                    for sel in [
                        "input[placeholder*='Budget' i]",
                        "input[placeholder*='budget' i]",
                        "input[placeholder*='amount' i]",
                        "input[type='number']",
                    ]:
                        try:
                            await self._page.wait_for_selector(sel, state="visible", timeout=1_000)
                            last_sel = sel
                            break
                        except Exception:
                            pass
                    if last_sel:
                        await self._page.press(last_sel, "Enter")
                        await self._page.wait_for_timeout(3000)
                        log.warning("[blinkit_ui] pressed Enter on budget input")
                except Exception as e:
                    log.warning("[blinkit_ui] Enter key failed: %s", e)

            # If Enter captured the PUT, skip button search
            if result.get("resp"):
                log.warning("[blinkit_ui] PUT captured via Enter key")
            else:
                # Debug: dump all visible buttons to diagnose selector issues
                visible_buttons = await self._page.evaluate("""
                    () => Array.from(document.querySelectorAll('button, [role="button"]')).filter(
                        b => b.offsetParent !== null
                    ).map(b => b.textContent.trim().slice(0, 40))
                """)
                log.warning("[blinkit_ui] visible buttons: %s", visible_buttons)

            clicked = result.get("resp") is not None

            if not clicked:
                # Try Playwright selector for each label
                for text in ["Done", "Update Campaign", "Update", "Save", "Apply"]:
                    try:
                        await self._page.click(f"button:has-text('{text}')", timeout=3_000)
                        clicked = True
                        log.warning("[blinkit_ui] clicked button: %s", text)
                        break
                    except Exception:
                        pass

            if not clicked:
                # Fallback: JS click by text label
                clicked = await self._page.evaluate("""
                    () => {
                        const labels = ['Done', 'Update Campaign', 'Update', 'Save', 'Apply'];
                        const all = Array.from(document.querySelectorAll('button, [role="button"]'))
                            .filter(b => b.offsetParent !== null);
                        for (const label of labels) {
                            const btn = all.find(b => b.textContent.trim().includes(label));
                            if (btn) { btn.click(); return label; }
                        }
                        return false;
                    }
                """)
                if clicked:
                    log.warning("[blinkit_ui] JS-clicked button: %s", clicked)
                    clicked = True

            if not clicked:
                # Fallback: find button physically closest to the budget input on screen
                clicked = await self._page.evaluate("""
                    () => {
                        const input = document.querySelector(
                            "input[placeholder*='Budget' i], input[placeholder*='budget' i], input[placeholder*='amount' i]"
                        );
                        if (!input) return false;
                        const iRect = input.getBoundingClientRect();
                        const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
                            .filter(b => b.offsetParent !== null && b.textContent.trim() !== "What's new?");
                        let closest = null, minDist = Infinity;
                        for (const btn of buttons) {
                            const r = btn.getBoundingClientRect();
                            const dx = r.left - iRect.right;
                            const dy = (r.top + r.height / 2) - (iRect.top + iRect.height / 2);
                            const dist = Math.sqrt(dx * dx + dy * dy);
                            if (dist < minDist) { minDist = dist; closest = btn; }
                        }
                        if (closest && minDist < 300) { closest.click(); return 'closest-px-' + Math.round(minDist); }
                        return false;
                    }
                """)
                if clicked:
                    log.warning("[blinkit_ui] JS-clicked nearest button: %s", clicked)
                    clicked = True

            if not clicked:
                # Last resort: submit button
                try:
                    await self._page.click("button[type='submit']", timeout=3_000)
                    clicked = True
                    log.warning("[blinkit_ui] clicked submit button")
                except Exception:
                    pass

            if not clicked:
                # Absolute position fallback: click just to the right of the budget input
                # (save/checkmark button is usually adjacent)
                try:
                    input_el = await self._page.query_selector(
                        "input[placeholder*='Budget' i], input[placeholder*='budget' i]"
                    )
                    if input_el:
                        box = await input_el.bounding_box()
                        if box:
                            # Try clicking at several positions to the right of the input
                            for x_offset in [box["width"] + 20, box["width"] + 50, box["width"] + 80]:
                                await self._page.mouse.click(
                                    box["x"] + x_offset,
                                    box["y"] + box["height"] / 2,
                                )
                                await self._page.wait_for_timeout(1500)
                                if result.get("resp"):
                                    clicked = True
                                    log.warning("[blinkit_ui] clicked via absolute position offset +%d", x_offset)
                                    break
                except Exception as e:
                    log.warning("[blinkit_ui] absolute position click failed: %s", e)

            if not clicked:
                log.warning("[blinkit_ui] could not find save button — see screenshots in ad_campaigns/")
                raise RuntimeError(
                    "Could not find the Update/Save button on Blinkit. "
                    "Check blinkit_step*.png screenshots in backend/ad_campaigns/"
                )

            await self._page.wait_for_timeout(5000)
        finally:
            await self._page.unroute("**/adservice/v3/campaigns")

        if result.get("err"):
            raise RuntimeError(f"UI intercept error: {result['err']}")
        if not result.get("resp"):
            raise RuntimeError("Budget update: no PUT request captured — see screenshots in ad_campaigns/")
        return result["resp"]


async def setup_with_state(storage_state: dict):
    """Open browser with a pre-loaded storage state (no DB call). Returns (playwright, browser, BlinkitClient)."""
    pw = await async_playwright().start()
    browser, context = await create_browser_context(pw, headless=True, storage_state=storage_state)

    idb_data = storage_state.get("indexedDB", [])
    if idb_data:
        await _inject_firebase_idb(context, idb_data)

    token_holder = {"token": None}
    page = await context.new_page()

    def _capture(request):
        if "adservice" in request.url and not token_holder["token"]:
            t = request.headers.get("firebase_user_token")
            if t:
                token_holder["token"] = t

    page.on("request", _capture)
    await page.goto(f"{BASE_URL}{CAMPAIGNS_PAGE}", wait_until="domcontentloaded", timeout=120_000)

    if "/diy/" not in page.url and "/dashboard" not in page.url:
        await browser.close()
        await pw.stop()
        raise RuntimeError(
            f"Session expired — redirected to {page.url}. Please reconnect Blinkit from the Campaign Manager page."
        )

    # Firebase token refresh + Blinkit API calls happen AFTER networkidle — wait up to 15s.
    for _ in range(30):
        if token_holder["token"]:
            break
        await asyncio.sleep(0.5)

    page.remove_listener("request", _capture)

    # Fallback 1: read token directly from localStorage (Firebase stores it there)
    if not token_holder["token"]:
        try:
            t = await page.evaluate("""
                () => {
                    for (const key of Object.keys(localStorage)) {
                        if (key.startsWith('firebase:authUser:')) {
                            try {
                                const data = JSON.parse(localStorage.getItem(key));
                                if (data && data.stsTokenManager && data.stsTokenManager.accessToken) {
                                    return data.stsTokenManager.accessToken;
                                }
                            } catch(e) {}
                        }
                    }
                    return null;
                }
            """)
            if t:
                token_holder["token"] = t
        except Exception:
            pass

    # Fallback 2: poll for Firebase SDK (legacy window.firebase global)
    if not token_holder["token"]:
        try:
            t = await page.evaluate("""
                async () => {
                    for (let i = 0; i < 20; i++) {
                        try {
                            const auth = window.firebase && window.firebase.auth && window.firebase.auth();
                            if (auth && auth.currentUser) {
                                const token = await auth.currentUser.getIdToken(true);
                                if (token) return token;
                            }
                        } catch(e) {}
                        await new Promise(r => setTimeout(r, 500));
                    }
                    return null;
                }
            """)
            if t:
                token_holder["token"] = t
        except Exception:
            pass

    if not token_holder["token"]:
        await browser.close()
        await pw.stop()
        raise RuntimeError(
            "Blinkit session expired — could not obtain auth token. "
            "Please reconnect Blinkit from the Campaign Manager page."
        )

    return pw, browser, BlinkitClient(page, token_holder["token"])


async def setup(tenant_id: str):
    """Get a WORKING session, open browser, return (playwright, browser, BlinkitClient).

    `ensure()` probes the stored session and refreshes or re-logs-in if it is
    dead, so the campaign manager no longer opens Chromium against a session that
    expired days ago just to discover the redirect. It raises a typed AuthError,
    which cli/main.py maps to exit 3 → `jobs.error='auth_expired'`.

    This matters more here than in the scrapers: this path WRITES budgets and bids
    to Blinkit, so failing halfway through on a dead session is a money-adjacent
    failure, not just a missing row.
    """
    async with AsyncSessionLocal() as db:
        session = await auth_service.ensure(db, tenant_id, "blinkit")

    return await setup_with_state(session.storage_state)
