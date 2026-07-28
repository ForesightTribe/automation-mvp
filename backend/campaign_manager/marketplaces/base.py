"""Adapter contract — INTENTIONALLY not a formal interface yet (D17).

An adapter exposes the marketplace-specific *mechanism*; `writes.py` owns the
*policy* (dry-run + guardrails) and calls into it. The informal contract each
adapter provides:

    async def read_budget(client, campaign_id) -> int | None
    async def apply_budget(client, campaign_id, budget) -> dict       # {status|success: ...}
    async def read_position(client, keyword, lat, lon, ...) -> float | None
    async def read_bid(client, campaign_id, keyword) -> int | None
    async def apply_bid(client, campaign_id, keyword, cpm, match_type) -> dict

We do NOT write an abstract base class here until a second marketplace (Zepto/
Instamart) actually lands: one example produces a leaky, Blinkit-shaped interface.
Two real MPs define a good seam; one guesses. See docs §5.1 / D17.
"""
