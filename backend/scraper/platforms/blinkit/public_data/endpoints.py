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


def first_search_url(keyword: str) -> str:
    """The offset-0 search request for a keyword."""
    return f"{BASE_URL}{SEARCH_PATH}?q={quote(keyword)}&search_type=type_to_search"
