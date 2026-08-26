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

def _money(v) -> str:
    """Render a budget the way it will actually be SENT.

    `--budget` is a float, so a target of 700 logs as "700.0" unless formatted —
    noise in the one line a human reads to approve a money change. Adapters round
    to int before sending, so show the int.
    """
    if v is None:
        return "unknown"
    try:
        return f"₹{int(round(float(v)))}"
    except (TypeError, ValueError):
        return f"₹{v}"


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


# ── Status transitions (docs/campaign-manager.md §8.1) ───────────────────
#
# Unlike budget (a scalar with bounds), a campaign's run state is an ENUM, so the
# guardrail is a transition table. Two states are terminal-ish and must never be
# written through: `ended` (COMPLETED — Blinkit is done with it) and `held`
# (ON_HOLD — Blinkit imposed it, so clearing it is not ours to do).

WRITABLE_STATES = ("running", "paused")


def status_transition_denied(current: str | None, target: str, *,
                             allow_draft: bool = False) -> str | None:
    """Return a reason string if `current → target` must not be written, else None.

    `allow_draft` is True only for an on-demand action (AD8): a human clicking Start on
    a draft means it; a scheduled rule reaching one does not — drafts are often
    incomplete. A no-op (current == target) is NOT rejected here; the caller checks that
    separately so it can log it as a skip rather than a guardrail trip.
    """
    if target not in WRITABLE_STATES:
        return f"refusing to write status {target!r} (only {'/'.join(WRITABLE_STATES)})"
    if current is None:
        return "current status unknown"
    if current in WRITABLE_STATES:
        return None
    if current == "draft":
        if target == "running" and allow_draft:
            return None
        return f"campaign is a draft — {'not startable by a rule' if target == 'running' else 'nothing to pause'}"
    if current == "held":
        # ON_HOLD = Blinkit paused delivery because the campaign's budget ran out. It is
        # still a LIVE campaign, not a stopped one — so it can be stopped, and raising its
        # budget is what revives it. What it CANNOT be is "restarted": there is nothing to
        # restart, which is why Blinkit offers `['UPDATE']` and never `['RESTART']` for it.
        if target == "paused":
            return None
        return ("campaign is ON_HOLD (its budget is exhausted) — raise the budget to revive "
                "it; there is nothing to restart")
    if current == "ended":
        return "campaign is COMPLETED — terminal, cannot be restarted"
    # An unmapped marketplace string. Refuse rather than guess: a new Blinkit status
    # we've never seen is exactly when a blind write is most likely to be wrong.
    return f"unrecognised campaign status {current!r}"


# ── Live-write arming (B3 account guardrail) ────────────────────────────────

async def arm_live(adapter, client, run_id: str,
                   advertiser: int | str | None) -> int | str:
    """Gate a LIVE run on the account guardrail. Never called in dry-run.

    The tenant's stored ad account must exist, and the adapter decides what to do
    with it — the two marketplaces mean different things by "account":

    * **Blinkit** SENDS it. The advertiser id is in no read API, so a stored value
      is the only source, and a stale one spends real money on the wrong account.
    * **Zepto** CHECKS it. The brand id comes from the login response, so the
      adapter asserts the live session matches and refuses if it does not.

    Either way, refusing to run beats writing to an account we cannot identify.
    """
    if advertiser is None:
        raise RuntimeError(
            "no ad account stored for this tenant — run "
            "`cm set-advertiser -t <id> -m <marketplace> --id <value>` first "
            "(Blinkit: the integer advertiser id from a dashboard PUT; "
            "Zepto: the brand UUID from `cm advertiser`). Refusing live write.")
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
    # A marketplace may impose its own floor/ceiling, which is stricter than our
    # config bounds and not ours to argue with — Zepto publishes a ₹500 daily-budget
    # minimum in its own metadata. The ADAPTER declares it (mechanism); this policy
    # enforces it, so an out-of-range target is skipped with a readable reason
    # instead of failing later as an opaque 400 from the marketplace.
    reason = budget_out_of_bounds(
        target,
        min_budget=getattr(adapter, "MIN_BUDGET", None),
        max_budget=getattr(adapter, "MAX_BUDGET", None),
    )
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
        # Pass the SAME detail the live branch does. Without it a dry run printed
        # "would apply  — not sent" with no numbers, which is backwards: the dry run
        # is precisely when a human needs to see what would change, and `write.intent`
        # (which carries old→new) is DEBUG.
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True,
                          detail=f"{_money(current)} → {_money(target)}")
        return True

    # LIVE — the single real budget mutation.
    resp = await adapter.apply_budget(client, campaign_id, target)
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      detail=f"{_money(current)} → {_money(target)}")
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
                             passed=False, reason="no-op (already at target bid)", keyword=keyword)
        return False
    if exceeds_rate_limit(recent_writes):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=f"rate limit ({recent_writes} recent writes)", keyword=keyword)
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True, keyword=keyword)

    # No write.result line here: the bid engine narrates the outcome itself, inside the
    # rule block, in a sentence. Emitting both would report every bid change twice.
    if dry_run:
        return True

    # LIVE — the single real Blinkit bid mutation.
    resp = await adapter.apply_bid(client, campaign_id, keyword, clamped, match_type)
    return bool(resp.get("status") or resp.get("success"))


