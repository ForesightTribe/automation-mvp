"""Zepto public search — endpoints, request constants, and tunables.

House rule: all URLs / header keys / request bodies for the public scraper live
here, never inline in scraper.py.

EVERY TUNABLE BELOW IS MEASURED, NOT INFERRED
---------------------------------------------
The previous version of this file was built on a per-IP VOLUME cap — ~137
searches then a ~12-hour cooldown — which does not exist. That model produced
12-second pacing, 15-minute scheduled rests, hour-long recovery sleeps and a
5-worker pool, and projected a national run at 62 hours.

Re-measured from scratch over 31-Aug-2026 (see
`zepto-cm-exp/public_scraper/JOURNAL.md`). The replacement was validated on a
real run: **169 stores x 9 keywords = 1,521 requests in 56.6 minutes, 100%
success, zero blocks, 29,125 rows.**

THERE ARE THREE FAILURE MODES, NOT ONE
--------------------------------------
The old `BLOCK_STATUSES` collapsed five statuses into one remedy — sleep. Two of
the three real mechanisms want the opposite:

    429  too fast, right now       connection-wide   clears ~60-80 s   slow down
    299  LOGIN_REQUIRED            connection-wide   clears ~60 s      pause, retry
    202  AWS WAF challenge         per session       NEVER clears      re-mint

`202` is the expensive one. A challenged session is dead permanently, so the old
code's response — wait up to an hour, then retry with the same dead session — can
never succeed. That single misclassification is enough on its own to make the
platform look like it has a 12-hour cooldown.
"""
import json

BASE_URL = "https://www.zepto.com"
BFF_BASE = "https://bff-gateway.zepto.com"

SEARCH_PATH = "/user-search-service/api/v3/search"
GET_PAGE_PATH = "/lms/api/v2/get_page"

# The homepage establishes the browser session Zepto binds its headers to, and is
# what mints the AWS WAF pass. No lat/lon here: Zepto ignores coordinates on
# search entirely and binds by store-id header instead.
HOMEPAGE_URL = BASE_URL
# Makes the browser fire its own /search so session-bound headers are captured
# from a real request rather than guessed.
WARMUP_SEARCH_URL = BASE_URL + "/search?query=bread"

SEARCH_BODY = {"query": "", "pageNumber": 0, "mode": "SHOW_ALL_RESULTS"}

# Headers the transport sets itself; copying them from a capture corrupts the
# request.
DROP_HEADER_KEYS = frozenset({
    "host", "content-length", "connection", "accept-encoding",
    ":method", ":path", ":authority", ":scheme",
})

# ── Store binding ─────────────────────────────────────────────────────────────
# THE critical fact about this platform. A search is bound to a store purely by
# these four headers. lat/lon in the body is accepted and SILENTLY IGNORED — send
# a coordinate and you get a valid 200 carrying a generic catalog.
#
# Re-verified 31-Aug on a 29,125-row run: `merchant_id` in every response matched
# the `store_id` requested, and the 169 stores returned different catalogs for the
# same keyword. Re-run that check whenever session or header logic changes; the
# failure is silent.
STORE_ID_HEADERS = ("store_id", "storeid")
STORE_IDS_HEADER = "store_ids"
STORE_ETAS_HEADER = "store_etas"


def store_headers(store_id: str, secondary_ids: tuple[str, ...] = ()) -> dict:
    """The four headers that bind a search to `store_id`."""
    all_ids = ",".join([store_id, *secondary_ids])
    h = {k: store_id for k in STORE_ID_HEADERS}
    h[STORE_IDS_HEADER] = all_ids
    h[STORE_ETAS_HEADER] = json.dumps({s: -1 for s in all_ids.split(",")})
    return h


# ── Response shape ────────────────────────────────────────────────────────────
PRODUCT_GRID_WIDGET = "PRODUCT_GRID"

# A search response is SECTIONED, and only the first section is the search. A
# HEADER_WIDGET titled "Similar Products" starts a recommendation carousel:
#
#   TITLE_WIDGET        "Showing results for sourdough"
#   PRODUCT_GRID x4     <- the real results
#   OOS_SEARCH_WIDGET   "Some items are temporarily out of stock"
#   HEADER_WIDGET       "Similar Products"      <- BOUNDARY
#   PRODUCT_GRID x3     <- recommendations, NOT ranks 12-20
#
# Collecting past that boundary invents ranks: it produced positions of 41, 48 and
# 66 for a search whose real result set was 11 items.
SECTION_BREAK_WIDGETS = frozenset({"HEADER_WIDGET"})

# Zepto sends "layout": null — NOT [] — on a page past the end of the results. The
# key IS present, so `data.get("layout", [])` returns None and iterating it raises.
# Always `data.get("layout") or []`.
LAYOUT_KEY = "layout"

# Prices are in PAISE. mrp 11000 = Rs 110.00.
PRICE_DIVISOR = 100

BASIC_SEARCH_METHOD = None   # no basic->similarity switch on Zepto

