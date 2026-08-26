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
import json

from app.utils.logger import logger
from campaign_manager.marketplaces.zepto import client as zc
from campaign_manager.marketplaces.zepto import endpoints as ep
from campaign_manager.marketplaces.zepto import translate
from campaign_manager.marketplaces.zepto.transport import setup  # noqa: F401  (contract)

# Platform-imposed bounds, published by Zepto at campaigns/metadata
# (budget_types[0].minimum_value). `writes.py` reads these off the adapter, so a
# sub-minimum target is refused with a readable reason instead of arriving as an
# opaque 400. Ours to mirror, not to argue with.
MIN_BUDGET = ep.MIN_DAILY_BUDGET

# Resuming is a dedicated endpoint that flips the campaign back on with its own
# budget and bids intact — nothing is re-submitted, so no budget is required and
# nothing is silently overwritten. Blinkit declares True, where resume IS a full
# campaign re-submission. `writes.py` reads this to decide whether a resume must
# carry a budget; without it a Zepto resume is refused as "budget is None".
RESUME_RESUBMITS = False

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


# ── writes (guarded; only reached via writes.py) ─────────────────────────────
async def _rebased_payload(client, campaign_id: int) -> tuple[dict, dict]:
    """Read the campaign NOW and translate it. Returns (payload, live_detail).

    Always a fresh read. Reusing a detail fetched earlier in the run would let us
    resubmit a campaign as it was minutes ago — silently reverting anything changed
    in the dashboard meanwhile.
    """
    detail = await zc.get_campaign_detail(client, campaign_id)
    options = await _targeting_options(client)
    return translate.to_put(detail, options, campaign_id), detail


async def _targeting_options(client) -> dict:
    """Brand-level city list, cached for the life of the client.

    Needed by every write (a campaign targeting ALL cities sends the explicit list),
    but it is brand-level and static within a run — fetching it per write would
    triple the request count for no benefit.
    """
    cached = getattr(client, "_targeting_options", None)
    if cached is None:
        cached = await zc.get_targeting_options(client)
        client._targeting_options = cached
    return cached


async def _put_one_field(client, campaign_id: int, field_path: str,
                         mutate) -> dict:
    """THE Zepto write primitive: change exactly one field of a live campaign.

    Zepto has no targeted write. Budget and bid are both a PUT of the WHOLE
    campaign, so the body carries geo targeting, the product list and every other
    keyword's bid. A wrong payload does not fail — it rewrites live configuration.

    Hence the guard: build the payload from a fresh read, apply the mutation, and
    diff the two. If anything other than `field_path` moved, refuse.

    That single check catches both failure modes at once — a translator bug, and a
    campaign edited in the dashboard between our read and our write. The second is
    routine here, not exotic: one session per user means a human is often in there.
    """
    base, _detail = await _rebased_payload(client, campaign_id)
    new = json.loads(json.dumps(base))      # deep copy; payloads nest
    mutate(new)

    changed = translate.diff(base, new)
    # `diff` yields "<path>: <old> -> <new>"; compare the PATHS, since the values
    # are exactly what we intend to differ.
    paths = [line.split(":", 1)[0] for line in changed]
    if paths != [field_path]:
        raise RuntimeError(
            f"Zepto write REFUSED for campaign {campaign_id}: expected exactly "
            f"{field_path!r} to change, got {changed or 'no change'}. The campaign "
            "may have been edited since it was read, or the translator has drifted. "
            "Nothing was sent."
        )
    return await zc.update_campaign(client, campaign_id, new)


async def apply_budget(client, campaign_id: int, budget: float) -> dict:
    """Set the daily budget via read-modify-write.

    `writes.py` has already applied policy (no-op, bounds, rate limit) by the time
    this runs; the diff guard here is the mechanism-level backstop.
    """
    target = int(round(float(budget)))
    resp = await _put_one_field(
        client, campaign_id, ".daily_budget",
        lambda p: p.update(daily_budget=target),
    )
    logger.info(f"Zepto campaign {campaign_id}: daily_budget -> ₹{target}")
    # Zepto answers {"message": "Campaign updated successfully"} with no status
    # field; writes.py reads `status`/`success`, so map it into that shape.
    return {"success": True, "response": resp}


async def apply_bid(client, campaign_id: int, keyword: str, cpm: int,
                    match_type: str = "EXACT") -> dict:
    """Set ONE keyword's bid, leaving every sibling untouched.

    ⚠️ `cpm` is the contract's Blinkit-flavoured name; Zepto bids in CPC. The engine
    steps by percentage, which is unit-agnostic, so the value passes through — but
    the absolute floors in config are rupee amounts and need per-platform tuning
    before this is trusted live (see PLAN-cm.md).
    """
    target = int(round(float(cpm)))
    index = await _keyword_index(client, campaign_id, keyword, match_type)
    resp = await _put_one_field(
        client, campaign_id, f".keyword_targeting[{index}].bid_value",
        lambda p: p["keyword_targeting"][index].update(bid_value=target),
    )
    logger.info(
        f"Zepto campaign {campaign_id}: bid[{keyword!r}/{match_type}] -> ₹{target}")
    return {"success": True, "response": resp}


async def _keyword_index(client, campaign_id: int, keyword: str,
                         match_type: str) -> int:
    """Where this keyword sits in `keyword_targeting[]`.

    Matched on (text, match_type) — the text alone is ambiguous, because Zepto bids
    one keyword under several match types at different rates, and writing to the
    wrong one would move a bid nobody asked to move.
    """
    payload, _ = await _rebased_payload(client, campaign_id)
    for i, kw in enumerate(payload.get("keyword_targeting", [])):
        if kw.get("text") == keyword and kw.get("match_type") == match_type:
            return i
    raise RuntimeError(
        f"Zepto campaign {campaign_id} has no keyword {keyword!r} with match type "
        f"{match_type!r}. Refusing to write — adding a keyword is not a bid change."
    )


async def apply_status(client, campaign_id: int, target: str, *,
                       budget: float | None = None) -> dict:
    """Start or stop. A dedicated endpoint, so none of the whole-campaign risk.

    `budget` is accepted for contract compatibility and IGNORED: Blinkit needs one
    because its restart re-submits the campaign, but Zepto's activate is an
    idempotent flip that restores the prior budget and bids by itself.
    """
    canonical = (target or "").strip().lower()
    if canonical in ("paused", "stopped", "pause", "stop"):
        pause = True
    elif canonical in ("running", "active", "resume", "start"):
        pause = False
    else:
        raise RuntimeError(f"Zepto: unknown target status {target!r}")

    if budget is not None:
        logger.info(
            f"Zepto campaign {campaign_id}: ignoring budget=₹{budget} on "
            "activation — Zepto restores the campaign's own budget."
        )
    resp = await zc.set_status(client, campaign_id, pause=pause)
    logger.info(f"Zepto campaign {campaign_id}: {'paused' if pause else 'activated'}")
    return {"success": True, "response": resp}


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


def campaign_name(detail: dict) -> str | None:
    """The campaign's name out of a raw detail. Zepto calls it `campaign_name`."""
    return (detail or {}).get("campaign_name")


def resume_overwrites(detail: dict, budget: float | None) -> dict | None:
    """Nothing is overwritten by a Zepto resume — see RESUME_RESUBMITS."""
    return None
