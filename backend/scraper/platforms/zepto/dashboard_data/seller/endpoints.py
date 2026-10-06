"""Zepto seller-console endpoints, headers and the client's constants.

Everything volatile about the console's APIs lives here — the sales, PO and ads-bff
endpoints the scrape reads, and the hosts / headers the shared client (`client.py`)
sends. The campaign manager imports the shared ones from here
(`campaign_manager/marketplaces/zepto/endpoints.py`), so each is defined once. Auth
endpoints are not here; they belong to `platform_auth/marketplaces/zepto/endpoints.py`.
"""

# The SPA is served from one host and talks to another. Both matter: the API checks
# Origin/Referer, so the console URL is not decoration.
CONSOLE = "https://brands.zepto.co.in"
API = "https://fcc.zepto.co.in"
BASE_URL = API

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# ── the three load-bearing headers (client.py sends them) ───────────────────
#
# 1. `authorization` carries the RAW jwt with NO "Bearer " prefix, despite the login
#    response advertising tokenType "Bearer". Prefixing it fails at base64 decode.
#
# 2. `/brand-analytics-web/*` needs `x-proxy-target: brand-analytics`. WITHOUT it the
#    gateway answers a bare text/plain 404 — which reads like a wrong URL and sends
#    you hunting for an endpoint that was correct all along.
#
# 3. `/ads-bff/*` sits behind AWS WAF and needs BOTH a valid `x-aws-waf-token` AND
#    `waf-enabled: false`. Missing EITHER, CloudFront answers 429 — which reads like
#    rate limiting and is not. That misreading cost a full afternoon; see the
#    `waf-enabled` note in client.py.
PROXY_TARGET_HEADER = "x-proxy-target"
PROXY_TARGET_BRAND_ANALYTICS = "brand-analytics"
WAF_TOKEN_HEADER = "x-aws-waf-token"
WAF_ENABLED_HEADER = "waf-enabled"
WAF_ENABLED_VALUE = "false"

# The AWS WAF challenge token lives ~5 minutes (measured: alive at 4 min, dead at 6).
# Never cached across runs — every job interval we have is longer than that, so a
# stored token would be expired essentially every time it was read.
WAF_TOKEN_TTL_SECONDS = 300

# Cheapest real authenticated call found (no filters/params, small response) —
# used purely as a "is this session still accepted" probe, not for real data.
USER_INFO_API = "/brand-analytics-web/api/v1/access-management/user"

# ── Discovery (tenant-specific IDs the Sales Analytics API requires) ────────────
CITY_LIST_API = "/api/v1/filter/city-list"
BRAND_CATEGORY_MAPPING_API = "/api/v1/commons/brand-category-mapping"

# ── Sales Analytics ─────────────────────────────────────────────────────────────
SALES_OVERVIEW_API = "/brand-analytics-web/api/v1/sales-analytics/sales-overview"
PRODUCT_PERFORMANCE_API = "/brand-analytics-web/api/v1/sales-analytics/product-performance"

# ── PO Management (`/vendor` app on the same host) ──────────────────────────────
# A separate part of the seller portal (brands.zepto.co.in/vendor/po/*) that
# nothing scraped until 2026-08-27. Its APIs live on the SAME host as the
# analytics ones above and accept the SAME saved session — no WAF challenge, no
# browser needed, unlike ads-bff.
#
# All three are POST with a JSON body carrying a date window, an offset/limit
# pair, and filter arrays. They page: the response has `total` and `hasNext`.
#
# ⚠️ `statusList: []` is assumed to mean "every status". The browser sends one
# value because the UI is on a status tab; an empty list has NOT been verified
# to widen it. If a scrape returns fewer POs than the dashboard shows, this is
# the first thing to check.
PO_FILTER_API = "/api/v1/po/filter"
PO_LISTING_STAT_API = "/api/v1/po/listing-stat"
PO_SCHEDULED_API = "/api/v1/po/scheduled"
GRN_FILTER_API = "/api/v1/grn/filter"
ASN_FILTER_API = "/api/v1/asn/filter"
# Returns-to-vendor. Endpoint observed but its payload was never captured, so
# nothing reads it yet.
RTV_FILTER_API = "/vendor/api/v2/rtv/filter"

# Per-PO line items — a GET, one call per PO, paged with offset/limit. The list
# endpoint reports `itemsCount` but not the lines themselves, so this is a second
# pass over the POs already fetched. Carries `unitPrice` (what Zepto pays) and
# `mrp`, which appear on no other Zepto endpoint, and `pvId` — the same id
# `zepto_seller_sales` keys on, so lines join to Products directly.
PO_ITEMS_API = "/api/v1/po/{po_id}/items"
GRN_ITEMS_API = "/api/v1/grn/{grn_no}/items"