# ── Pack size ─────────────────────────────────────────────────────────────────
# Zepto supplies pack size STRUCTURED — `productVariant.packsize` (total content,
# already multiplied out) plus `unitOfMeasure` — at 100% fill. The free-text
# `formattedPacksize` ("1 pack (400 g)") is kept as `pack_raw` for audit, but it
# is NOT the source of size: `pack.py`'s grammar parses only 2.2% of it, whereas
# the structured fields cover ~100%.
#
# The one thing structured fields do NOT carry is the multipack multiplier, so
# `pack_count` still comes from the string ("50 x 20 g" -> 50, "150 ml X 2" -> 2).
# `productVariant.quantity` is NOT the count — it is stock, identical to
# `availableQuantity`; the same pack string shows 1, 3 and 7 on different rows.
UOM_MAP = {
    "GRAM": ("g", 1.0), "MILLIGRAM": ("g", 0.001), "KILOGRAM": ("g", 1000.0),
    "MILLILITRE": ("ml", 1.0), "MILLILITER": ("ml", 1.0),
    "LITER": ("ml", 1000.0), "LITRE": ("ml", 1000.0),
    "PIECE": ("pc", 1.0), "PIECES": ("pc", 1.0),
    # Zepto's own marker for a bundled product. Treated as a combo signal.
    "COMBO": ("", 1.0),
}
COMBO_UOM = "COMBO"

# ── Pacing ────────────────────────────────────────────────────────────────────
# Throughput vs pacing, 4-minute arms, riding through blocks:
#
#     pace   sent    ok   blocked   success
#      0.0  13648    83         0        1%   429 storm
#      0.5    406   111       100       27%
#      1.0    225    48         0       21%
#      2.0    107   106         0       99%   <- clean
#      4.0     57    57         0      100%
#      8.0     29    28         0       97%
#     12.0     20    20         0      100%
#
# 2 s is the fastest pacing that stays completely clean. Faster than ~1 req/s
# trips a genuine 429 limiter; slower than 2 s just wastes time linearly.
SEARCH_GAP_S = 2.0
# SEARCH_GAP_S already paces everything; a second gap between stores would only
# slow the run down.
STORE_GAP_S = 0.0
FETCH_TIMEOUT_S = 25.0

# There is NO volume quota. 14,279 requests were spent in one afternoon and the
# arms that ran AFTER all of them were the cleanest of the day. Scheduled rests
# exist only because the old model predicted a wall that is not there.
PAUSE_EVERY = None
PAUSE_S = 0

# Blocks clear on their own in about a minute. The old (900, 1800, 2700, 3600)
# ladder waited out a gate that was already gone.
GATE_PAUSE_S = 60.0        # after a 299
RATE_PAUSE_S = 30.0        # after a 429
PROBE_EVERY_S = 60
RECOVERY_WAITS_S = (60, 60, 120, 180)
RETRY_DELAYS = (1.0, 2.0)

# The AWS WAF pass (the `aws-waf-token` cookie) lives 4-6 minutes and NOTHING on
# the page refreshes it — `window.AwsWafIntegration` is absent. Re-mint on a timer
# rather than discovering death via a 202.
PASS_REFRESH_S = 240.0

# One worker. Measured: 1 worker 791 products/min, 4 workers 807 — a 1.02x return
# for 4x the requests, wasting 76% of them. The limiter is per connection, so
# parallelism inside one IP buys nothing. Scale with IPs, not workers.
WORKERS = 1
MAX_WORKERS = 1

# ── Result caps ───────────────────────────────────────────────────────────────
# One page. A page is ~30 products, and only 1.9% of Zepto own-brand placements
# sit past position 30 (measured across every stored row). A second page doubles
# the run to recover that 1.9%.
#
# Raise per tenant via `keyword_cap` — broad head terms genuinely fill page 2
# (`milk` returned 17 new products there), niche terms return 4-16 rows and never
# do. DEDUPE IS MANDATORY at any depth: page 0 alone carried 3 duplicates among
# 30 items, and page 1 repeated 29% of page 0.
RESULT_CAP = 30
BRAND_RESULT_CAP = 60      # brand scrape paginates the catalog; tuned in Phase 4
MAX_PAGES = 3              # ceiling only; RESULT_CAP is what normally stops paging

# ── Status codes ──────────────────────────────────────────────────────────────
GATE_STATUS = 299          # LOGIN_REQUIRED — shared, self-clearing
CHALLENGE_STATUS = 202     # AWS WAF — per-session, TERMINAL without a re-mint
RATE_STATUS = 429          # too fast — self-clearing

# Kept for callers that only need "was this a failure". The ENGINE must not use
# this set to decide a remedy — that is the bug this rewrite exists to fix.
BLOCK_STATUSES = frozenset({202, 299, 401, 403, 429, 503})


def search_url() -> str:
    """The search endpoint. Zepto pages via a body field, not a URL."""
    return f"{BFF_BASE}{SEARCH_PATH}"


def get_page_url(lat: float, lon: float, page_size: int = 3) -> str:
    """Coordinate -> serving store. Discovery only; the scrape path does not need
    it, because the catalog already holds every store id and calling it per store
    spends a SECOND, independently rate-limited budget for nothing."""
    return (f"{BFF_BASE}{GET_PAGE_PATH}?latitude={lat}&longitude={lon}"
            f"&page_type=HOME&version=v2&show_new_eta_banner=true"
            f"&page_size={page_size}&enforce_platform_type=WEB")


def search_body(keyword: str, page_number: int = 0, base: dict | None = None) -> dict:
    """Body for one search page, preserving any session fields the browser sent
    (e.g. userSessionId) from `base`."""
    body = dict(base or SEARCH_BODY)
    body.update(query=keyword, pageNumber=page_number, mode="SHOW_ALL_RESULTS")
    return body
