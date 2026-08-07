"""Zepto public search — endpoints, request constants, and tunables.

House rule: all URLs / header keys / request bodies for the public scraper live
here, never inline in scraper.py.

Every value below is from the Phase 0 recon; the captured traffic that justifies
it is in api.txt, and the reasoning is in docs/zepto_phase0_handover.md.
"""
import json

BASE_URL = "https://www.zepto.com"
BFF_BASE = "https://bff-gateway.zepto.com"

SEARCH_PATH = "/user-search-service/api/v3/search"
GET_PAGE_PATH = "/lms/api/v2/get_page"

# Homepage establishes the browser session Zepto binds its headers to. Unlike
# Blinkit, NO lat/lon goes here — Zepto ignores coordinates on search entirely
# (Q2) and binds by store id header instead, so the homepage only exists to get
# a session issued.
HOMEPAGE_URL = BASE_URL
# Makes the browser fire its own /search so the session-bound headers can be
# captured from a real request rather than guessed.
WARMUP_SEARCH_URL = BASE_URL + "/search?query=bread"

# First-page search body. `query` and `pageNumber` are overwritten per request;
# the rest is replayed as the browser sent it.
SEARCH_BODY = {"query": "", "pageNumber": 0, "mode": "SHOW_ALL_RESULTS"}

# Headers Zepto attaches to its own search request. Captured from the live
# browser and replayed. Most are session/device values that go stale, which is
# why they are captured rather than hardcoded.
SEARCH_HEADER_KEYS = (
    "accept", "accept-language", "content-type", "origin", "referer",
    "user-agent", "app_version", "appversion", "platform", "tenant",
    "device_id", "deviceid", "session_id", "sessionid", "x-without-bearer",
    "store_id", "storeid", "store_ids", "store_etas",
)

# Headers dropped when replaying a captured request — the transport sets these
# itself and copying them corrupts the request.
DROP_HEADER_KEYS = frozenset({
    "host", "content-length", "connection", "accept-encoding",
    ":method", ":path", ":authority", ":scheme",
})

# ── Store binding (Q2) ────────────────────────────────────────────────────────
# THE critical fact about this platform. A search is bound to a store purely by
# these four headers. lat/lon in the body is accepted and SILENTLY IGNORED — send
# a coordinate and you get a valid 200 carrying a generic catalog, which is the
# failure mode docs/zepto.md warned about. Proven: coordinates gave four test
# stores the identical catalog; these headers gave 4/4 correct.
#
# `store_ids` is the primary id PLUS that store's secondaries, comma-joined.
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


# ── Response shape (Q6, Q7) ───────────────────────────────────────────────────
# Products live at layout[].data.resolver.data.items[] on widgets whose
# widgetId is PRODUCT_GRID. There may be SEVERAL such widgets in one response.
PRODUCT_GRID_WIDGET = "PRODUCT_GRID"

# A search response is NOT just its PRODUCT_GRIDs. The layout is sectioned, and
# a HEADER_WIDGET titled "Similar Products" starts a recommendation carousel that
# the page renders as a separate block:
#
#   TITLE_WIDGET        "Showing results for sourdough"
#   PRODUCT_GRID x4     <- the real results
#   OOS_SEARCH_WIDGET   "Some items are temporarily out of stock"
#   HEADER_WIDGET       "Similar Products"      <- BOUNDARY
#   PRODUCT_GRID x3     <- recommendations, NOT ranks 12-20
#
# Collecting past that boundary invents ranks: it produced positions of 41, 48
# and 66 for a search whose real result set was 11 items, and made a brand look
# absent from the top of a page it was actually near the top of. Stop here.
SECTION_BREAK_WIDGETS = frozenset({"HEADER_WIDGET"})

# Zepto sends "layout": null — NOT [] — on a page past the end of the results.
# The key is PRESENT, so `data.get("layout", [])` returns None and iterating it
# raises. Always `data.get("layout") or []`. This cost two days: the exception was
# swallowed and reported as a rate-limit block, so healthy stores looked throttled
# and their already-fetched products were discarded.
LAYOUT_KEY = "layout"

# Prices are in PAISE. mrp 11000 = Rs 110.00.
PRICE_DIVISOR = 100

# No basic->similarity relevance switch (Q6), so there is no equivalent of
# Blinkit's BASIC_SEARCH_METHOD stop condition. Paging stops on an empty page.
BASIC_SEARCH_METHOD = None

# ── Tunables ──────────────────────────────────────────────────────────────────
# Observed page size is 12-27, so one page never fills the cap and 2-3 requests
# per search is normal. Kept well above a page for the same reason as Blinkit:
# a low cap makes a tenant structurally blind to deep placements, and Brik Oven
# was observed at ranks 27-36 on `mozzarella`.
RESULT_CAP = 48
BRAND_RESULT_CAP = 60
MAX_PAGES = 3

# ── Rate limiting (Q10) ───────────────────────────────────────────────────────
# Zepto is NOT Blinkit here, and the difference drives every setting below.
# Blinkit has transient 403/429s that self-resolve on backoff. Zepto enforces a
# per-IP VOLUME cap: measured on a residential IP, blocks land after
#     0.4s pacing -> 1 search     6s -> 47      12s -> 137
# and the ceiling drains across a day (137 -> 86 -> 65) refilling over ~12 hours.
#
# Retry-and-refresh, the Blinkit remedy, does not help: rotating session headers
# lost 22.0% and a wholly new browser identity 22.5%. The limit tracks the IP.
#
# HTTP 299 is Zepto's non-standard throttle signal. Treat it as a block, never as
# an empty result — retrying into it prolongs the block.
# 299 is Zepto's own non-standard throttle code. 202 is the subtler one: an
# "Accepted" with no results, returned in clusters once the IP is tired. Treated
# as a plain failure it is worse than a block — the worker does NOT back off, so
# five workers hammer a throttled endpoint, fail in milliseconds, and burn through
# the store list recording nothing. Observed doing exactly that across 14 stores.
BLOCK_STATUSES = frozenset({202, 299, 401, 403, 429})

SEARCH_GAP_S = 12.0        # between searches, per worker. 6s was tested and is
                           # SLOWER end to end: a hard block costs more than a
                           # scheduled pause.
STORE_GAP_S = 3.0
FETCH_TIMEOUT_S = 20.0
RETRY_DELAYS = (1.0, 2.0)  # more just feeds an active block

# Rest BEFORE the wall, not into it: recovery from a hard block yields ~3
# searches per 5-minute cycle, while a clean pause resets the window properly.
# Set from each run's observed block points, not guessed — the ceiling moves.
PAUSE_EVERY = 110
PAUSE_S = 900

# On a block, PROBE rather than sleep blind. Measured recovery is ~5 minutes, so
# a fixed 15-minute sleep wastes 10 minutes of every block.
PROBE_EVERY_S = 300
RECOVERY_WAITS_S = (900, 1800, 2700, 3600)

# 5 concurrent workers on one IP measured 21.7 searches/min against a single
# worker's 5.0 — a full Bengaluru run went 11h -> 2.7h. The budget is shared, so
# workers drain it faster and block sooner; the net is still ~4x.
WORKERS = 5


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
