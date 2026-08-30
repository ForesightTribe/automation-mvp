import asyncio
import json
import re
from datetime import date
from urllib.parse import urlencode

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
            await _log_advertiser(page, token)

            # ── Account-level pulls ────────────────────────────────────────────
            # ONE config call serves two purposes: which campaign types may be requested,
            # and the city id→name directory that turns a campaign's `region_ids` into
            # names (V7). Resolving the names here is what spares us a city lookup table.
            config = await _account_config(page, token)
            cities = (config or {}).get("cities") or {}
            logger.info(f"City directory: {len(cities)} cities")

            body = {
                "from_date": from_str,
                "to_date": to_str,
                "campaign_types": _enabled_campaign_types(config),
            }
            campaigns_resp = await _post(page, ep.CAMPAIGNS_API, body, token)
            if campaigns_resp is None:
                raise RuntimeError(
                    "Campaign list request failed — see the logged status + message "
                    "from Blinkit above."
                )
            campaigns = (campaigns_resp.get("data") or {}).get("campaigns") or []
            if not campaigns:
                raise RuntimeError(
                    f"Campaign list is empty for {from_str}→{to_str}. The advertiser has "
                    "no campaigns in this window, or the session belongs to a different "
                    "advertiser than expected (see the advertiser logged above)."
                )
            logger.info(f"Captured {len(campaigns)} campaigns")

            sov_resp = await _post(page, ep.SPONSORED_SOV_API, body, token)
            sov = ((sov_resp or {}).get("data") or {}).get("sponsored_sov") or []

            collections_resp = await _get(page, ep.BRAND_COLLECTIONS_API, token)
            collections = ((collections_resp or {}).get("data") or {}).get("collections") or []

            plans_resp = await _get(page, ep.VISIBILITY_PLANS_API, token)
            plans = (plans_resp or {}).get("data") or []

            # ── Per-campaign pulls ──────────────────────────────────────────────
            # Every campaign is fetched — no skipping — so the data is complete.
            # Cloudflare is handled purely by pacing + 429 backoff in _fetch.
            # Referrer is set to the campaign page (some endpoints require it).
            # --limit just caps the count for a smoke test.
            #
            # TWO kinds of pull, with DIFFERENT eligibility (V7):
            #   - METRICS (daily series + report) — only campaigns that have actually run.
            #     A draft/scheduled/under-review campaign has none.
            #   - CONFIGURATION (detail + keyword bid ranges) — EVERY campaign, drafts
            #     included. They have keywords, city targeting and bid floors from the
            #     moment they exist, and a just-created campaign is exactly the one someone
            #     is about to automate; skipping it would make "it syncs tonight" false for
            #     the only case that needs it.
            targets = campaigns[:limit] if limit else campaigns
            runnable_ids = {
                c["id"] for c in campaigns
                if _norm_status(c.get("campaign_status")) not in _NO_DATA_STATUSES
            }
            no_metrics = len(campaigns) - len(runnable_ids)
            if no_metrics:
                logger.info(
                    f"{no_metrics} campaign(s) {sorted(_NO_DATA_STATUSES)} — config only, no metrics"
                )
            logger.info(f"Per-campaign pulls for {len(targets)}/{len(campaigns)} campaigns")

            daily: dict[int, list] = {}
            detail: dict[int, dict] = {}
            campaign_detail: dict[int, dict] = {}
            keyword_attributes: dict[int, list] = {}
            total = len(targets)
            for i, c in enumerate(targets, 1):
                cid = c["id"]
                logger.info(f"  campaign {i}/{total} (id {cid})")
                referrer = f"{ep.BASE_URL}/diy/campaign/{cid}"

                # Configuration — every campaign.
                detail_resp = await _get(
                    page, ep.CAMPAIGN_DETAIL_API.format(campaign_id=cid), token, referrer=referrer
                )
                # ⚠️ The campaign sits at data.CAMPAIGN, not at data — and the account's
                # `min_cpm_config` is its SIBLING, not a field on it. Fold the config in so
                # one object carries everything the parser needs.
                data = (detail_resp or {}).get("data") or {}
                cfg = data.get("campaign") or {}
                if cfg:
                    cfg = {**cfg, "min_cpm_config": data.get("min_cpm_config") or {}}
                campaign_detail[cid] = cfg
                keyword_attributes[cid] = await _fetch_keyword_attributes(
                    page, cid, cfg, token, referrer
                )

                # Metrics — only campaigns that have run.
                if cid not in runnable_ids:
                    continue
                daily[cid] = await _fetch_daily(page, cid, from_str, to_str, token, referrer)
                report = await _post(
                    page,
                    ep.CAMPAIGN_REPORT_API.format(campaign_id=cid),
                    {"from_date": from_str, "to_date": to_str},
                    token,
                    referrer=referrer,
                )
                detail[cid] = (report or {}).get("data") or {}
            got_config = sum(1 for v in campaign_detail.values() if v)
            logger.info(
                f"Fetched config for {got_config}/{len(campaign_detail)} campaigns "
                f"({sum(len(v) for v in keyword_attributes.values())} keyword bid ranges), "
                f"metrics for {len(daily)}"
            )
            # A campaign whose detail call failed has its targeting/floor columns written
            # NULL (the upsert replaces every updatable column, and a batch insert cannot
            # carry per-row column sets). One campaign going blank for a day self-heals and
            # costs nothing — the write-time check is the authority. ALL of them going
            # blank means the endpoint changed shape, and that must not pass silently, so
            # say so loudly rather than reporting a clean scrape over empty data.
            if targets and not got_config:
                logger.warning(
                    f"Campaign detail returned nothing for all {len(targets)} campaigns — "
                    "city targeting, budget floors and keyword bid ranges will be blanked. "
                    "Check whether /adservice/v1/campaigns/{id} changed shape."
                )

            return {
                "campaigns": campaigns,
                "daily": daily,
                "detail": detail,
                "campaign_detail": campaign_detail,
                "keyword_attributes": keyword_attributes,
                "cities": cities,
                "sponsored_sov": sov,
                "brand_collections": collections,
                "visibility_plans": plans,
            }
        finally:
            await browser.close()


