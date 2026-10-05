"""The prepaid ad wallet — read once per engine run, warned about when low (ZC-C12).

Zepto ads spend from a WALLET. When it empties, every campaign stops delivering no matter
what its budget is — Zepto marks them `INSUFFICIENT_WALLET_BALANCE` — and recharging is not
in our permissions. So a low wallet silently makes every budget and bid change we make
pointless, and the only useful response is to tell a person early.

A WARNING, never a guardrail. An empty wallet does not make a budget change wrong (the
budget still applies the moment the wallet is topped up), and refusing to act would turn a
billing problem into a missed schedule on top of it.

Marketplace-agnostic: an adapter with a wallet declares `read_wallet(client)`; one without
(Blinkit) is never checked. Never raises — a failed wallet read must not cost a run.
"""
from datetime import timedelta

from app.utils.time import now_ist
from campaign_manager import config, logs, repo


def assess(balance, *, warn_below: float) -> tuple[str, str] | None:
    """`(level, sentence)` for a balance worth mentioning, else None. Pure."""
    if not isinstance(balance, (int, float)):
        return None
    if balance <= 0:
        return ("error",
                f"the ad wallet is EMPTY (₹{balance:,.0f}) — campaigns will not deliver "
                f"whatever their budgets say, and we cannot top it up. Recharge it on Zepto.")
    if balance < warn_below:
        return ("warning",
                f"the ad wallet is low: ₹{balance:,.0f} left (warning below "
                f"₹{warn_below:,.0f}) — campaigns stop delivering when it runs out. "
                f"Recharge it on Zepto.")
    return None


async def check(adapter, client, *, tenant_id, platform: str, run_id: str,
                dry_run: bool) -> float | None:
    """Read the wallet and say so if it is low. Returns the balance, or None if unknown."""
    reader = getattr(adapter, "read_wallet", None)
    if reader is None:
        return None
    try:
        wallet = await reader(client)
        balance = (wallet or {}).get("current_balance")
    except Exception as e:
        logs.note(run_id, f"wallet unreadable ({e})", dry_run=dry_run, level="warning")
        return None

    verdict = assess(balance, warn_below=config.WALLET_WARN_BELOW)
    if verdict is None:
        logs.note(run_id, f"ad wallet ₹{balance:,.0f}", dry_run=dry_run, level="debug")
        return balance
    level, said = verdict
    # The run log gets the number; History keeps the full sentence for the client.
    logs.note(run_id, (f"wallet EMPTY: ₹{balance:,.0f} · ads not delivering — recharge on "
                       f"{platform.title()}") if level == "error" else
              f"wallet low: ₹{balance:,.0f} (warns below ₹{config.WALLET_WARN_BELOW:,.0f})",
              dry_run=dry_run, level=level)
    await _history_note(tenant_id, platform, run_id, level, said, balance, dry_run)
    return balance


async def _history_note(tenant_id, platform, run_id, level, said, balance, dry_run) -> None:
    """One History line, at most once per `WALLET_NOTE_EVERY_HOURS`. Never raises."""
    try:
        last = await repo.last_run_log_at(tenant_id, platform, kind="wallet")
        if last is not None and now_ist() - last < timedelta(
                hours=config.WALLET_NOTE_EVERY_HOURS):
            return
        await repo.write_run_log([{
            "tenant_id": tenant_id, "platform": platform, "run_id": run_id,
            "kind": "wallet", "campaign_id": None, "campaign_name": None, "keyword": None,
            "action": "error" if level == "error" else "warn",
            "old_value": None, "new_value": balance, "reason": said,
            "dry_run": dry_run, "success": False,
        }])
    except Exception as e:
        logs.note(run_id, f"could not record the wallet warning in History: {e}",
                  dry_run=dry_run, level="warning")
