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

# ── Ads (`ads-bff`) ─────────────────────────────────────────────────────────────
# A different service from the analytics endpoints above, and stricter: it
# rejects the saved session's WAF token with 202 (an AWS WAF challenge), so ads
# calls need headers harvested from a live browser first. See
# scraper.py::capture_ads_headers.
ADS_PAGE = "/ads/campaign-management"
ADS_ANALYTICS_PAGE = "/ads/analytics"
ADS_CAMPAIGNS_API = "/ads-bff/api/v1/campaigns"
ADS_METRICS_API = "/ads-bff/api/v1/brands/analytics/metrics"
ADS_WALLET_API = "/ads-bff/api/v1/wallet/details"
ADS_CATEGORIES_API = "/ads-bff/api/v1/campaign-categories"

# The Analytics page's performance tables. Richer than ADS_CAMPAIGNS_API above:
# that one backs Campaign Management (budgets, status, toggles) and reports no
# revenue, no add-to-carts and no keywords. This one reports all three.
#
# Found late (20-Aug-2026) because the tables sit below the fold and load on
# scroll — an API capture that only waits for page load never sees them. Three
# earlier "Zepto does not expose X" conclusions were wrong for that reason.
ADS_TABULAR_API = "/ads-bff/api/v1/brands/analytics/metrics/tabular"

# `view` values. campaign/product/city/page load with the Analytics page;
# category and keyword load when their tab is selected.
ADS_VIEW_CAMPAIGN = "campaign_table"
ADS_VIEW_PRODUCT = "product_table"
ADS_VIEW_CATEGORY = "category_table"
ADS_VIEW_KEYWORD = "keyword_table"
ADS_VIEW_CITY = "city_table"
ADS_VIEW_PAGE = "page_table"

# Every view returns the same metric set, prefixed with the dimension name:
#   {dim}_spend, _revenue, _roas, _robas, _atc, _orders, _clicks,
#   _impressions, _cpc, _cpm, _same_skus, _other_skus
# plus {dim}_name and a few per-view extras (campaign: status, sub_type,
# daily_budget, unique_reach, new_to_brand_user_percentage; product: category,
# details, ctr; keyword: match_type, ctr).
ADS_TABULAR_PAGE_SIZE = 50

# The three tabs on Campaign Management. Campaigns are scoped to one at a time.
ADS_CATEGORIES = ("sponsored_products", "sponsored_display", "sponsored_brands")

# Metrics the analytics endpoint accepts. `impressions_per_thousand` is Zepto's
# name for the impressions series, not a derived per-mille figure.
ADS_METRIC_NAMES = ("spends", "ctr", "impressions_per_thousand", "clicks", "ecpm")
