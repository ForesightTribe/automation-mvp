BASE_URL = "https://brands.blinkit.com"

# ── Page URLs (navigation + session verification) ──────────────────────────────
CAMPAIGNS_PAGE = "/diy/list"
BRAND_COLLECTIONS_PAGE = "/diy/brand-pages"
VISIBILITY_PLANS_PAGE = "/diy/plans"

# ── API Endpoints ───────────────────────────────────────────────────────────────
CAMPAIGNS_API = "/adservice/v1/advertisers/campaigns"
SPONSORED_SOV_API = "/adservice/v1/campaigns/sponsored-sov"
PERFORMANCE_SUMMARY_API = "/adservice/v1/campaigns/performance-summary"
BRAND_COLLECTIONS_API = "/adservice/v1/brand-pages"
VISIBILITY_PLANS_API = "/adservice/v1/plans"

# ── Campaign types included in POST request body ───────────────────────────────
ALL_CAMPAIGN_TYPES = [
    "PRODUCT_LISTING",
    "PRODUCT_RECOMMENDATION",
    "SEARCH_SUGGESTION",
    "SHELF_DIY",
    "STORY_DIY",
    "BANNER_DIY",
    "BRAND_SPOTLIGHT_DIY",
    "BANNER_LISTING",
    "BRAND_BOOSTER",
]