def _status_detail(target: str, budget: float | None) -> str:
    """What a status write is doing, for the log line.

    `budget` is None on a marketplace whose resume carries none, so it is only
    mentioned when there is one — and never formatted with `:g`, which raises on
    None and would turn a successful write into a crash while reporting itself.
    """
    if target == "running" and budget is not None:
        return f"status={target} budget={_money(budget)}"
    return f"status={target}"


async def apply_status(adapter, client, *, run_id, campaign_id, target, current,
                       dry_run: bool, recent_writes: int = 0, allow_draft: bool = False,
                       budget: float | None = None, overwrites: dict | None = None) -> bool:
    """Guardrailed campaign start/stop. Returns True if applied (or would-apply in dry-run).

    The two directions are NOT symmetric, and HOW asymmetric depends on the
    marketplace — which is why the adapter declares it via `RESUME_RESUBMITS`
    rather than this function assuming:

      - `paused` is cheap and safe everywhere (Blinkit: a bodiless DELETE;
        Zepto: a dedicated pause endpoint).
      - `running` on **Blinkit** is a RESTART: a FULL campaign re-submission that
        rewrites budget, keywords, bids and dates. It therefore REQUIRES a budget
        and inherits the budget bounds guardrail; `overwrites` (AD10) is the diff
        of everything it will replace, logged so a silently-reverted bid is visible
        rather than discovered weeks later.
      - `running` on **Zepto** is an idempotent flip that restores the campaign's
        own budget and bids. Nothing is re-submitted, so demanding a budget would
        refuse every legitimate resume as "budget is None".
    """
    logs.write_intent(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      what="status", old=current, new=target)

    if current == target:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=f"no-op (already {target})")
        return False
    reason = status_transition_denied(current, target, allow_draft=allow_draft)
    if reason:
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=reason)
        return False

    # A RESTART writes a budget, so it passes the same bounds check a budget write
    # does rather than sneaking a value past it (AD14 of the original draft; §5.3).
    # Defaults to True so Blinkit — and any adapter that has not thought about it —
    # keeps the stricter behaviour.
    if target == "running" and getattr(adapter, "RESUME_RESUBMITS", True):
        bad = budget_out_of_bounds(budget)
        if bad:
            logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                                 passed=False, reason=f"restart budget rejected — {bad}")
            return False

    if exceeds_rate_limit(recent_writes):
        logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id,
                             passed=False, reason=f"rate limit ({recent_writes} recent writes)")
        return False

    logs.write_guardrail(run_id, dry_run=dry_run, campaign_id=campaign_id, passed=True)
    if target == "running" and overwrites:
        logs.status_overwrites(run_id, dry_run=dry_run, campaign_id=campaign_id,
                               fields=overwrites)

    if dry_run:
        # Same detail the live branch reports. A dry run that says only "would
        # apply" tells a reviewer nothing about WHAT it would apply.
        logs.write_result(run_id, dry_run=True, campaign_id=campaign_id, applied=True,
                          detail=_status_detail(target, budget))
        return True

    # LIVE — the single real status mutation.
    resp = await adapter.apply_status(client, campaign_id, target, budget=budget)
    ok = bool(resp.get("status") or resp.get("success"))
    logs.write_result(run_id, dry_run=False, campaign_id=campaign_id, applied=ok,
                      detail=_status_detail(target, budget))
    return ok
