"""Instamart Brand Portal (partner.instamart.in) private-data endpoints.

Every URL and static key for the Brand Portal scrape (sales and ads) lives
here, nowhere else — the same rule the Zepto and Blinkit modules follow.

All of it was verified against the live Brik Oven account on 2026-09-22.

TWO THINGS MAKE THIS MARKETPLACE UNUSUAL
========================================

**1. Every data call is signed.** `brand-portal-service` rejects any request
without a valid per-request `x-signature` (403 "PermissionDenied … Please
reload the browser"). The signature is an HMAC produced by a WebAssembly module
the portal ships. We reproduce it in pure Python — see signer.py.

**2. The signature is not enough; the request must come from the browser.**
A plain httpx call carrying a VALID signature, the full browser header set and a
live token still gets 403, while the identical request issued from inside the
logged-in page returns 200. The edge gates on something transport-level (TLS /
HTTP2 fingerprint), not on the signature. So a Playwright page is the transport
(session.py) while Python stays the brain: we build the body, choose the date
range and compute the signature ourselves, and never touch the UI.

THE SALES PIPELINE (3 signed calls + 1 plain download)
======================================================
    1. POST /api/v1/sales/report    ask for a report   -> long-running operation
    2. POST /api/v1/sales/reports   poll the list      -> STATUS_COMPLETED + url
    3. GET  <presigned S3 url>      the xlsx itself    -> NO auth, NO signature
    4. parse the two sheets         -> instamart_seller_store_daily
                                       instamart_brand_city_daily

The report is the ONLY source of per-store sales: its grain is
day x store(pod) x item, and `store_id` is the same podId the public scraper
stores as `search_listings.merchant_id`. The Sales Dashboard API cannot go below
city level, so it is not a substitute (it does carry SOV / market share / CTR /
CVR / unique users, which the report lacks — a later addition, not needed here).
"""
from pathlib import Path

PORTAL = "https://partner.instamart.in"
DATA = "https://brand-portal-service-http.swiggy.com"

LOGIN_PATH = "/login"
# The transport page must NOT be a page that polls the endpoints we call: on
# /instamart/reports the app polls /sales/reports itself, and our call then
# intermittently comes back 403 "Please reload the browser". Sales Dashboard
# boots the same data client without touching the reports list.
TRANSPORT_PATH = "/instamart/sales-insights"

# The portal answers a perfectly-signed call with 403 "… Please reload the
# browser" when signed calls arrive in a burst: the same request that fails
# immediately after a run succeeds a minute later, from the same session and
# page, with the same signature shape. So it is throttling, not a bad signature.
# Back off and retry rather than treating it as fatal.
# Measured 2026-09-22: whichever signed call goes first succeeds and the next
# one seconds later is refused, while a single call in a fresh run always
# succeeds — a token bucket with a slow refill, per account. Seconds are not
# enough; give it tens of seconds.
SIGNED_RETRY_WAITS_S = (60, 120, 240)
# Space out our own calls so we do not drain the bucket in the first place.
SIGNED_CALL_GAP_S = 20.0
# The report is never ready instantly; polling straight after asking just burns
# a signed call against the throttle.
POLL_INITIAL_WAIT_S = 75

# ── Data calls ───────────────────────────────────────────────────────────────
SALES_REPORT = "/api/v1/sales/report"        # singular: CREATE a report
SALES_REPORTS = "/api/v1/sales/reports"      # plural: LIST reports
CAMPAIGNS = "/api/v1/campaigns"              # list + per-campaign lifetime metrics
ADVERTISER_METRICS_BATCH = "/api/v1/advertiser/metrics/batch"  # account-wide, DIMENSION_TYPE_DAY
ADVERTISER_METRICS = "/api/v1/advertiser/metrics"              # product / keyword x campaign x day
PRODUCTS_BATCH = "/api/v1/products/batch"    # product name + images by candidate id

# The data client identifies itself as 1.4.136. This exact string is part of the
# signed message, so it must match the `app_version` header byte for byte.
APP_VERSION = "1.4.136"
DATA_CLIENT_ID = "IM_ADS_EXTERNAL_DASHBOARD"
USER_POOL = "USER_POOL_BRAND"

# ── The signer ───────────────────────────────────────────────────────────────
# TWO wasm binaries ship, one per client, with DIFFERENT baked-in keys:
#   host client  (app_version 0.0.41)  brand-portal-client/27fe09e17c98e205daa3.wasm
#   DATA client  (app_version 1.4.136) brand-portal-client/instamart/<hash>.wasm
# Only the second one signs the calls below. Using the host's silently produces
# well-formed but wrong signatures — which is exactly what a 403 looks like.
SIGNER_WASM_URL = (
    "https://instamart-media-assets.swiggy.com/brand-portal-client/instamart/"
    "779142c50801f328b965.wasm"
)
# Cached next to the module on first use; delete the file to re-fetch. If Swiggy
# rebuilds the bundle this URL 404s — recover the new one from a logged-in page
# (it is the only .wasm fetched under .../brand-portal-client/instamart/).
SIGNER_CACHE = Path(__file__).parent / "_signer_cache" / "im_data_signer.wasm"

# ── Report request ───────────────────────────────────────────────────────────
# dimensions of the xlsx: one row per day x store x item.
REPORT_DIMENSIONS = ["DIMENSION_DAY", "DIMENSION_POD", "DIMENSION_SPIN"]
REPORT_METRICS = ["METRIC_GMV", "METRIC_UNITS_SOLD"]
BRAND_ACCOUNT_FILTER = "FILTER_BRAND_ACCOUNT_ID"
OPERATOR_EQUAL = "COMPARISON_OPERATOR_EQUAL"
# The portal refuses ranges longer than this, and deletes reports after 24 h.
MAX_REPORT_DAYS = 31

# ── Polling ──────────────────────────────────────────────────────────────────
STATUS_COMPLETED = "STATUS_COMPLETED"
STATUS_FAILED = "STATUS_FAILED"
POLL_INTERVAL_S = 60
POLL_TIMEOUT_S = 900          # generous: the throttle costs more time than the build does
REPORTS_PAGE_SIZE = 12

# ── Ads ──────────────────────────────────────────────────────────────────────
# /campaigns: `pagination_context.offset` is a 1-based PAGE NUMBER (see
# scraper.fetch_campaigns), and a page shorter than this is the last one.
CAMPAIGNS_PAGE_SIZE = 50
# /advertiser/metrics: one page only — the offset does not advance past it
# (see scraper.ASSET_CHUNK_DAYS for how wide ranges are split instead).
ASSET_PAGE_SIZE = 500
IMAGE_CDN_PREFIX = "https://media-assets.swiggy.com/swiggy/image/upload/fl_lossy,f_auto,q_auto,w_200/"

# ── Browser session ──────────────────────────────────────────────────────────
# A real click-through login is required at least once: injecting only
# localStorage logs the shell in but leaves data calls unsigned (403). The
# cookies a genuine login sets are what make the app sign. The saved state is
# reused until it stops working, then we log in again.
# The OTP boxes are React inputs (otp1..otp6, maxlength=1). `fill()` leaves the
# component's own state empty, so the code must be TYPED as keystrokes.
OTP_TYPE_DELAY_MS = 140
EMAIL_INPUT = "#email-input"
OTP_BOX = 'input[maxlength="1"]'
SEND_OTP_LABELS = ["Send OTP", "Get OTP", "Continue"]
SUBMIT_LABELS = ["Login", "Verify", "Submit"]
NAV_TIMEOUT_MS = 60_000
SETTLE_MS = 6_000
