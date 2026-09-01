"""Zepto's sponsored-slot marker, and the tracking id that comes with it.

WHY THIS EXISTS
---------------
Zepto search results interleave paid placements with organic ones and the payload
says which is which — we simply were not reading it. On one live `bread` search,
**9 of 24 results (37.5%) were sponsored**, all stored as if they were organic. That
skews SoV and rank for every Zepto keyword scrape, and it is the single fact the bid
optimizer cannot work without.

THE MARKER
----------
    productResponse.meta.tagsV2  ->  {"P0": {...}, "P3": {...}}

`tagsV2` is a dict keyed by BADGE SLOT, not by meaning: `P0` carried a "Product
Discount" badge and `P3` carried "Sponsored" in the captures. So match on
`tagType == "SPONSORED"` across the dict's VALUES — hardcoding `P3` would break the
day Zepto renumbers its badges.

⚠️ `is_fly_wheel_ad` IS NOT THIS. It sits right beside the tags on the same `meta`
block and reads false even on confirmed sponsored rows (verified: 10 of our own
sponsored slots, all `is_fly_wheel_ad: false`). It marks Zepto's organic "flywheel"
re-ranking, not a paid ad. Reading it as an ad flag is what made ads look invisible
for two days.

THE TRACKING ID
---------------
Sponsored items — and only sponsored items — carry an item-level `uclId`: a
pipe-delimited string naming the advertiser, the campaign, the store, and the
CAMPAIGN KEYWORD that won the slot. Verified against 19 live ads across two
advertisers on 2026-09-01; our own ads carried the same advertiser UUID we store in
`cm_platform_accounts.account_ref`.

    101|<uuid>|1600|<ts>|<uuid>|||CPC|<advertiser>|<advertiser>||2373457|2373457|
    <store>||0|P_INFO|||<uuid>|<uuid>|<uuid>|<uuid>|K_INFO|PHRASE|bakers dozen bread|0|0|0|0

🔴 **The keyword in a `uclId` is the CAMPAIGN's keyword, not the query that was
searched.** Searching `sourdough bread` returned our ad won by `bakers dozen bread`;
`rosemary sourdough` returned one won by `bakers dozen sourdough bread` under mode
`K_INFO_SEMANTIC`. Zepto matches campaign keywords to shopper queries by phrase and
semantically, so a consumer of this data must attribute a slot to
(campaign, keyword, match_type) — campaign alone would credit one slot to every rule
in a multi-keyword campaign.

Positions are NOT parsed out of the id: the position is the item's own rank in the
result list, which the caller already has.
"""
from typing import Any

# The marker, and the field it is forever going to be confused with.
SPONSORED_TAG_TYPE = "SPONSORED"

# `uclId` segments we can name with confidence. Everything else is left alone
# rather than guessed at — see UNNAMED_TAIL below.
_MODEL_TOKENS = ("CPC", "CPM")
# What separates the product block from the keyword block in the id.
_KEYWORD_MARKERS = ("K_INFO", "K_INFO_SEMANTIC")
_MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")


def is_sponsored(product_response: dict) -> bool:
    """Is this search result a paid placement?

    Reads `meta.tagsV2` and matches on `tagType`, never on the slot key. Returns
    False for a malformed or absent tag block: a result we cannot prove is an ad is
    reported as organic, which under-counts ads rather than inventing them.
    """
    tags = ((product_response or {}).get("meta") or {}).get("tagsV2") or {}
    if not isinstance(tags, dict):
        return False
    return any(
        isinstance(t, dict) and t.get("tagType") == SPONSORED_TAG_TYPE
        for t in tags.values()
    )


def parse_ucl_id(ucl: str | None) -> dict[str, Any]:
    """Decode a sponsored item's `uclId` into the fields we can name.

    Positional parsing would be brittle — the id carries empty segments and the
    layout is not documented — so each field is found by the token that announces
    it, and anything not found is simply absent from the result. A caller must treat
    every key as optional.

    Returns `{}` for a missing or unparseable id.
    """
    if not ucl or not isinstance(ucl, str):
        return {}
    parts = ucl.split("|")
    out: dict[str, Any] = {}

    for i, seg in enumerate(parts):
        # Pricing model, immediately followed by the advertiser id (twice).
        if seg in _MODEL_TOKENS and "model" not in out:
            out["model"] = seg
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            if _looks_uuid(nxt):
                out["advertiser_id"] = nxt

        # The campaign id appears twice in a row, as a bare 6-8 digit integer, and
        # is followed by the store uuid. Requiring the REPEAT is what stops a price
        # or timestamp segment being mistaken for it.
        if (seg.isdigit() and 6 <= len(seg) <= 8 and "campaign_id" not in out
                and i + 1 < len(parts) and parts[i + 1] == seg):
            out["campaign_id"] = seg
            nxt = parts[i + 2] if i + 2 < len(parts) else ""
            if _looks_uuid(nxt):
                out["store_id"] = nxt

        # Keyword block: <marker>|<match_type>|<keyword>
        if seg in _KEYWORD_MARKERS:
            out["keyword_mode"] = seg
            mt = parts[i + 1] if i + 1 < len(parts) else ""
            if mt in _MATCH_TYPES:
                out["match_type"] = mt
                if i + 2 < len(parts):
                    out["keyword"] = parts[i + 2]

    # The four trailing integers vary across ads (`0|10|0|0`, `0|0|70|0`, `0|0|0|0`)
    # and no reading of them has been established. Kept verbatim so a future
    # investigation has the data, deliberately NOT given a meaningful name.
    if len(parts) >= 4 and all(p.isdigit() for p in parts[-4:]):
        out["unnamed_tail"] = [int(p) for p in parts[-4:]]
    return out


def _looks_uuid(s: str) -> bool:
    return len(s) == 36 and s.count("-") == 4
