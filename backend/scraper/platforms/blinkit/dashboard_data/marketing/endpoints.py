BASE_URL = "https://brands.blinkit.com"

# ── Page URLs (navigation + session verification) ──────────────────────────────
CAMPAIGNS_PAGE = "/dashboard"
BRAND_COLLECTIONS_PAGE = "/diy/brand-pages"
VISIBILITY_PLANS_PAGE = "/diy/plans"

# ── API Endpoints ───────────────────────────────────────────────────────────────
ADVERTISERS_API = "/adservice/v1/advertisers"
CAMPAIGNS_API = "/adservice/v1/advertisers/campaigns"
SPONSORED_SOV_API = "/adservice/v1/campaigns/sponsored-sov"
BRAND_COLLECTIONS_API = "/adservice/v1/brand-pages"
VISIBILITY_PLANS_API = "/adservice/v1/plans"

# Publishes the campaign (asset) types enabled for the logged-in advertiser,
# grouped under objective_types[].asset_types — the same call the dashboard makes.
CAMPAIGN_CONFIG_API = "/adservice/v2/campaigns/config"

# Per-campaign daily metric series — append the campaign id.
CAMPAIGN_DAILY_API = "/adservice/v1/campaigns/metrics-trends/{campaign_id}"
# Per-campaign keyword / recommendation breakdown — append the campaign id.
CAMPAIGN_REPORT_API = "/adservice/v1/campaigns/reports/{campaign_id}"

# Per-campaign CONFIGURATION (not metrics): city targeting (`region_type`/`region_ids`),
# the keyword list with its live bids, budget, pacing, spend-to-date — plus the account's
# `min_cpm_config`. The campaign LIST carries none of this.
CAMPAIGN_DETAIL_API = "/adservice/v1/campaigns/{campaign_id}"

# Blinkit's published bid range PER KEYWORD — `bid_range.exact_match/.smart_match` with
# {min, max, suggested_min, suggested_max, min_for_boost} plus `keyword_searches`. Takes a
# comma-separated keyword list, so one request covers a whole campaign.
# Query: keywords=a,b&campaign_type=<type>&campaign_id=<id>
KEYWORD_ATTRIBUTES_API = "/adservice/v1/campaigns/keywords/attributes"

# Keywords per attributes request. The endpoint has no documented cap; this keeps the URL
# comfortably short for a campaign carrying dozens of long keywords.
KEYWORD_ATTRIBUTES_CHUNK = 40

# ── Campaign types included in POST request bodies ─────────────────────────────
# Fallback only. Blinkit 400s the whole request if it is sent a type the advertiser
# does not have enabled ("[...] are not enabled for given advertiser"), so the
# scraper reads the live set from CAMPAIGN_CONFIG_API and only falls back to this
# list if that call fails. Do not send this list blindly.
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
