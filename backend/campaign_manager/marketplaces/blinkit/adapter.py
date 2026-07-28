"""Blinkit adapter — the marketplace-specific *mechanism* (docs §5.1 / D17).

Thin wrappers over the reused engine (`ad_campaigns.client` + `ad_campaigns.
live_position`). `writes.py` owns the dry-run + guardrail *policy* and calls these
only when a real mutation is due.

⚠️ B3 (before live writes land — V1.3 / V5): `client.update_campaign` internally
derives `advertiser_id` via `client.get_advertiser_id()`, which today falls back to a
hardcoded `234` (Dobra's account). That fallback must be removed (derive live +
fail loud), and — for multi-tenant — `writes.py` should assert the session's
advertiser_id matches the tenant's expected one before any write. Not exercised in
V0 (dry-run, no writes); wired here so V1 has one place to harden.
"""
from ad_campaigns.client import setup, setup_with_state  # noqa: F401  (session bootstrap, reused by orchestration)
from ad_campaigns.live_position import get_live_positions


async def read_budget(client, campaign_id: int) -> int | None:
    """Current daily budget for a campaign (a READ — safe)."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    budget = (detail or {}).get("campaign_budget")
    return int(budget) if budget is not None else None


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the campaign's daily budget. LIVE — only reached via writes.apply_budget."""
    detail, _ = await client.get_campaign_detail(campaign_id)
    pacing = (detail or {}).get("pacing_type", "DAILY")
    changes = {"bidding_strategy": {"total_budget": float(budget), "pacing_type": pacing}}
    resp = await client.update_campaign(campaign_id, changes)
    if resp.get("status") or resp.get("success"):
        return resp
    # Fallback: empty pids handles delisted/invalid catalog products.
    return await client.update_campaign(campaign_id, changes, empty_pids=True)


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


async def read_position(client, keyword: str, lat: float, lon: float) -> list[dict]:
    """Live consumer-search positions for a keyword at a dark store (a READ — safe).
    Returns [{position, name, is_ad, pid}]. `client` is unused (separate browser)."""
    return await get_live_positions(keyword, lat=lat, lon=lon)


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set a keyword's CPM bid. LIVE — only reached via writes.apply_bid."""
    api_match = "SMART" if match_type == "BROAD" else match_type
    return await client.update_keyword_bids(
        campaign_id, [{"keyword": keyword, "match_type": api_match, "cpm": int(cpm)}]
    )
