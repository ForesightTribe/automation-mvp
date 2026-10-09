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
# Lists this seller's filter options, including city_filter — the full city
# list for the per-city sales pass (confirmed live, 2026-10-01: 29 cities for
# Sereko; the UI's Cities dropdown reads from this same response).
SALES_FILTERS_PATH = "seller-hub/api/sales/performance/filters"

# A different endpoint family — the "Download sales sheet" order-level
# report. POST to start generating (report_type: SALES_SUMMARY), GET poll
# repeatedly until a document_url appears, then a plain (non-Blinkit) S3
# download for the real file. See scraper.fetch_sales_order_report.
REPORTS_DOWNLOAD_PATH = "seller-hub/api/reports/download"
REPORTS_POLL_PATH = "seller-hub/api/reports/poll"

# ── Inventory (Inventory → "Stock on hand" tab) ───────────────────────────────
# GET, query string only. `view` lists every item with its sellable stock split
# warehouse / darkstore / in-between (+ unsellable, incoming). Unfiltered, the
# numbers are all-warehouse totals; with `warehouse_ids=<id>` they are THAT
# warehouse's own figures (confirmed live 2026-10-09 for Sereko: 1164 sellable
# in total = 475 Bengaluru B5 + 239 Kundli + ...). `page_size=50` is honoured
# (the UI asks for 5). `filters` lists the account's warehouses.
INVENTORY_VIEW_PATH = "seller-hub/api/inventories/v1/view"
INVENTORY_FILTERS_PATH = "seller-hub/api/inventories/v1/filters"
INVENTORY_PAGE_SIZE = 50
