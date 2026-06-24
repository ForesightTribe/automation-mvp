import asyncio
import json
import re
from datetime import date

from playwright.async_api import async_playwright

from scraper.platforms.blinkit.dashboard_data.marketing import endpoints as ep
from scraper.utils.browser import create_browser_context, write_blocker
from app.utils.logger import logger

# Per-campaign endpoints reject more than two metrics at a time (the UI cap is
# also the API cap), so request the daily metrics in pairs and merge by date.
_METRIC_CHUNK = 2

# brands.blinkit.com is Cloudflare-protected and rate-limits rapid programmatic
# fetches (429 "Just a moment..."). Pace every call, and back off + retry on 429.
_THROTTLE_S = 0.6
_MAX_RETRIES = 3
_RATE_LIMIT_BACKOFF_S = 15
# Abort if this many calls exhaust their 429 retries back-to-back (sustained
# Cloudflare block) — a legitimately empty campaign (204) does NOT count.
_RATE_LIMIT_ABORT_AFTER = 3

# Recurring fetch failures are collapsed to one warning per (endpoint, status)
# signature so a systemic problem doesn't flood the console across N campaigns.
_WARNED_SIGNATURES: set[str] = set()
# Mutable run state (reset per scrape): consecutive 429-exhausted calls.
_STATE = {"rate_limit_exhaustions": 0}


def _fmt(d: date) -> str:
    """Blinkit's ad APIs want M/D/YYYY (no zero-padding)."""
    return f"{d.month}/{d.day}/{d.year}"


# campaign_status values for campaigns that have never run, so they carry no
# metrics — skip their per-campaign pulls (metadata is still saved from the list).
# Matched case-insensitively with spaces/hyphens normalized to underscores; add
# any other not-yet-running states Blinkit uses here.
_NO_DATA_STATUSES = {"DRAFT", "SCHEDULED", "UNDER_REVIEW"}


def _norm_status(status: str | None) -> str:
    return (status or "").strip().upper().replace(" ", "_").replace("-", "_")


async def scrape(storage_state: dict, start: date, end: date, limit: int | None = None) -> dict:
    """Active scrape of the marketing dashboard for a [start, end] window.

    Authenticates once (capturing the firebase_user_token), then issues in-page
    fetches per endpoint — same-origin on brands.blinkit.com, so Cloudflare
    cookies ride along automatically. Returns raw API payloads; parsing happens
    in parser.py.
    """
    from_str, to_str = _fmt(start), _fmt(end)
    _WARNED_SIGNATURES.clear()
    _STATE["rate_limit_exhaustions"] = 0

    async with async_playwright() as p:
        browser, context = await create_browser_context(
            p, headless=True, storage_state=storage_state
        )

        idb_data = storage_state.get("indexedDB", [])
        if idb_data:
            await _inject_firebase_idb(context, idb_data)
        else:
            logger.warning("No IndexedDB data in session — scrape may fail. Re-login recommended.")

        await context.route("**/*", write_blocker)

        try:
            page = await context.new_page()
            token = await _authenticate(page)

            # ── Account-level pulls ────────────────────────────────────────────
            body = {
                "from_date": from_str,
                "to_date": to_str,
                "campaign_types": ep.ALL_CAMPAIGN_TYPES,
            }
            campaigns_resp = await _post(page, ep.CAMPAIGNS_API, body, token)
            campaigns = ((campaigns_resp or {}).get("data") or {}).get("campaigns") or []
            if not campaigns:
                raise RuntimeError(
                    "Campaign list came back empty (see logged snippet) — session "
                    "likely expired or blocked. Re-run `cli auth blinkit`."
                )
            logger.info(f"Captured {len(campaigns)} campaigns")

            sov_resp = await _post(page, ep.SPONSORED_SOV_API, body, token)
            sov = ((sov_resp or {}).get("data") or {}).get("sponsored_sov") or []

            collections_resp = await _get(page, ep.BRAND_COLLECTIONS_API, token)
            collections = ((collections_resp or {}).get("data") or {}).get("collections") or []

            plans_resp = await _get(page, ep.VISIBILITY_PLANS_API, token)
            plans = (plans_resp or {}).get("data") or []

            # ── Per-campaign pulls (daily series + keyword/asset breakdown) ─────
            # Every campaign is fetched — no skipping — so the data is complete.
            # Cloudflare is handled purely by pacing + 429 backoff in _fetch.
            # Referrer is set to the campaign page (some endpoints require it).
            # Skip campaigns that have never run (draft/scheduled/under review) —
            # no metrics to fetch. --limit just caps the count for a smoke test.
            runnable = [
                c for c in campaigns
                if _norm_status(c.get("campaign_status")) not in _NO_DATA_STATUSES
            ]
            skipped = len(campaigns) - len(runnable)
            targets = runnable[:limit] if limit else runnable
            if skipped:
                logger.info(f"Skipping {skipped} not-yet-running campaign(s) {sorted(_NO_DATA_STATUSES)}")
            logger.info(f"Per-campaign pulls for {len(targets)}/{len(campaigns)} campaigns")

            daily: dict[int, list] = {}
            detail: dict[int, dict] = {}
            total = len(targets)
            for i, c in enumerate(targets, 1):
                cid = c["id"]
                logger.info(f"  campaign {i}/{total} (id {cid})")
                referrer = f"{ep.BASE_URL}/diy/campaign/{cid}"
                daily[cid] = await _fetch_daily(page, cid, from_str, to_str, token, referrer)
                report = await _post(
                    page,
                    ep.CAMPAIGN_REPORT_API.format(campaign_id=cid),
                    {"from_date": from_str, "to_date": to_str},
                    token,
                    referrer=referrer,
                )
                detail[cid] = (report or {}).get("data") or {}
            logger.info(f"Fetched daily + detail for {total} campaigns")

            return {
                "campaigns": campaigns,
                "daily": daily,
                "detail": detail,
                "sponsored_sov": sov,
                "brand_collections": collections,
                "visibility_plans": plans,
            }
        finally:
            await browser.close()


