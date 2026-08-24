"""
Live position checker — where our sponsored ad actually ranks in Blinkit consumer
search, for one keyword at one dark store.

**This talks to Blinkit's search API directly; it does not load search pages.**
One warm-up per run establishes a cleared session and captures the session-bound
headers Blinkit attaches to its own `/v1/layout/search` request; after that every
keyword — and every store — is a single in-page `fetch()` costing well under a second.
The store is selected by the `lat`/`lon` HEADERS, so changing location needs no
navigation at all.

That transport (in-page fetch on a cleared session, Cloudflare-challenge detection,
retry with backoff) is shared with the public scraper rather than copied:
`scraper.platforms.blinkit.public_data` owns it, and a Blinkit change gets fixed once.

Why it works this way — the 2026-08-22 incident:
  The previous version launched a Playwright driver and a Chromium PER KEYWORD, then
  did two full `page.goto`s waiting on `networkidle`. That cost 10-60s per keyword and
  made Blinkit see a dozen cold clients hitting the same search from one IP within
  minutes. Eight of twelve keywords were lost to `Page.goto` timeouts and run time
  climbed 87s → 524s across four runs. `networkidle` is also a fragile wait by nature:
  it needs 500ms of total network silence, which a page with analytics may never reach.

There is deliberately NO DOM fallback. It could not read `ads_campaign_id`, so every
product it returned was flagged `is_ad: false` — which `match_position` can only ever
read as "organic-only → skip". It never once produced a usable bid decision.
"""
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from app.utils.logger import logger
from scraper.platforms.blinkit.public_data import endpoints as ep
from scraper.platforms.blinkit.public_data.scraper import in_page_fetch

# Default: Bengaluru MG Road / Shivajinagar dark store
_DEFAULT_LAT = 12.9767
_DEFAULT_LON = 77.5713

_TAG = "cm.pos"

# One search page is 12 products. Positions past ~40 are far below anything worth
# bidding for, and each extra page is another request against the same rate limit.
_MAX_PRODUCTS = 48


def _log(keyword: str | None = None):
    """Logger bound to this scraper (and the keyword, so one keyword's story can be
    followed through a run that interleaves a dozen of them)."""
    return logger.bind(tag=f"{_TAG}[{keyword}]" if keyword else _TAG)


# ── Session (one per run) ────────────────────────────────────────────────────

async def open_session(pw, lat: float = _DEFAULT_LAT, lon: float = _DEFAULT_LON) -> dict:
    """Launch the consumer-side browser and capture Blinkit's session-bound search
    headers. Returns a session dict; the caller closes it with `close_session`.

    The warm-up is two navigations ONCE per run — the homepage to establish the location
    context, then a throwaway search so the browser fires its own `/v1/layout/search` and
    we can read the headers off it. Everything after this is a bare fetch.

    `headers` is empty if the capture failed; `search` then reports the failure per
    keyword rather than silently returning nothing.
    """
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()

    captured: dict = {}

    def _on_req(req):
        if ep.SEARCH_PATH in req.url and not captured:
            captured.update(req.headers)

    page.on("request", _on_req)
    try:
        for url, wait in ((ep.HOMEPAGE_URL.format(lat=lat, lon=lon), 1000),
                          (ep.WARMUP_SEARCH_URL, 1500)):
            try:
                await page.goto(url, wait_until="networkidle", timeout=20_000)
                await page.wait_for_timeout(wait)
            except Exception as e:
                # Not fatal on its own: the headers may already have been captured by the
                # first navigation, and `search` reports it properly if they weren't.
                _log().debug(f"warm-up navigation failed ({url}): {e}")
    finally:
        page.remove_listener("request", _on_req)

    headers = {k: captured[k] for k in ep.SEARCH_HEADER_KEYS if k in captured}
    if headers:
        _log().debug(f"session ready — {len(headers)} search headers captured")
    else:
        _log().error("no search headers captured — position lookups will fail this run")

    return {"browser": browser, "context": context, "page": page, "headers": headers}


async def close_session(session: dict) -> None:
    """Tear the session down. Never raises — a teardown failure must not fail a run."""
    for key in ("context", "browser"):
        obj = (session or {}).get(key)
        if obj is not None:
            try:
                await obj.close()
            except Exception:
                pass


# ── Search ───────────────────────────────────────────────────────────────────