def _keywords_from_detail(detail: dict) -> list[str]:
    """The campaign's keyword names, out of its detail response.

    Blinkit returns keywords in two places depending on the campaign — nested under
    `campaign_targeting`, or at the top level — so read the nested one first and fall back.
    Order is preserved and duplicates dropped, since the names go straight into a query
    string."""
    entries = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
        or detail.get("keywords", []) or []
    )
    seen: dict[str, None] = {}
    for kw in entries:
        name = (kw.get("keyword") or "").strip()
        if name:
            seen.setdefault(name, None)
    return list(seen)


async def _fetch_keyword_attributes(
    page, campaign_id: int, detail: dict, token: str, referrer: str
) -> list:
    """Blinkit's published bid range for each of a campaign's keywords (V7).

    The endpoint takes a comma-separated keyword list, so a whole campaign costs ONE
    request regardless of how many keywords it carries (chunked only to keep the URL
    sane). A campaign with no keyword targeting — every PRODUCT_RECOMMENDATION campaign —
    costs no request at all.
    """
    keywords = _keywords_from_detail(detail)
    if not keywords:
        return []

    campaign_type = detail.get("campaign_type") or ""
    out: list = []
    for i in range(0, len(keywords), ep.KEYWORD_ATTRIBUTES_CHUNK):
        chunk = keywords[i : i + ep.KEYWORD_ATTRIBUTES_CHUNK]
        query = urlencode({
            "keywords": ",".join(chunk),
            "campaign_type": campaign_type,
            "campaign_id": str(campaign_id),
        })
        resp = await _get(page, f"{ep.KEYWORD_ATTRIBUTES_API}?{query}", token, referrer=referrer)
        data = (resp or {}).get("data") or {}
        rows = data.get("keyword_attributes") or (resp or {}).get("keyword_attributes") or []
        out.extend(rows)
    return out


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

    if "/diy/" not in page.url and "/dashboard" not in page.url:
        raise RuntimeError(f"Session expired — redirected to {page.url}")
    if "firebase_user_token" not in captured:
        await asyncio.sleep(3)
    page.remove_listener("request", on_request)

    token = captured.get("firebase_user_token")
    if not token:
        raise RuntimeError("Could not capture firebase_user_token — session may be expired")
    return token


async def _log_advertiser(page, token: str) -> None:
    """Record which advertiser this session is acting as. A mis-login (right
    tenant, wrong Blinkit account) is otherwise invisible until the data lands."""
    resp = await _get(page, ep.ADVERTISERS_API, token)
    items = (resp or {}).get("items") or []
    if not items:
        logger.warning("Could not identify advertiser for this session")
        return
    named = ", ".join(f"{a.get('name')} (id {a.get('id')})" for a in items)
    logger.info(f"Advertiser: {named}")


async def _account_config(page, token: str) -> dict:
    """The account config the dashboard loads on start — enabled campaign types AND the
    city id→name directory, in one call.

    Deliberately still v2, not the v3 the dashboard has moved to: the two differ in which
    asset types they list, and that set decides which campaigns the LIST call returns. A
    change there would silently change what gets scraped, so it is not a free upgrade.
    Both carry `cities`, which is all V7 needs from it."""
    resp = await _get(page, ep.CAMPAIGN_CONFIG_API, token)
    return (resp or {}).get("data") or {}


def _enabled_campaign_types(config: dict) -> list[str]:
    """Campaign types enabled for this advertiser, out of an already-fetched config.
    Blinkit rejects the whole request with 400 if it is sent a disabled type, so never
    send the full hardcoded list when this succeeds."""
    objectives = (config or {}).get("objective_types") or []
    types = sorted({t for o in objectives for t in (o.get("asset_types") or [])})
    if not types:
        logger.warning(
            f"Could not read enabled campaign types — falling back to all "
            f"{len(ep.ALL_CAMPAIGN_TYPES)} types; expect a 400 if any is disabled."
        )
        return ep.ALL_CAMPAIGN_TYPES
    disabled = sorted(set(ep.ALL_CAMPAIGN_TYPES) - set(types))
    logger.info(f"Enabled campaign types: {len(types)} ({', '.join(types)})")
    if disabled:
        logger.debug(f"Not enabled for this advertiser: {', '.join(disabled)}")
    return types


async def _post(page, path: str, body: dict, token: str, referrer: str | None = None) -> dict | list | None:
    return await _fetch(page, path, token, method="POST", body=body, referrer=referrer)


async def _get(page, path: str, token: str, referrer: str | None = None) -> dict | list | None:
    return await _fetch(page, path, token, method="GET", body=None, referrer=referrer)


def _error_detail(result: dict) -> str:
    """Blinkit returns error bodies as JSON — {"success": false, "message": ...} —
    which the in-page fetch parses into `json`, not `snippet`. Read the message so
    failures like "[...] are not enabled for given advertiser" reach the log instead
    of being reported as an empty body. `snippet` is the non-JSON case (Cloudflare
    challenge / redirect), `error` the network case."""
    body = result.get("json")
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    if body is not None:
        return json.dumps(body)[:200]
    return result.get("snippet") or result.get("error") or ""


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

        detail = _error_detail(result)
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
