"""Zepto adapter — the marketplace-specific *mechanism* (see marketplaces/base.py).

`writes.py` owns the policy (dry-run default, bounds, no-op suppression, rate
limiting, audit). This module owns how Zepto is actually driven, and one invariant
that is Zepto's alone:

## Every write is read-modify-write, and must change exactly one field

Budget and bid are both a **whole-campaign PUT** — geo targeting, the product list
and every other keyword's bid ride in the same body. A wrong payload does not fail
loudly; it rewrites live configuration.

So `apply_budget` and `apply_bid` never construct a payload. They:

    1. read the campaign fresh,
    2. translate it into the PUT shape (translate.to_put),
    3. mutate ONE field,
    4. diff against the untouched translation and REFUSE unless exactly that field
       changed,
    5. only then PUT.

Step 4 is the load-bearing one. It catches both a translator bug and a campaign
that changed under us between read and write — someone editing in the dashboard
while a job runs is routine here, not exotic.

⚠️ This is mechanism, not policy, which is why it lives here and not in
`writes.py`: it defends against a hazard only Zepto has. Blinkit's targeted writes
cannot damage a campaign this way, and forcing every marketplace through a
whole-object diff would be wrong.

## Status vocabulary

Zepto's own strings map onto the engine's canonical set. `DAILY_BUDGET_EXHAUSTED`
is Zepto's `ON_HOLD`: live but out of budget — stoppable, not startable, and never
ours to clear. An unmapped value passes through unchanged so a guardrail can refuse
it by name rather than silently coercing it into something writable.
"""
from app.utils.logger import logger
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import endpoints as ep
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.marketplaces.zepto.transport import setup  # noqa: F401  (contract)

_STATUS_FROM_ZEPTO = {
    ep.STATUS_ACTIVE: "running",
    ep.STATUS_PAUSED: "paused",
    # Live but out of budget — Zepto-imposed, exactly like Blinkit's ON_HOLD.
    ep.STATUS_BUDGET_EXHAUSTED: "held",
}


def _canonical(status: str | None) -> str | None:
    """Zepto's status -> ours. Unmapped values return as-is, on purpose."""
    if not status:
        return None
    key = status.strip().upper()
    if key not in _STATUS_FROM_ZEPTO:
        logger.warning(
            f"Zepto returned an unmapped campaign status {status!r} — treating it as "
            "unknown. If it is legitimate, add it to _STATUS_FROM_ZEPTO."
        )
    return _STATUS_FROM_ZEPTO.get(key, status)


# ── reads (safe) ─────────────────────────────────────────────────────────────
async def list_campaigns(client, days: int = 90) -> list[dict]:
    """Every campaign on the account, ONE call. Raw rows, not canonicalised."""
    return await zc.get_campaigns(client, days=days)


async def read_campaign(client, campaign_id: int) -> tuple[str | None, int | None, dict]:
    """(canonical status, daily budget, full detail) in ONE call.

    Writes read per-campaign like this rather than off `list_campaigns`, because a
    write needs the full detail anyway and it must be fresh at write time — not
    taken from a list fetched minutes earlier.
    """
    detail = await zc.get_campaign_detail(client, campaign_id)
    budget = detail.get("daily_budget")
    return (_canonical(detail.get("status")),
            int(budget) if budget is not None else None,
            detail)


async def read_status(client, campaign_id: int) -> str | None:
    status, _, _ = await read_campaign(client, campaign_id)
    return status


async def read_budget(client, campaign_id: int) -> int | None:
    _, budget, _ = await read_campaign(client, campaign_id)
    return budget


async def read_bids(client, campaign_id: int) -> dict[str, int]:
    """Keyword bids, keyed by TEXT — the shape `base.py` specifies.

    ⚠️ LOSSY on Zepto by design of the contract: a keyword bid under both EXACT and
    BROAD collapses to one entry here. `read_bids_by_match` keeps the pair and is
    what the write path uses; this exists for callers that only need a rough view.
    """
    by_pair = await read_bids_by_match(client, campaign_id)
    flat: dict[str, int] = {}
    for (text, match), value in by_pair.items():
        if text in flat and flat[text] != value:
            logger.warning(
                f"Zepto campaign {campaign_id}: keyword {text!r} is bid under several "
                f"match types at different values; read_bids() reports one. Use "
                "read_bids_by_match() where the distinction matters."
            )
        flat[text] = value
    return flat


async def read_bids_by_match(client, campaign_id: int) -> dict[tuple[str, str], int]:
    """Keyword bids keyed by (text, match_type) — the real grain on Zepto."""
    detail = await zc.get_campaign_detail(client, campaign_id)
    return translate.bids_from_detail(detail)


def bids_from_detail(detail: dict) -> dict[str, int]:
    """Bids off an already-fetched detail, saving a call. Same lossiness as
    `read_bids`."""
    return {text: value
            for (text, _match), value in translate.bids_from_detail(detail).items()}


async def read_products(client, campaign_id: int) -> list[dict]:
    """The products a campaign advertises — used to identify our own ad in search."""
    detail = await zc.get_campaign_detail(client, campaign_id)
    return list(detail.get("ad_assets_pla") or [])


async def read_wallet(client) -> dict:
    """Prepaid balance, and a warning when it is low.

    Deliberately NOT a guardrail: an empty wallet does not make a budget change
    wrong, and refusing to act would be worse than acting loudly. Campaigns simply
    stop delivering, which is Zepto's decision to make, not ours.
    """
    wallet = await zc.get_wallet(client)
    balance = wallet.get("current_balance")
    if isinstance(balance, (int, float)) and balance <= 0:
        logger.error(
            f"Zepto wallet is empty (balance {balance}) — campaigns will not deliver "
            "regardless of their budgets, and we cannot top it up (recharge is not in "
            "our permissions). This needs a human."
        )
    return wallet


def set_advertiser(client, advertiser_id) -> None:
    """Pin the ad account for this client's writes (B3).

    Zepto needs no stored id — `brand_id` arrives in the login response — so this
    ASSERTS rather than sets. Blinkit must store one because it appears in no read
    API, and a stale value there writes real money to a dead account; here we can
    check instead of trust.
    """
    if advertiser_id in (None, "", 0):
        return
    if str(advertiser_id) not in {str(b) for b in client.brand_ids}:
        raise RuntimeError(
            f"Zepto account mismatch: the stored account_ref {advertiser_id!r} is not "
            f"among this session's brand ids {client.brand_ids}. Refusing to write — "
            "the session may belong to a different account than the one configured."
        )
    logger.info(f"Zepto account asserted: {advertiser_id}")


async def resolve_advertiser(client):
    """What a write would be scoped to. Derived, not stored."""
    return client.brand_id
