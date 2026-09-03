"""Zepto campaign-manager endpoints, headers and platform bounds.

Everything volatile about Zepto's ads API lives here, nowhere else — the same rule
docs/code-standards.md applies to selectors.py. Auth endpoints are NOT here; they
belong to `platform_auth/marketplaces/zepto/endpoints.py`.

All of it was read off real traffic against the live BrikOven account (2026-08-21),
not guessed.
"""

CONSOLE = "https://brands.zepto.co.in"
API = "https://fcc.zepto.co.in"

# ── the ads back-end-for-frontend ────────────────────────────────────────────
CAMPAIGNS = "/ads-bff/api/v1/campaigns"                    # GET  list
CAMPAIGN_PLA = "/ads-bff/api/v1/campaigns/pla/{id}"        # GET detail · PUT update
CAMPAIGN_PAUSE = "/ads-bff/api/v1/campaigns/{id}/pause"    # POST {"brand_id": …}
CAMPAIGN_ACTIVATE = "/ads-bff/api/v1/campaigns/{id}/activate"
CAMPAIGN_METADATA = "/ads-bff/api/v1/campaigns/metadata"   # vocabulary + platform bounds
TARGETING_OPTIONS = "/ads-bff/api/v1/brands/targeting-options"   # the city list
WALLET = "/ads-bff/api/v1/wallet/details"

# ── the analytics service (different host path, different header) ────────────
BRAND_ANALYTICS = "/brand-analytics-web/api/v1"

# ── the three load-bearing headers ───────────────────────────────────────────
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
#    `waf-enabled` note in transport.py.
PROXY_TARGET_HEADER = "x-proxy-target"
PROXY_TARGET_BRAND_ANALYTICS = "brand-analytics"
WAF_TOKEN_HEADER = "x-aws-waf-token"
WAF_ENABLED_HEADER = "waf-enabled"
WAF_ENABLED_VALUE = "false"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# ── platform bounds, published by Zepto itself ───────────────────────────────
# From campaigns/metadata → budget_types[0].minimum_value. Adopted rather than
# invented: a sub-minimum write would be rejected anyway, and refusing it at our own
# choke-point gives a reason instead of a 400.
MIN_DAILY_BUDGET = 500

# ── Keyword bid floors ──────────────────────────────────────────────────────
#
# Zepto PUBLISHES a per-keyword minimum, read-only, one request for a whole list —
# the direct analogue of Blinkit's `get_keyword_attributes`:
KEYWORD_CONFIG = "/ads-bff/api/v1/keyword/config"    # POST
#
#     -> {"keywords": [{"keyword": "bread", "match_type": "EXACT"}]}
#     <- {"keywords": [{"keyword": "bread", "match_type": "EXACT", "min_bid": 9}]}
#
# Measured live 2026-09-02 (EXACT): bread 9 · milk 9 · ricotta 3 · sourdough bread 3.
#
# ⚠️ THE FLOOR IS PER KEYWORD AND IT VARIES (3 to 9 in one sample). Any single global
# number is therefore wrong for somebody — which is what `MIN_BID` below is, and why
# it must become a FALLBACK rather than the floor once `read_bid_floors` exists.
#
# ⚠️ EXACT ONLY. PHRASE and BROAD returned nothing for any keyword tested. What Zepto
# actually enforces for those is still unknown.
#
# ⚠️ COVERAGE IS INCOMPLETE, and silence is not permission. `pink toffee` is absent
# from the response for every match type, yet a live PUT was refused against it:
#
#     keyword bid validation failed: keyword 'pink toffee' (EXACT)
#     bid 8.00 is below minimum bid 10.00
#
# The hypothesis that fits every observation: a keyword WITH a config gets its own
# floor, and one WITHOUT gets a default of 10. That makes ₹10 the right value for the
# unknown case and the wrong value for `bread` (9) or `ricotta` (3).
#
# ⚠️ Not the ₹8 in `campaigns/metadata` either — that is
# `bid_multiplier_types[pdp].minimum_bid`, a per-PLACEMENT floor. Adopting it would
# have put our guardrail BELOW the real limit.
#
# INTERIM: `MIN_BID` is enforced unconditionally by `writes.apply_bid`, so today it is
# deliberately CONSERVATIVE — it refuses a ₹3 bid on `ricotta` that Zepto would have
# accepted. Safe (never writes below any observed floor), but over-restrictive, and it
# is the reason `read_bid_floors` is worth building.
MIN_BID = 10

# Campaign statuses observed live. `DAILY_BUDGET_EXHAUSTED` is Zepto's equivalent of
# Blinkit's ON_HOLD: live but out of budget, so stoppable rather than startable.
# ⚠️ Not known to be the complete set — treat an unseen value as unknown, not as an
# error, and log it.
STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED = "PAUSED"
STATUS_BUDGET_EXHAUSTED = "DAILY_BUDGET_EXHAUSTED"

# The AWS WAF challenge token lives ~5 minutes (measured: alive at 4 min, dead at 6).
# Never cached across runs — every job interval we have is longer than that, so a
# stored token would be expired essentially every time it was read.
WAF_TOKEN_TTL_SECONDS = 300