async def _fetch_daily(
    page, campaign_id: int, from_str: str, to_str: str, token: str, referrer: str
) -> list:
    """Per-campaign daily series. The endpoint accepts at most two metrics per
    call, so request them in pairs and merge the day rows by date. A pair that
    fails is skipped (its metrics are just absent), so the series degrades
    gracefully rather than failing wholesale."""
    url = ep.CAMPAIGN_DAILY_API.format(campaign_id=campaign_id)
    merged: dict[str, dict] = {}
    for i in range(0, len(ep.DAILY_METRICS), _METRIC_CHUNK):
        chunk = ep.DAILY_METRICS[i : i + _METRIC_CHUNK]
        resp = await _post(
            page, url, {"metrics": chunk, "from_date": from_str, "to_date": to_str},
            token, referrer=referrer,
        )
        data = (resp.get("data") if isinstance(resp, dict) else resp) if resp else None
        for row in data or []:
            day = row.get("date_ist")
            if day:
                merged.setdefault(day, {"date_ist": day}).update(row)
    return list(merged.values())


async def _authenticate(page) -> str:
    """Load the campaigns page and capture the firebase_user_token from the
    SPA's own API requests, so we can replay endpoints with custom date ranges."""
    captured: dict = {}

    async def on_request(request):
        if "/adservice/" in request.url and "firebase_user_token" not in captured:
            token = request.headers.get("firebase_user_token")
            if token:
                captured["firebase_user_token"] = token

    page.on("request", on_request)
    await page.goto(f"{ep.BASE_URL}{ep.CAMPAIGNS_PAGE}", wait_until="networkidle", timeout=60_000)

    if "/diy/" not in page.url:
        raise RuntimeError(f"Session expired — redirected to {page.url}")
    if "firebase_user_token" not in captured:
        await asyncio.sleep(3)
    page.remove_listener("request", on_request)

    token = captured.get("firebase_user_token")
    if not token:
        raise RuntimeError("Could not capture firebase_user_token — session may be expired")
    return token


async def _post(page, path: str, body: dict, token: str, referrer: str | None = None) -> dict | list | None:
    return await _fetch(page, path, token, method="POST", body=body, referrer=referrer)


