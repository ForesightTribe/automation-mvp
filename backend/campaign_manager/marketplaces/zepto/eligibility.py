"""Which Zepto campaigns the automations may touch (ZC-C3). PURE.

Only **product ads bid by keyword** — `campaign_type` PLA with KEYWORD bidding (Q4,
2026-09-19). Everything the campaign manager does assumes that shape: bid rules chase a
keyword's sponsored position, and the write path is built and verified against PLA's
whole-campaign PUT (`/campaigns/pla/{id}`). An AUTO campaign has no keyword bids to
manage (Zepto bids for it), and Display is a different product with a different API.

Pure, and apart from `adapter.py`, because the API process asks it too — at rule save —
and the API must never import an adapter.

Two callers, one rule:
  * **at save** (`repo.create_budget_schedule` / `create_bid_rule`), from the catalogue —
    so an ineligible campaign never becomes an automation. A campaign the catalogue has not
    seen (created since the last scrape) is allowed, as everywhere else;
  * **at write** (`adapter`), from the fresh read — the backstop for a rule saved before
    this gate, or a campaign whose type changed after it was catalogued.

A MISSING value is "no opinion", not a refusal: the fields are always present on real
campaigns, and refusing on an absent key would turn a Zepto payload rename into every
write failing. A value that is present and wrong is refused.
"""

AUTOMATABLE_TYPE = "PLA"
AUTOMATABLE_BIDDING = "KEYWORD"

# A Zepto bid rule must say WHERE it measures — a city or a store (ZC-C14). With neither,
# the engine would fall back to fixed Bengaluru coordinates, which on Zepto are not a store:
# every search would then pay a separately rate-limited store lookup (`get_page`), every
# tick. Refused at save (`repo.create_bid_rule`) and skipped at run time (`bid.run`).
RULE_NEEDS_LOCATION = True


def refusal(campaign_type: str | None, bid_targeting: str | None) -> str | None:
    """Why this campaign cannot be automated, or None when it can (or we cannot tell)."""
    ctype = (campaign_type or "").strip().upper()
    bidding = (bid_targeting or "").strip().upper()
    if ctype and ctype != AUTOMATABLE_TYPE:
        return (f"it is a {campaign_type} campaign — automations run only on Zepto product "
                f"ads (PLA) bid by keyword")
    if bidding and bidding != AUTOMATABLE_BIDDING:
        return (f"it uses {bid_targeting} bidding — automations run only on campaigns bid by "
                f"keyword, and Zepto sets the bids of an {bid_targeting} campaign itself")
    return None


def refusal_from_detail(detail: dict | None) -> str | None:
    """`refusal` off a raw campaign read (`GET /campaigns/pla/{id}`), where the bidding mode
    sits in `campaign_configs.bid_targeting` — not `bid_targeting_type` as in the list."""
    detail = detail or {}
    return refusal(detail.get("campaign_type"),
                   (detail.get("campaign_configs") or {}).get("bid_targeting"))
