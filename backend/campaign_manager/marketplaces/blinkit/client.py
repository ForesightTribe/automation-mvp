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
from scraper.utils.browser import create_browser_context, new_context
from campaign_manager.writes import SessionExpired
from campaign_manager.marketplaces.blinkit import build
from campaign_manager.marketplaces.blinkit import payload as payload_check

_IST = timezone(timedelta(hours=5, minutes=30))

BASE_URL = "https://brands.blinkit.com"
CAMPAIGNS_PAGE = "/dashboard"
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


def _looks_logged_out(html: str | None) -> bool:
    """A non-JSON body that is the login page rather than some other error."""
    if not html:
        return False
    lowered = html.lower()
    return any(m in lowered for m in ("login", "sign in", "unauthorized", "unauthenticated"))


class BlinkitClient:
    def __init__(self, page: Page, token: str, tenant_id: str | None = None):
        self._page = page
        self._token = token
        self._email = _decode_email(token)
        # Needed to re-authenticate mid-run. None for a client built straight from a stored
        # state (no tenant to look up), which then cannot self-heal — it raises instead.
        self._tenant_id = tenant_id

    async def _fetch(self, method: str, path: str, body: dict | None = None,
                     *, _retrying: bool = False) -> dict:
        """One Blinkit API call, made through the page so Cloudflare sees a real browser.

        Re-authenticates ONCE if the session has died, then replays the call. A bid run can
        last minutes while the session is established only at its start, so without this a
        mid-run expiry costs every remaining keyword — and does it while claiming Blinkit
        rejected the bids, which is not what happened.

        Replaying a write is safe: an auth failure means the request never reached the
        campaign.
        """
        url = f"{BASE_URL}{path}"
        # GET/HEAD cannot have a body — move params to query string
        if method in ("GET", "HEAD") and body:
            url = f"{url}?{urlencode(body)}"
            body = None
        raw = await self._page.evaluate(
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
                let body_json = null;
                try { body_json = JSON.parse(text); } catch(e) {}
                // Carry the STATUS out too: a login redirect returns HTML, which
                // used to be swallowed into `{}` and read as a rejection.
                return {__status: resp.status, __body: body_json,
                        __html: body_json === null ? text.slice(0, 200) : null};
            }""",
            [method, url, self._token, body],
        )

        status, payload = raw.get("__status"), raw.get("__body")
        if status in (401, 403) or (payload is None and _looks_logged_out(raw.get("__html"))):
            if _retrying or not self._tenant_id:
                raise SessionExpired(
                    f"Blinkit returned {status} for {method} {path} — the session is no "
                    f"longer valid" + ("" if self._tenant_id else
                                       " and this client cannot re-authenticate itself"))
            log.warning("[blinkit] session looks dead (%s on %s) — re-authenticating mid-run",
                        status, path)
            await self.reauth()
            return await self._fetch(method, path, body, _retrying=True)
        # Unchanged for every caller: a non-JSON body is still `{}`.
        return payload if payload is not None else {}

    async def reauth(self) -> None:
        """Rebuild this client's session in place, without disturbing the caller.

        Swaps the browser CONTEXT, not the browser. The engine holds `pw`/`browser` from
        `setup()` and closes them in a `finally`, so launching a second Chromium here would
        leak ~1 GB and leave the caller closing the wrong one.

        `auth_service.ensure` is the same load → probe → refresh → re-login path the run
        used at startup, so this also respects the circuit breaker that suspends auto-login
        after repeated failures rather than hammering it from inside a loop.
        """
        old_context = self._page.context
        browser = old_context.browser
        async with AsyncSessionLocal() as db:
            session = await auth_service.ensure(db, self._tenant_id, "blinkit")

        state = session.storage_state
        context = await new_context(browser, state)
        idb = (state or {}).get("indexedDB", [])
        if idb:
            await _inject_firebase_idb(context, idb)
        page, token = await _bind_session(context)

        self._page, self._token = page, token
        self._email = _decode_email(token) or self._email
        await old_context.close()
        log.warning("[blinkit] session re-established mid-run")

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

    async def get_keyword_attributes(self, campaign_id: int, campaign_type: str,
                                     keywords: list[str]) -> list[dict]:
        """Blinkit's published bid range per keyword (V7.6).

        `keyword_attributes[].bid_range.{exact_match,smart_match}` carries
        `{min, max, suggested_min, suggested_max, min_for_boost}`. The `min` is the floor
        Blinkit enforces on a bid write, and it varies PER KEYWORD (₹50 on 'mango', ₹400 on
        'cocktail') — there is no account-wide number. ⚠️ `min_cpm_config`, despite the
        name, is a BUDGET input and must never be used as a bid floor.

        Takes a comma-separated list, so a whole campaign costs ONE request regardless of
        keyword count; chunked only to keep the URL sane.
        """
        out: list[dict] = []
        for i in range(0, len(keywords), 40):
            chunk = keywords[i:i + 40]
            resp = await self._fetch("GET", "/adservice/v1/campaigns/keywords/attributes", {
                "keywords": ",".join(chunk),
                "campaign_type": campaign_type or "",
                "campaign_id": str(campaign_id),
            })
            data = (resp or {}).get("data") or {}
            out.extend(data.get("keyword_attributes")
                       or (resp or {}).get("keyword_attributes") or [])
        return out

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

        # Blinkit refuses a bid update on a campaign with no products — its own dashboard
        # shows the same error — so say that plainly rather than letting it come back as an
        # opaque 400.
        if not build.pids(detail):
            raise RuntimeError(
                "This campaign has no products (PIDs). Blinkit requires at least one product "
                "to update keyword bids — even their own dashboard shows this error. "
                "Fix: open this campaign in the Blinkit Ads dashboard and add at least one product."
            )

        payload = build.build(
            detail, shape=build.BID, campaign_id=campaign_id,
            requested_by=self._email,
            advertiser_id=(advertiser_id if advertiser_id is not None
                           else await self.get_advertiser_id()),
            keyword_updates=keyword_updates, min_cpm=min_cpm_config,
        )

        # Last gate before a live account changes: does this body still describe the
        # campaign we read, apart from the bid we meant to move? (payload.py)
        payload_check.verify(detail, payload, shape=payload_check.BID,
                             campaign_id=campaign_id)

        resp = await self._fetch("PUT", "/adservice/v3/campaigns", payload)
        if resp.get("status") or resp.get("success"):
            return resp

        msg = resp.get("message") or resp
        raise RuntimeError(f"Blinkit bid update failed: {msg}")

    async def get_advertiser_id(self) -> int:
        """The ad account this session belongs to, derived live from Blinkit (B3).

        ⚠️ This used to fall back to a hardcoded `234` when the response came back without
        the field — the PRE-SPLIT account, dead since Dobra's accounts were separated. A
        flaky read therefore aimed live writes, with real money, at the wrong account. There
        is no fallback now: an unreadable id raises, because refusing to write is the only
        safe answer to "which account is this?".

        Live writes do not depend on this at all — they send the tenant's STORED
        `advertiser_id` (set by `writes.arm_live`). This is the derivation shown by
        `cm advertiser` for comparison, and the last-resort path when no id was passed.
        """
        from_date, to_date = _date_range(1)
        resp = await self._fetch("POST", "/adservice/v1/advertisers/campaigns", {
            "from_date": from_date,
            "to_date": to_date,
            "campaign_types": ["PRODUCT_LISTING"],
        })
        adv_id = (resp.get("data") or {}).get("advertiser_id")
        if not isinstance(adv_id, int) or adv_id <= 0:
            raise RuntimeError(
                "Blinkit did not report an advertiser_id for this session "
                f"(got {adv_id!r}). Refusing to guess — a wrong account id spends real "
                "money against someone else's account. Set the tenant's id explicitly "
                "with `cli cm set-advertiser`."
            )
        log.debug("[get_advertiser_id] advertiser_id=%r", adv_id)
        return adv_id

    async def update_campaign(self, campaign_id: int, changes: dict, *,
                              advertiser_id: int | None = None) -> dict:
        """Minimal PUT payload for campaign updates (e.g. budget).

        advertiser_id: optional explicit account override (campaign-manager v2 passes the
        per-tenant stored id here). Falls back to get_advertiser_id() when None.

        The `empty_pids` option was removed 2026-09-05 — it sent `pids: ""` to work around
        a delisted catalog, and Blinkit rejects any payload with no pids, so it never
        worked. See `adapter.apply_budget`."""
        actual_advertiser_id = advertiser_id if advertiser_id is not None else await self.get_advertiser_id()
        detail, min_cpm_config = await self.get_campaign_detail(campaign_id)
        if not detail:
            raise RuntimeError(f"Could not fetch details for campaign {campaign_id}")

        payload = build.build(
            detail, shape=build.BUDGET,
            campaign_id=campaign_id, requested_by=self._email,
            advertiser_id=actual_advertiser_id, min_cpm=min_cpm_config,
        )
        # `changes` is the caller's delta, merged over the campaign's own values. The budget
        # write is the only caller and passes `bidding_strategy`; the merge stays generic
        # because the verify below treats it with exactly the suspicion it deserves.
        payload.update(changes)
        # AFTER `changes` is merged — that dict is a caller-supplied override and is
        # exactly as capable of clobbering the campaign as the builder is.
        payload_check.verify(
            detail, payload, shape=payload_check.BUDGET, campaign_id=campaign_id)
        log.debug("[update_campaign] campaign=%d pids=%r budget=%s",
                    campaign_id, payload.get("pids"),
                    payload.get("bidding_strategy", {}).get("total_budget"))
        if detail.get("campaign_type") == "BANNER_LISTING":
            # This type has tripped Blinkit's image validator before, so its body is worth
            # having in full when one is rejected.
            log.debug("[update_campaign] FULL PAYLOAD=%s", json.dumps(payload, default=str))
        resp = await self._fetch("PUT", "/adservice/v3/campaigns", payload)
        log.debug("[update_campaign] RESP=%r", resp)
        return resp



async def _bind_session(context) -> tuple:
    """A context with a session in it → `(page, firebase_token)`.

    Extracted so `setup_with_state` and `BlinkitClient.reauth` establish a session the SAME
    way. They used to be one code path only because re-authentication did not exist; making
    it a second copy is how the two would drift, and the token-capture fallbacks below are
    exactly the fiddly part nobody would keep in sync by hand.
    """
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
        # Raise, don't clean up: the browser belongs to the CALLER (a fresh one in
        # `setup_with_state`, the run's existing one in `reauth`), and closing it here is
        # how the extraction would leak or double-close.
        raise SessionExpired(
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
        raise SessionExpired(
            "Blinkit session expired — could not obtain an auth token. "
            "Please reconnect Blinkit from the Campaign Manager page."
        )

    return page, token_holder["token"]


async def setup_with_state(storage_state: dict, tenant_id: str | None = None):
    """Open a browser with a pre-loaded storage state (no DB call).
    Returns (playwright, browser, BlinkitClient).

    `tenant_id` is what lets the client re-authenticate itself mid-run; without it a dead
    session raises instead of self-healing.
    """
    pw = await async_playwright().start()
    browser, context = await create_browser_context(pw, headless=True, storage_state=storage_state)

    idb_data = storage_state.get("indexedDB", [])
    if idb_data:
        await _inject_firebase_idb(context, idb_data)

    try:
        page, token = await _bind_session(context)
    except Exception:
        await browser.close()
        await pw.stop()
        raise

    return pw, browser, BlinkitClient(page, token, tenant_id=tenant_id)


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

    return await setup_with_state(session.storage_state, tenant_id=tenant_id)
