"""Blinkit adapter — the marketplace-specific *mechanism* (docs §5.1 / D17).

Thin wrappers over the Blinkit engine (`.client` + `.live_position`), which is now
**vendored into this package** (copied out of the legacy `ad_campaigns/` on 2026-07-30)
so campaign-manager v2 owns its whole Blinkit stack and no longer imports v1. `writes.py`
owns the dry-run + guardrail *policy* and calls these only when a real mutation is due.

B3: live writes send the tenant's STORED advertiser id (set on the client by
`writes.arm_live` → `set_advertiser`), overriding the client's own unreliable
`get_advertiser_id()` derivation (which falls back to a possibly-stale hardcoded id).
"""
from campaign_manager.marketplaces.blinkit.client import setup, setup_with_state  # noqa: F401  (session bootstrap)
from campaign_manager.marketplaces.blinkit.live_position import get_live_positions


async def read_budget(client, campaign_id: int) -> int | None:
    """Current daily budget for a campaign (a READ — safe)."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    budget = (detail or {}).get("campaign_budget")
    return int(budget) if budget is not None else None


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the campaign's daily budget. LIVE — only reached via writes.apply_budget.
    Sends the tenant's stored advertiser id (set on the client by arm_live)."""
    adv = getattr(client, "cm_advertiser_id", None)
    detail, _ = await client.get_campaign_detail(campaign_id)
    pacing = (detail or {}).get("pacing_type", "DAILY")
    changes = {"bidding_strategy": {"total_budget": float(budget), "pacing_type": pacing}}
    resp = await client.update_campaign(campaign_id, changes, advertiser_id=adv)
    if resp.get("status") or resp.get("success"):
        return resp
    # Fallback: empty pids handles delisted/invalid catalog products.
    return await client.update_campaign(campaign_id, changes, empty_pids=True, advertiser_id=adv)


async def read_bid(client, campaign_id: int, keyword: str) -> int | None:
    """Current CPM bid for a keyword in a campaign (a READ — safe)."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    existing = (
        (detail.get("campaign_targeting") or {})
        .get("keyword_targeting", {})
        .get("keywords", [])
    ) or detail.get("keywords", [])
    for kw in existing:
        if kw.get("keyword") == keyword and kw.get("bids"):
            return int(kw["bids"][0].get("cpm", 0))
    return None


async def resolve_advertiser(client) -> int:
    """What Blinkit's own code would derive for the account — `client.get_advertiser_id()`,
    which falls back to a (possibly STALE) hardcoded constant because Blinkit doesn't expose
    the id in its read APIs. Shown by `cm advertiser` for comparison only; live writes use
    the per-tenant STORED value, not this. Read-only."""
    return int(await client.get_advertiser_id())


def set_advertiser(client, advertiser_id: int) -> None:
    """Make subsequent writes on this client send `advertiser_id` (the tenant's stored
    account), overriding Blinkit's unreliable derivation. Called by writes.arm_live."""
    client.cm_advertiser_id = int(advertiser_id)


async def read_bids(client, campaign_id: int) -> dict[str, int]:
    """Current CPM per keyword for a campaign (a READ — safe). {keyword: cpm}."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    existing = (
        (detail.get("campaign_targeting") or {}).get("keyword_targeting", {}).get("keywords", [])
    ) or (detail or {}).get("keywords", [])
    return {k["keyword"]: int(k["bids"][0].get("cpm", 0))
            for k in existing if k.get("keyword") and k.get("bids")}


async def read_products(client, campaign_id: int) -> list[dict]:
    """Campaign products (name + pid) — used to match the ad in live search (a READ)."""
    return await client.get_campaign_products(campaign_id)


async def read_position(client, keyword: str, lat: float, lon: float) -> list[dict]:
    """Live consumer-search positions for a keyword at a dark store (a READ — safe).
    Returns [{position, name, is_ad, pid}]. `client` is unused (separate browser)."""
    return await get_live_positions(keyword, lat=lat, lon=lon)


async def resolve_position(client, campaign_id: int, keyword: str, *, lat: float, lon: float,
                           product_names: list[str], product_pids: list[str],
                           brand_name: str | None) -> tuple[float | None, str]:
    """Live sponsored position for the campaign's product on `keyword` (a READ — safe).
    Scrapes consumer search, then matches this campaign's product by pid/name/brand.
    Returns (position | None, source). None = product not found / organic-only → skip.
    MP-specific matching lives in `positions.py`; the bid loop stays MP-agnostic."""
    from campaign_manager.marketplaces.blinkit import positions
    return await positions.resolve(keyword, lat, lon, product_names=product_names,
                                   product_pids=product_pids, brand_name=brand_name)


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set a keyword's CPM bid. LIVE — only reached via writes.apply_bid.
    Sends the tenant's stored advertiser id (set on the client by arm_live)."""
    adv = getattr(client, "cm_advertiser_id", None)
    api_match = "SMART" if match_type == "BROAD" else match_type
    return await client.update_keyword_bids(
        campaign_id, [{"keyword": keyword, "match_type": api_match, "cpm": int(cpm)}],
        advertiser_id=adv,
    )
