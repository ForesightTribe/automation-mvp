BASE_URL = "https://brands.blinkit.com"

# ── Page URLs (navigation + session verification) ──────────────────────────────
CAMPAIGNS_PAGE = "/dashboard"
BRAND_COLLECTIONS_PAGE = "/diy/brand-pages"
VISIBILITY_PLANS_PAGE = "/diy/plans"

# ── API Endpoints ───────────────────────────────────────────────────────────────
CAMPAIGNS_API = "/adservice/v1/advertisers/campaigns"
SPONSORED_SOV_API = "/adservice/v1/campaigns/sponsored-sov"
BRAND_COLLECTIONS_API = "/adservice/v1/brand-pages"
VISIBILITY_PLANS_API = "/adservice/v1/plans"

# Per-campaign daily metric series — append the campaign id.
CAMPAIGN_DAILY_API = "/adservice/v1/campaigns/metrics-trends/{campaign_id}"
# Per-campaign keyword / recommendation breakdown — append the campaign id.
CAMPAIGN_REPORT_API = "/adservice/v1/campaigns/reports/{campaign_id}"

# ── Campaign types included in POST request bodies ─────────────────────────────
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

# Daily metrics requested from the per-campaign metrics-trends endpoint. The UI
# only lets you pick two at a time, but the API accepts the full list; the
# scraper falls back to per-metric calls (merged by date) if it ever rejects > 2.
DAILY_METRICS = [
    "budget_consumed",
    "impressions",
    "total_atc",
    "total_quantities_sold",
    "total_sales",
    "total_roas",
]
