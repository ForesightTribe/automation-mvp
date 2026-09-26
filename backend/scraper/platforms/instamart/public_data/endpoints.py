"""Instamart public search — endpoints, request shapes, and tunables.

House rule (same as Blinkit and Zepto): every URL, path, body template, header
and pacing number lives here. The scraper and parser hold no literals.

HOST MATTERS. Everything here is on instamart.in. The same paths on swiggy.com
sit behind AWS WAF and answer 202 with an empty body — the previous version of
this package targeted swiggy.com/dapi and never returned a product. Verified
2026-09-08 (dark-store work) and again 2026-09-17 (this rewrite).

Everything below was measured against the live site on 2026-09-17 from a real
Chromium session at Bengaluru store 1388682: 40 search calls, all 200. The
per-item field notes come from a full page-0 capture of "sourdough" (32 items)
and of the brand query "brik oven" (4 items).
"""

BASE_URL = "https://www.instamart.in"
HOME_URL = BASE_URL + "/"

# ── Session ───────────────────────────────────────────────────────────────────
# The location is a cookie. Set it, load the homepage, and the bootstrap state
# carries the dark store that serves that point. The FIRST page load of a fresh
# context never resolves a store, so a warm-up load precedes the first probe.
LOCATION_COOKIE = "userLocation"
COOKIE_DOMAIN = ".instamart.in"
BOOTSTRAP_VAR = "window.___INITIAL_STATE___"
STORE_ID_RE = r'"storeId"\s*:\s*"?([0-9]+)"?'

# Plain headless Chromium gets 403; the AutomationControlled flag is required.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/536.36")
VIEWPORT = {"width": 498, "height": 728}
EXTRA_HEADERS = {"Accept-Language": "en-IN,en;q=0.9"}
# A warm-up page is ~150k characters; a bot-gate page is a few thousand.
WARM_PAGE_MIN_CHARS = 50_000

# ── Search ────────────────────────────────────────────────────────────────────
# POST, JSON body, store binding in the QUERY STRING. Pages are indexed 0,1,2,…
# and the index travels twice: `offset` in the URL and `search_results_offset`
# (a string) in the body. They must move together.
SEARCH_PATH = "/api/instamart/search/v2"
LAYOUT_ID = "4987"
# What the page sends for a typed search. The suggest-box path sends
# "INSTAMART_AUTO_SUGGEST_PAGE"; both return the same results.
PAGE_TYPE = "INSTAMART_SEARCH_PAGE"
SEARCH_BODY = {
    "facets": [],                 # NEVER set: a brand facet would hide competitors
    "is_pre_search_tag": False,
    "page_type": PAGE_TYPE,
    "query": "",
    "search_results_offset": "0",
    "sortAttribute": "",          # NEVER set: any sort destroys the rank we measure
}

# Transport — the one thing that is NOT like Zepto. Playwright's
# `context.request.post` gets a hard 404 (the SPA shell, 288 KB of HTML). Only a
# fetch() issued from inside the page works: it carries the WAF cookie and
# whatever fingerprint the gate checks. So every search is `page.evaluate` of
# this function. The `matcher` header the page adds to its own requests is NOT
# validated (removed it → 200, 32 items), so no header capture is needed.
IN_PAGE_POST = """async ([path, body]) => {
  const r = await fetch(path, {method: 'POST',
      headers: {'content-type': 'application/json', 'accept': '*/*'},
      body: JSON.stringify(body), credentials: 'include'});
  return {status: r.status, body: await r.text()};
}"""


def search_url(offset: int, store_id: str, secondary_id: str = "") -> str:
    """Path for one page. `secondary_id` (the backup store that can also serve the
    point) may be left blank — the page's own first search sends it blank and the
    results are still bound to the primary."""
    return (f"{SEARCH_PATH}?offset={offset}&ageConsent=false&layoutId={LAYOUT_ID}"
            f"&voiceSearchTrackingId=&storeId={store_id}&primaryStoreId={store_id}"
            f"&secondaryStoreId={secondary_id}")


def search_body(query: str, offset: int) -> dict:
    return {**SEARCH_BODY, "query": query, "search_results_offset": str(offset)}


# ── Response shape ────────────────────────────────────────────────────────────
# data.cards[] is an ordered list of widgets. The first is the filter widget
# (carries `resultCount` and the brand facet); the rest are GridWidgets, each with
# gridElements.infoWithStyle.items[] — 2 items per card. Global rank = walk the
# cards in order. `analytics.position` on an item is its slot WITHIN the card
# (0 or 1) and must not be used as a rank.
GRID_ITEMS_PATH = ("gridElements", "infoWithStyle", "items")
RESULT_COUNT_KEY = "resultCount"

