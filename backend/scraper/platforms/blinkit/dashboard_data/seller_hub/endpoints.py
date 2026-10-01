BASE_URL = "https://seller.blinkit.com"

# ── Page URLs ─────────────────────────────────────────────────────────────────
# Navigated for real (not fetched directly) — this domain's Cloudflare bot
# management blocks a bare httpx/fetch call even with valid cookies/headers
# replayed (confirmed in platform_auth/marketplaces/blinkit/seller_new.py,
# Phase B, 2026-09-30). The SPA's own in-page requests are what carries the
# auth headers these endpoints need.
SALES_PERFORMANCE_PAGE = "/dashboard/performance?performance=sales_performance"

# ── Sales API endpoints (response URLs, matched by substring) ──────────────────
SALES_METRICS_PATH = "seller-hub/api/sales/performance/metrics"
SALES_BY_PRODUCT_PATH = "seller-hub/api/sales/products/performance"
