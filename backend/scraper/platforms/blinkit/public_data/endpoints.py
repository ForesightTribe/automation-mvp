"""Blinkit public search — endpoints, request constants, and tunables.

House rule: all URLs / header keys / request bodies for the public scraper live
here, never inline in scraper.py.
"""
from urllib.parse import quote

BASE_URL = "https://blinkit.com"
SEARCH_PATH = "/v1/layout/search"

# Homepage with lat/lon establishes Blinkit's location context (resolves the
# dark store serving that point). Warmup search makes the browser fire its own
# /v1/layout/search so we can capture the session-bound headers.
HOMEPAGE_URL = BASE_URL + "/?lat={lat}&lon={lon}"
WARMUP_SEARCH_URL = BASE_URL + "/s/?q=water"

# First-page search request body. Paged requests (via next_url) send no body.
SEARCH_BODY = {"applied_filters": None, "sort": ""}

# Session-bound headers Blinkit attaches to its own search request. We capture
# these from the live browser request and replay them via in-page fetch(), so
# Cloudflare sees a request from the real (already-cleared) session.
SEARCH_HEADER_KEYS = (
    "accept", "accept-language", "app_client", "app_version", "auth_key",
    "content-type", "device_id", "session_uuid", "web_app_version",
    "rn_bundle_version", "lat", "lon", "access_token",
)

# Blinkit returns genuine matches with search_method="basic", then pads with
# loosely-related items ("similarity"). Stop paging when it switches.
BASIC_SEARCH_METHOD = "basic"

# One Blinkit results page. A cap that is not a multiple of it fetches a last page only
# to throw part of it away — `cli sync` warns about such caps (scraper/public/caps.py).
PAGE_SIZE = 12

# Max products to collect per (keyword, location). One Blinkit page is 12.
# FLOOR ONLY — the real knob is the tenant's `keyword_cap` (config workbook), which
# takes precedence; this applies to tenants that set none, and to the ad-hoc CLI.
# Must stay well above 12: non-express tiers are interleaved by rank and surface
# deep (longtail first appeared at rank 24-29 for a brand keyword), so a cap of 12
# makes an unconfigured tenant structurally blind to every store but express.
RESULT_CAP = 48

# Cap for the brand-query targeted scrape — searches a tenant's brand name to
# pull its whole catalog at a store. Set well above a realistic brand SKU count
# so the full catalog is captured, but bounded so a huge brand can't run away.
BRAND_RESULT_CAP = 60

# Hard ceiling on pages followed per search. Ceiling only — the cap is what normally
# stops paging (60 products = 5 pages; 10 leaves room for the similarity tail, which
# overlaps what was already seen). It exists because Blinkit's next_url cannot be
# trusted to end: Shillong store 47298 answered "dobra" with one product and a next_url
# pointing back at offset=0, forever, and one such store hung a 2059-store run.
MAX_PAGES = 10

# ── Blocks (Cloudflare) ───────────────────────────────────────────────────────
# Until 2026-10-02 a Blinkit block was not recognised as one: `in_page_fetch` re-sent
# the request three more times within ~5 s (0.5 / 1.5 / 3), then the search counted as
# an ordinary failure. A "too many requests" answer was met with more requests, and
# two of them skipped the rest of the store. How each kind is now met is
# `scraper.block_remedy`:
#
#     rate        HTTP 429                      wait, SAME session
#     challenge   a Cloudflare page, not JSON   NEW session (the clearance is stale)
#                 ("Just a moment", "Attention Required", "Access denied")
#     forbidden   HTTP 403 with a JSON body     wait, then a new session
#
# ⚠️ UNMEASURED. Zepto's numbers came from a week of experiments; these are cautious
# starting points. Every block is now recorded with its kind (the staging file's
# `blocks` table) — tune these from that, not from guesses.
RATE_PAUSE_S = 30.0
FORBIDDEN_PAUSE_S = 60.0
RECOVERY_WAITS_S = (30, 60, 120, 180)    # the 2nd, 3rd, 4th+ block in a row
# A worker that sees nothing but blocks for this long stops; the run ends `partial`
# and --resume continues it. Same reasoning as Zepto: half an hour of nothing else is
# a wall, not a rate limit.
BLOCK_GIVE_UP_S = 30 * 60
BLOCK_KINDS = frozenset({"rate", "challenge", "forbidden"})


def first_search_url(keyword: str) -> str:
    """The offset-0 search request for a keyword."""
    return f"{BASE_URL}{SEARCH_PATH}?q={quote(keyword)}&search_type=type_to_search"