# Ads: three independent markers agree on every sponsored item —
#   badges[].type == AD_BADGE, adTrackingContext != "", and
#   analytics.impressionObjectName == "item-impression-ad".
# The badge is the flag; the tracking context carries adslot / cid / kw.
AD_BADGE = "BADGE_TYPE_AD"
BESTSELLER_BADGE = "BADGE_TYPE_BEST_SELLER"

# Each item is tagged HIGH_CONFIDENCE or LOW_CONFIDENCE (analytics.extraFields.
# searchResultType) — Blinkit's basic→similarity boundary, but per item, and LOW
# items appear from page 0. Kept in `extra` so a consumer can drop the tail.
CONFIDENCE_HIGH = "HIGH_CONFIDENCE"

# Which store actually served an item: variations[].podId. Usually the primary,
# but the secondary can fill in — attribute by podId, never by the request.
POD_ID_KEY = "podId"

# Paging end signal: `pageOffset.nextOffset` is None (JSON null) — NOT "" and
# NOT a missing key. Seen on the brand query (4 results). Keyword searches never
# reached it in 8 pages: `nextOffset` kept incrementing while the pages returned
# the same ~42 items with 0-2 new ones each. Never page towards `resultCount`.
NEXT_OFFSET_PATH = ("pageOffset", "nextOffset")

# Prices are whole rupees in `units` (mrp 110 = Rs 110), with a `nanos` field
# that was 0 in every captured row. Not paise — Zepto's divisor does not apply.
PRICE_DIVISOR = 1

# ── Pacing ────────────────────────────────────────────────────────────────────
# 30 calls at 1.0 s across 6 keywords x 2 stores: 30/30 OK, avg 0.78 s, no 202,
# no 429. That is a light probe, not a volume test — the dark-store MAPS
# endpoints imposed an IP quota with hour-long holds after ~10k calls in a day,
# and search has not been driven that hard yet. Measure on the first full run
# (147 stores x 9 keywords ≈ 1,300 calls) before touching these.
SEARCH_GAP_S = 1.0
STORE_GAP_S = 0.0
FETCH_TIMEOUT_S = 25.0
RETRY_DELAYS = (1.0, 2.0)      # transport failures only; a block is never retried here

# The AWS WAF pass (`aws-waf-token` cookie). Unlike Zepto, the page renewed it
# on its own between two captures 9 minutes apart — but a session that sits on
# one page for hours has not been observed, so re-navigate on a timer anyway.
PASS_REFRESH_S = 240.0

# Blocks: none observed yet. These mirror Zepto's until Instamart's are measured.
PROBE_EVERY_S = 60
RECOVERY_WAITS_S = (60, 60, 120, 180)
PAUSE_EVERY = None
PAUSE_S = 0

# One worker until the limiter is measured. Zepto's is per connection (4 workers
# = 1.02x of 1); Blinkit's is per session-open. Which model Instamart follows is
# the first thing the first full run tells us. Raising this without that number
# would repeat the Zepto mistake of 4x the requests for nothing.
WORKERS = 1
MAX_WORKERS = 1

# ── Result caps ───────────────────────────────────────────────────────────────
# Page 0 is 32 items. Pages overlap massively (49 distinct products across 8
# pages of ~42; page 2 added ZERO new ones), so page 0 is the result set for
# share-of-voice — Zepto stops at 30, Blinkit at 48. DEDUPE BY productId IS
# MANDATORY at any depth. Raise per tenant via `keyword_cap` if a head term
# genuinely fills page 1.
RESULT_CAP = 32
# Brand query: the whole own catalog at a store, which is small (Brik Oven: 4
# SKUs, `nextOffset` null after page 0). The cap is a ceiling, not a target.
BRAND_RESULT_CAP = 60
MAX_PAGES = 3

# ── Status codes ──────────────────────────────────────────────────────────────
CHALLENGE_STATUS = 202     # AWS WAF — per-session; re-mint the pass
RATE_STATUS = 429          # too fast — self-clearing
# 404 on the search path is not "no results": it is what a request WITHOUT the
# in-page fingerprint gets (see IN_PAGE_POST). Treat as a transport bug.
BLOCK_STATUSES = frozenset({202, 401, 403, 429, 503})
