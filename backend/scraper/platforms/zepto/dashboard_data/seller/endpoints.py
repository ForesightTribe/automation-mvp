BASE_URL = "https://fcc.zepto.co.in"

# Page path used for the browser-fallback header re-capture (only reached if
# a browser-free call gets a 401/403 that a fresh session apparently doesn't
# explain — see scraper.py's _recapture_auth_via_browser).
SALES_ANALYTICS_PAGE = "/vendor/dashboard/sales-analytics"

# Cheapest real authenticated call found (no filters/params, small response) —
# used purely as a "is this session still accepted" probe, not for real data.
USER_INFO_API = "/brand-analytics-web/api/v1/access-management/user"

# ── Discovery (tenant-specific IDs the Sales Analytics API requires) ────────────
CITY_LIST_API = "/api/v1/filter/city-list"
BRAND_CATEGORY_MAPPING_API = "/api/v1/commons/brand-category-mapping"

# ── Sales Analytics ─────────────────────────────────────────────────────────────
SALES_OVERVIEW_API = "/brand-analytics-web/api/v1/sales-analytics/sales-overview"
PRODUCT_PERFORMANCE_API = "/brand-analytics-web/api/v1/sales-analytics/product-performance"