# The UI asks for 14 at a time; 100 is well within what the API accepts and
# cuts the number of pages for a 30-day window to one on this account.
PO_PAGE_SIZE = 100
# Guard against an unbounded loop if `hasNext` ever misbehaves.
PO_MAX_PAGES = 20

# ⚠️ asn/filter is NOT the same as its two siblings — it 500s at limit=100.
#
# Measured 2026-09-05 against the live API, one variable at a time. Identical
# 31-day window, identical payload, only `limit` changed:
#
#     limit=100  ->  HTTP 500 after 20.9s   (their gateway timing out)
#     limit= 50  ->  HTTP 200,  50 rows, 0.9s
#     limit= 25  ->  HTTP 200,  25 rows, 0.6s
#
# Paginating that same window at 50 collects all 76 ASNs in 1.8s. The failing
# runs spent two minutes on the 5/15/45s retry ladder and returned nothing.
#
# po/filter and grn/filter handle limit=100 fine (75 rows, under a second), so
# this is specific to the ASN endpoint — which is why it stays a separate
# constant rather than lowering the page size for all three.
#
# This was mistaken for random flakiness for weeks ("~4 failures in 18
# attempts, randomly distributed"). It was never random: the failures were the
# WIDE windows, which return more rows. Narrow windows happened to stay under
# whatever the endpoint chokes on.
#
# ⚠️ 50 STOPPED WORKING. Re-measured 2026-09-16 (the 14/15/16 Sep scheduled runs
# all lost ASNs, three days with zero rows written):
#
#     31-day window, limit=50  ->  HTTP 500 after 21.3s, 21.0s, 21.5s  (3/3)
#     31-day window, limit=25  ->  HTTP 200 in 1.1s
#     31-day window, limit=10  ->  HTTP 200 in 0.7s
#     14-day window, limit=50  ->  HTTP 200 in 1.1s   (34 rows)
#      7-day window, limit=50  ->  HTTP 200 in 0.8s   (16 rows)
#     po/filter & grn/filter, limit=100 -> HTTP 200 in 0.7s / 1.6s
#
# The 500 body finally named the cause, which the 5 Sep measurements could only
# infer: their gateway fans out per page to an internal service and that call
# times out —
#     Post "http://wms-inbound.zepto.co/api/v1/inbound/inbound-details-by-requestIds":
#     context deadline exceeded (Client.Timeout exceeded while awaiting headers)
#
# So the limit is ROWS PER REQUEST against a deadline on their side, not a fixed
# number: as the window fills with ASNs, the page size that fits shrinks. 25 is
# 20x under the deadline (1.1s vs 21s), which buys room for that to drift again.
# If ASNs start failing once more, halve this and re-measure — do NOT reach for
# a longer retry ladder, because every attempt burns the same 21s and fails.
ASN_PAGE_SIZE = 25


# ── Ads (`ads-bff`) ─────────────────────────────────────────────────────────────
# A different service from the analytics endpoints above, and stricter: it needs
# an AWS WAF token on top of the session (202 without one). The shared Zepto
# client mints it once per run and re-mints it on a 202/429.
ADS_CAMPAIGNS_API = "/ads-bff/api/v1/campaigns"                   # GET list (all pages)
ADS_CAMPAIGN_PLA_API = "/ads-bff/api/v1/campaigns/pla/{id}"       # GET detail · PUT update
ADS_TARGETING_OPTIONS_API = "/ads-bff/api/v1/brands/targeting-options"   # the city list
# Zepto's published minimum bid per keyword — POST {"keywords": [{keyword, match_type}]}.
ADS_KEYWORD_CONFIG_API = "/ads-bff/api/v1/keyword/config"
# ⚠️ Capped at 500 keywords per request — more is a 400 "max 500 keywords allowed per
# request" (seen 2026-10-03 on Sereko's 2428159, which failed the catalogue every day
# from 2026-09-29). `scraper.get_keyword_floors` batches on this.
KEYWORD_CONFIG_MAX = 500
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

# The same tables scoped to ONE campaign — what the campaign detail page asks for. Takes
# `campaign_id` in the body. With view=keyword_table it is keyword performance PER
# CAMPAIGN (P38): one row per keyword × match type, for the window asked. Probed
# 2026-10-06: a multi-day window is one total per keyword, and `interval`/`breakdown`
# are refused (400) — so one call per campaign per DAY.
ADS_CAMPAIGN_TABULAR_API = "/ads-bff/api/v1/brands/campaigns/analytics/metrics/tabular"

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