async def _get(page, path: str, token: str, referrer: str | None = None) -> dict | list | None:
    return await _fetch(page, path, token, method="GET", body=None, referrer=referrer)


async def _fetch(
    page, path: str, token: str, *, method: str, body: dict | None, referrer: str | None
) -> dict | list | None:
    """In-page fetch on the brands.blinkit.com origin (cookies auto-included),
    adding the captured firebase_user_token. Reads the body as text and tries to
    parse JSON, so a non-JSON response (HTML challenge / redirect) is reported as
    a status + snippet rather than crashing. Returns the parsed JSON on success,
    else None."""
    url = f"{ep.BASE_URL}{path}"
    js = """async ({ url, method, body, token, referrer }) => {
        const opts = {
            method,
            headers: { 'content-type': 'application/json', 'firebase_user_token': token },
        };
        if (body) opts.body = JSON.stringify(body);
        if (referrer) { opts.referrer = referrer; opts.referrerPolicy = 'unsafe-url'; }
        let res;
        try { res = await fetch(url, opts); }
        catch (e) { return { ok: false, status: 0, error: String(e) }; }
        const text = await res.text();
        try { return { ok: res.ok, status: res.status, json: JSON.parse(text) }; }
        catch (e) { return { ok: res.ok, status: res.status, snippet: text.slice(0, 200) }; }
    }"""
    payload = {"url": url, "method": method, "body": body, "token": token, "referrer": referrer}

    for attempt in range(_MAX_RETRIES):
        await asyncio.sleep(_THROTTLE_S)  # pace every call to stay under the rate limit
        result = await page.evaluate(js, payload)
        status = result.get("status")

        if result.get("ok"):
            # 200 -> JSON; 204/empty -> json is None, a legitimate "no data".
            _STATE["rate_limit_exhaustions"] = 0
            return result.get("json")

        if status == 429 and attempt < _MAX_RETRIES - 1:
            logger.debug(f"429 on {path}; backing off {_RATE_LIMIT_BACKOFF_S}s (attempt {attempt + 1})")
            await asyncio.sleep(_RATE_LIMIT_BACKOFF_S)
            continue

        # Sustained rate-limiting (429 retries exhausted) -> abort with guidance.
        if status == 429:
            _STATE["rate_limit_exhaustions"] += 1
            if _STATE["rate_limit_exhaustions"] >= _RATE_LIMIT_ABORT_AFTER:
                raise RuntimeError(
                    "Cloudflare is persistently rate-limiting (429) despite backoff. "
                    "Aborting — rerun later, or increase _THROTTLE_S/_RATE_LIMIT_BACKOFF_S."
                )

        detail = result.get("snippet") or result.get("error") or ""
        # Collapse repeats: one warning per (endpoint pattern, status); rest -> debug.
        endpoint = re.sub(r"/\d+$", "/{id}", path)
        signature = f"{endpoint}|{status}"
        msg = f"Fetch {path} -> status {status}: {detail!r}"
        if signature in _WARNED_SIGNATURES:
            logger.debug(msg)
        else:
            _WARNED_SIGNATURES.add(signature)
            logger.warning(msg)
        return None

    return None


async def _inject_firebase_idb(context, idb_data: list) -> None:
    # Pre-populate IndexedDB before any page JS runs so Firebase SDK finds the refresh token.
    idb_json = json.dumps(idb_data)
    await context.add_init_script(f"""(function() {{
        var IDB_DATA = {idb_json};
        if (!IDB_DATA || !IDB_DATA.length) return;
        var req = indexedDB.open('firebaseLocalStorageDb', 1);
        req.onupgradeneeded = function(e) {{
            var db = e.target.result;
            if (!db.objectStoreNames.contains('firebaseLocalStorage'))
                db.createObjectStore('firebaseLocalStorage', {{keyPath: 'fbase_key'}});
        }};
        req.onsuccess = function(e) {{
            var db = e.target.result;
            var tx = db.transaction('firebaseLocalStorage', 'readwrite');
            var store = tx.objectStore('firebaseLocalStorage');
            IDB_DATA.forEach(function(item) {{ store.put(item); }});
        }};
    }})();""")
    logger.info(f"IndexedDB injection: {len(idb_data)} Firebase items")