def _parse_snippets(snippets: list, start_rank: int) -> list[dict]:
    """Blinkit search snippets → [{position, name, is_ad, pid}]. Pure."""
    out: list[dict] = []
    for sn in snippets:
        if not isinstance(sn, dict):
            continue
        d = sn.get("data") or {}
        if not isinstance(d, dict):
            continue

        # blinkit wraps product name as {"text": "Product Name"}
        name_raw = d.get("name") or {}
        name = (
            (name_raw.get("text") if isinstance(name_raw, dict) else str(name_raw)) or ""
        ).strip()
        if not name or len(name) <= 2:
            continue

        pid = str((d.get("identity") or {}).get("id") or "").strip()

        # A non-empty ads_campaign_id is what makes a slot sponsored. This is the ONLY
        # place the sponsored flag comes from, which is why there is no DOM fallback.
        common = (sn.get("tracking") or {}).get("common_attributes") or {}
        ads_campaign_id = str(common.get("ads_campaign_id") or "").strip()
        is_ad = bool(ads_campaign_id and ads_campaign_id not in ("0", "null", "None"))

        out.append({
            "position": start_rank + len(out),
            "name": name[:100],
            "is_ad": is_ad,
            "pid": pid,
        })
    return out


async def search(session: dict, keyword: str, lat: float = _DEFAULT_LAT,
                 lon: float = _DEFAULT_LON) -> list[dict]:
    """Search `keyword` at the store serving (lat, lon).

    The store comes from the lat/lon HEADERS, so switching location costs nothing —
    no navigation, no new context, no re-warm-up.

    Raises RuntimeError when the search could not be performed (no captured headers, or
    the request never returned 200 after retries). That is deliberate: the bid loop must
    tell "we looked and our ad wasn't there" (empty list → skip) apart from "we couldn't
    look" (raise → error row), because the first is a normal outcome and the second is a
    fault that should be visible.
    """
    log = _log(keyword)
    headers = session.get("headers") or {}
    if not headers:
        raise RuntimeError("no Blinkit search headers captured for this session")
    headers = {**headers, "lat": str(lat), "lon": str(lon)}

    products: list[dict] = []
    url: str | None = ep.first_search_url(keyword)
    body: dict | None = ep.SEARCH_BODY

    while url and len(products) < _MAX_PRODUCTS:
        resp = await in_page_fetch(session["page"], url, headers, body)
        if resp.get("status") != 200 or resp.get("body") is None:
            if products:
                # Page 1 worked; a later page failing just truncates the list. The ad we
                # care about ranks near the top, so this is still a usable answer.
                log.warning(f"paging stopped at {len(products)} products "
                            f"(HTTP {resp.get('status')})")
                break
            detail = resp.get("error") or f"HTTP {resp.get('status')}"
            raise RuntimeError(f"search request failed: {detail}")

        data = resp["body"]
        snippets = (data.get("response") or {}).get("snippets") or []
        if not snippets:
            break
        products.extend(_parse_snippets(snippets, start_rank=len(products) + 1))

        # Blinkit returns genuine matches as `basic`, then pads with loosely-related
        # `similarity` items. Our sponsored slot is never in the padding, so following it
        # would spend extra requests against the same rate limit for nothing.
        url, method = _next_page(data)
        if method and method != ep.BASIC_SEARCH_METHOD:
            break
        body = None                      # only the offset-0 request carries a body

    ads = sum(1 for p in products if p["is_ad"])
    log.debug(f"{len(products)} products ({ads} sponsored) @ ({lat},{lon})")
    return products


def _next_page(data: dict) -> tuple[str | None, str | None]:
    """(next_url, search_method) — mirrors the public scraper's `_pagination`. The response
    carries its own continuation link rather than an offset we compute, and the method
    lives in that link's QUERY STRING, not as a field beside it."""
    resp = data.get("response") or {}
    next_url = (resp.get("pagination") or {}).get("next_url")
    if not next_url:
        return None, None
    method = (parse_qs(urlparse(next_url).query).get("search_method") or [None])[0]
    return next_url, method


# ── Standalone convenience (ad-hoc single lookup) ────────────────────────────

async def get_live_positions(
    keyword: str,
    lat: float = _DEFAULT_LAT,
    lon: float = _DEFAULT_LON,
) -> list[dict]:
    """One-shot lookup with its own browser — fine for a single ad-hoc check. A caller
    with several keywords should open one session and reuse it, or it pays the warm-up
    (two navigations) per keyword instead of once per run."""
    async with async_playwright() as pw:
        session = await open_session(pw, lat, lon)
        try:
            return await search(session, keyword, lat, lon)
        finally:
            await close_session(session)
