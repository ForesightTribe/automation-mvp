"""Zepto campaign-manager endpoints and platform bounds.

The hosts, headers and every endpoint the scrape uses too — the campaign list, detail,
keyword floors, targeting options — are defined ONCE, in the seller console's endpoints
(`scraper/platforms/zepto/dashboard_data/seller/endpoints.py`), next to the shared client
and the shared reads (`seller/scraper.py`). What only the campaign manager calls — the
whole-campaign PUT, pause / activate, metadata, wallet — and the platform bounds stay
here. Auth endpoints belong to `platform_auth/marketplaces/zepto/endpoints.py`.

All of it was read off real traffic against the live BrikOven account (2026-08-21),
not guessed.
"""
from scraper.platforms.zepto.dashboard_data.seller.endpoints import (  # noqa: F401 (re-export)
    ADS_CAMPAIGN_PLA_API as CAMPAIGN_PLA,   # GET is the shared detail read; PUT is ours
)

# ── campaign-manager-only ads-bff calls ──────────────────────────────────────
CAMPAIGN_PAUSE = "/ads-bff/api/v1/campaigns/{id}/pause"    # POST {"brand_id": …}
CAMPAIGN_ACTIVATE = "/ads-bff/api/v1/campaigns/{id}/activate"
CAMPAIGN_METADATA = "/ads-bff/api/v1/campaigns/metadata"   # vocabulary + platform bounds
WALLET = "/ads-bff/api/v1/wallet/details"

# ── the analytics service (different host path, different header) ────────────
BRAND_ANALYTICS = "/brand-analytics-web/api/v1"

# ── platform bounds, published by Zepto itself ───────────────────────────────
# From campaigns/metadata → budget_types[0].minimum_value. Adopted rather than
# invented: a sub-minimum write would be rejected anyway, and refusing it at our own
# choke-point gives a reason instead of a 400.
MIN_DAILY_BUDGET = 500

# ── Keyword bid floors ──────────────────────────────────────────────────────
#
# Zepto PUBLISHES a per-keyword minimum, read-only, one request for a whole list —
# the direct analogue of Blinkit's `get_keyword_attributes`. The endpoint and its 500-a-
# request cap live in the seller endpoints (ADS_KEYWORD_CONFIG_API, KEYWORD_CONFIG_MAX);
# the read is `seller/scraper.get_keyword_floors`.
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
# Seen in the scraped campaign table (2026-09-19), never mapped until then: 7 campaigns
# held for an empty prepaid wallet, 2 finished.
STATUS_WALLET_EMPTY = "INSUFFICIENT_WALLET_BALANCE"
STATUS_ENDED = "ENDED"

