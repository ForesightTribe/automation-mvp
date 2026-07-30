"""The gated write choke-point (docs §12.1) — the ONLY place that mutates Blinkit.

Nothing else in the campaign manager may call an adapter's `apply_*`. Every write
goes through `apply_budget()` / `apply_bid()`, which:
  - are DRY-RUN by default (live must be explicitly requested),
  - run guardrails (bounds / clamp / no-op skip / rate limit),
  - log intent → guardrail → result,
  - and only then delegate the real mutation to the marketplace adapter.

The guardrail checks are PURE functions (unit-tested in tests/test_guardrails.py),
so the safety logic is verifiable without Blinkit.
"""
from campaign_manager import config, logs


# ── Pure guardrail logic (unit-tested, no I/O) ──────────────────────────────

def budget_out_of_bounds(target, *, min_budget: float | None = None,
                         max_budget: float | None = None) -> str | None:
    """Return a reason string if `target` is outside sane bounds, else None."""
    lo = config.MIN_BUDGET if min_budget is None else min_budget
    hi = config.MAX_BUDGET if max_budget is None else max_budget
    if target is None:
        return "budget is None"
    if target < lo:
        return f"budget {target} below min {lo}"
    if target > hi:
        return f"budget {target} above max {hi}"
    return None


def clamp_bid(cpm, min_bid, max_bid) -> int:
    """Clamp a CPM into [min_bid, max_bid] (defense in depth)."""
    return max(int(min_bid), min(int(cpm), int(max_bid)))


def is_noop(new, current) -> bool:
    """True when the computed value equals the current one → skip the write."""
    if new is None or current is None:
        return False
    return int(round(float(new))) == int(round(float(current)))


def exceeds_rate_limit(recent_writes: int, *, limit: int | None = None) -> bool:
    """True when this campaign already has `limit`+ writes in the window."""
    cap = config.MAX_WRITES_PER_WINDOW if limit is None else limit
    return recent_writes >= cap


# ── Live-write arming (B3 account guardrail) ────────────────────────────────

async def arm_live(adapter, client, run_id: str, advertiser: int | None) -> int:
    """Gate a LIVE run on the account guardrail: the tenant's STORED advertiser must exist
    (Blinkit doesn't expose it, so it can't be derived). Sets it on the client so every
    write sends that exact account, and returns it. Raises RuntimeError (→ refused run) if
    none is stored. Never called in dry-run."""
    if advertiser is None:
        raise RuntimeError(
            "no advertiser stored for this tenant — capture it from a Blinkit dashboard PUT "
            "and run `cm set-advertiser -t <id> --id <n>`. Refusing live write.")
    adapter.set_advertiser(client, advertiser)
    logs.live_armed(run_id, advertiser=advertiser)
    return advertiser


# ── The choke-point (only entry to a Blinkit budget/bid mutation) ───────────

async def apply_budget(adapter, client, *, run_id: str, campaign_id, target, current,
                       dry_run: bool, recent_writes: int = 0) -> bool:
    """Guardrailed budget write. Returns True if applied (or would-apply in dry-run),
    False if skipped/rejected. `adapter`/`client` are unused in dry-run."""
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      what="budget", old=current, new=target)

    if is_noop(target, current):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason="no-op (already at target)")
        return False
    reason = budget_out_of_bounds(target)
    if reason:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=reason)
        return False
    if exceeds_rate_limit(recent_writes):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=f"rate limit ({recent_writes} recent writes)")
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True)

    if dry_run:
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True)
        return True

    # LIVE — the single real Blinkit budget mutation.
    resp = await adapter.apply_budget(client, campaign_id, target)
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      detail=f"budget=₹{target}")
    return ok


async def apply_bid(adapter, client, *, run_id: str, campaign_id, keyword, new_cpm,
                    current_cpm, min_bid, max_bid, match_type="EXACT",
                    dry_run: bool, recent_writes: int = 0) -> bool:
    """Guardrailed keyword-bid write. Clamps to [min_bid, max_bid] first."""
    clamped = clamp_bid(new_cpm, min_bid, max_bid)
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id, keyword=keyword,
                      what="bid", old=current_cpm, new=clamped)

    if is_noop(clamped, current_cpm):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason="no-op (already at target bid)")
        return False
    if exceeds_rate_limit(recent_writes):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=f"rate limit ({recent_writes} recent writes)")
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True)

    if dry_run:
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True)
        return True

    # LIVE — the single real Blinkit bid mutation.
    resp = await adapter.apply_bid(client, campaign_id, keyword, clamped, match_type)
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      detail=f"bid=₹{clamped}")
    return ok
