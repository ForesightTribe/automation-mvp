"""Zepto's campaign-status vocabulary → the engines' canonical set. PURE.

Separate from `adapter.py` because the API process needs it too — to tell the UI a
campaign's canonical state (running / paused / held / ended) — and the API must never
import an adapter: Blinkit's pulls in Playwright. This module imports nothing but
`endpoints` and the logger.

Two of Zepto's states mean "live, but Zepto is holding delivery", and they are the same
canonical state for a different reason:

  * `DAILY_BUDGET_EXHAUSTED` — today's budget is spent. Raising the budget revives it.
  * `INSUFFICIENT_WALLET_BALANCE` — the prepaid ad wallet is empty. Raising the budget
    does NOTHING; it needs a top-up on Zepto, which is not in our permissions.

Both are `held` (stoppable, not startable, never ours to clear), and `HOLD_REASONS` keeps
the difference so a refusal tells a person the right thing to do.
"""
from app.utils.logger import logger
from campaign_manager.marketplaces.zepto import endpoints as ep

FROM_ZEPTO = {
    ep.STATUS_ACTIVE: "running",
    ep.STATUS_PAUSED: "paused",
    # Live but out of budget — Zepto-imposed, exactly like Blinkit's ON_HOLD.
    ep.STATUS_BUDGET_EXHAUSTED: "held",
    # Live but the wallet is empty — Zepto-imposed too, and not fixable by a budget.
    ep.STATUS_WALLET_EMPTY: "held",
    # Finished. Terminal: nothing restarts it.
    ep.STATUS_ENDED: "ended",
}

# Why a `held` campaign is held, in the words a person acts on.
HOLD_REASONS = {
    ep.STATUS_BUDGET_EXHAUSTED: (
        "campaign is on hold — Zepto has paused delivery because today's budget is spent. "
        "Raise the budget to revive it; there is nothing to restart"),
    ep.STATUS_WALLET_EMPTY: (
        "campaign is on hold — Zepto has paused delivery because the ad wallet is empty. "
        "It needs a wallet top-up on Zepto (we cannot recharge it); a budget change will "
        "not revive it and there is nothing to restart"),
}


def _key(status: str | None) -> str:
    return (status or "").strip().upper()


def canonical(status: str | None) -> str | None:
    """Zepto's status → ours. An unmapped value is returned as-is, on purpose, so a
    guardrail refuses it by name instead of it being coerced into something writable."""
    if not status or not status.strip():
        return None
    key = _key(status)
    if key not in FROM_ZEPTO:
        logger.warning(
            f"Zepto returned an unmapped campaign status {status!r} — treating it as "
            "unknown. If it is legitimate, add it to zepto/status.py.")
    return FROM_ZEPTO.get(key, status)


def hold_reason(status: str | None) -> str | None:
    """Why a held campaign is held, or None when it is not one of Zepto's holds."""
    return HOLD_REASONS.get(_key(status))
