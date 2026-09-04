"""Blinkit's sponsored-slot marker, and the ad tracking ids that come with it.

WHY THIS EXISTS
---------------
Two parts of the system need to answer "is this search result a paid placement?" —
the bid optimizer (`campaign_manager/marketplaces/blinkit/live_position.py`, which
has read it correctly since it was written) and the public keyword scrape (which did
not read it at all: 340,635 stored Blinkit listings, every one of them recorded as
organic). One predicate, in one place, because the alternative is two definitions of
"sponsored" drifting apart — which is exactly how the `city_ids` bug hid in a second
copy of the payload builder.

THE MARKER
----------
    snippet.tracking.common_attributes.ads_campaign_id

A non-empty campaign id is what makes a slot sponsored. There is no boolean to read.

⚠️ `ads_campaign_id` APPEARS IN THREE PLACES and only one of them is a product ad.
In the recorded capture (`api.txt`) it occurs 15 times: 9 under `common_attributes`
(product cards — what we want) and 6 under `widget_meta` / `entry_source_map`, which
belong to a promotional BANNER carousel (`ads_type: "monet_banner_listing"`). A
recursive search for the key would flag banners as sponsored products. Always read
the `common_attributes` block of a product snippet, never the snippet at large.

CORROBORATING FIELDS (not the marker, but they travel with it)
    ads_type       "monet_product_listing" for a sponsored product slot,
                   "monet_banner_listing" for a banner
    badge          "AD"          (common_attributes)
    overlay_badges "ad,"         (cart_item, i.e. the other side of the snippet)

`is_sponsored` deliberately keys on the campaign id alone rather than on all four:
that is the reading the bid optimizer has been making live decisions with, and a
stricter predicate here would silently disagree with it.

THE IDS
-------
`ads_campaign_id` is OUR campaign id — the same integer the Campaign Manager writes
to. It is the direct analogue of Zepto's `uclId`, minus the keyword attribution:
Blinkit does not say which campaign keyword won the slot, so a slot can be attributed
to a campaign but not to a rule within it.
"""
from typing import Any

# Values Blinkit sends on organic rows. Reading any of them as a campaign id would
# have the optimizer chase a position its ad never held.
_PLACEHOLDERS = ("", "0", "null", "None")


def campaign_id(common: dict | None) -> str:
    """The sponsoring campaign's id, or "" when the slot is organic.

    Takes the product snippet's `tracking.common_attributes` block — NOT the whole
    snippet (see the module docstring: banners carry the same key elsewhere).
    """
    if not isinstance(common, dict):
        return ""
    raw = str(common.get("ads_campaign_id") or "").strip()
    return "" if raw in _PLACEHOLDERS else raw


def is_sponsored(common: dict | None) -> bool:
    """Is this product slot a paid placement?

    False for a missing or placeholder campaign id: a result we cannot prove is an ad
    is reported as organic, which under-counts ads rather than inventing them.
    """
    return bool(campaign_id(common))


def ad_meta(common: dict | None) -> dict[str, Any]:
    """The sponsored slot's tracking ids, for storage. `{}` on an organic row.

    Kept as a small dict rather than promoted to columns: `search_listings` is the
    largest table we write (~85 MB per national run) and only ~8% of its rows are
    sponsored, so a nullable column per id would cost every organic row. Promote one
    to a column when a query actually needs it.
    """
    cid = campaign_id(common)
    if not cid:
        return {}
    out: dict[str, Any] = {"ads_campaign_id": cid}
    # Sub-campaign is the ad-group grain; cost id and type are carried verbatim
    # because no reading of them has been established yet and guessing later is
    # harder than keeping them now.
    for src, dst in (("ads_subcampaign_id", "ads_subcampaign_id"),
                     ("ads_cost_id", "ads_cost_id"),
                     ("ads_type", "ads_type")):
        val = common.get(src) if isinstance(common, dict) else None
        if val not in (None, ""):
            out[dst] = str(val)
    return out
