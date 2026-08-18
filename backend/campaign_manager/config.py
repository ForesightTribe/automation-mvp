"""Campaign-manager v2 configuration — guardrail bounds + the dry-run default.

Self-contained so the CM doesn't touch the shared app Settings. Every value has a
safe default; override via env only if needed (no new REQUIRED .env keys).
"""
import os


def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in ("", "0", "false", "no", "off")


# Every CM action is DRY-RUN unless explicitly armed with --live. Fail-safe (D15).
DRY_RUN_DEFAULT: bool = _flag("CM_DRY_RUN_DEFAULT", True)

# Budget guardrails — writes.py rejects a target outside [MIN_BUDGET, MAX_BUDGET].
# A bug computing budget=0 or an absurd value must be REJECTED, never sent.
MIN_BUDGET: float = float(os.getenv("CM_MIN_BUDGET", "1"))
MAX_BUDGET: float = float(os.getenv("CM_MAX_BUDGET", "100000"))

# Rate limit — refuse to write the same campaign more than MAX_WRITES_PER_WINDOW
# times within RATE_WINDOW_MINUTES (catches a runaway loop, à la the every-minute-cron
# incident). Counted from cm_run_log at apply time.
MAX_WRITES_PER_WINDOW: int = int(os.getenv("CM_MAX_WRITES_PER_WINDOW", "12"))
RATE_WINDOW_MINUTES: int = int(os.getenv("CM_RATE_WINDOW_MINUTES", "60"))

# ── Bid drift-down (cost minimisation at target) ────────────────────────────
#
# Once a keyword HOLDS its target position, shave a little off the bid each tick until it
# stops holding, then snap back to the last bid that worked and stop shaving for a while.
# Finds the cheapest price that keeps the position, and keeps following it as the market
# moves — instead of freezing at whatever price happened to win the climb.
#
# BID_DRIFT_PCT = 0 is the KILL SWITCH: at 0 the optimizer behaves exactly as it did before
# this feature existed (freeze at target, step down only when BETTER than target), so the
# switch is a true revert rather than a half-disabled state.
# Default is 7 = ARMED. Read at import, so the runner must be restarted to change it.
BID_DRIFT_PCT: float = float(os.getenv("CM_BID_DRIFT_PCT", "7"))
# Floor for one drift step, so a small bid still moves (7% of ₹60 would round to nothing).
BID_DRIFT_MIN_STEP: int = int(os.getenv("CM_BID_DRIFT_MIN_STEP", "5"))
# After a drift goes one step too far and loses the position, how long before trying again.
# The dial between cost and position: shorter = cheaper but more dips below target.
BID_DRIFT_PAUSE_MINUTES: int = int(os.getenv("CM_BID_DRIFT_PAUSE_MINUTES", "90"))

# ── Absolute bid ceiling ────────────────────────────────────────────────────
#
# A rule's `max_bid` is OPTIONAL — sometimes the client wants the target position whatever
# it costs. This is the backstop that makes "no ceiling" safe: a rule without one is capped
# here, and a rule WITH one is capped at the lower of the two (so a typo'd max_bid=50000
# can't get through either).
#
# It is a runaway guard, not a tuning knob — set well above any realistic CPM (the highest
# ever observed is ₹900) so it never binds in normal operation. Real spend is bounded by
# the campaign's daily budget long before this: at a ₹10,000 CPM a ₹2,000 daily budget is
# exhausted in 200 impressions and the campaign goes ON_HOLD.
#
# Raising it invalidates any stored unreachable-target relaxation (the ceiling it was
# concluded at changed), which is the correct behaviour — see bid.stored_effective_target.
BID_MAX_ABSOLUTE: int = int(os.getenv("CM_BID_MAX_ABSOLUTE", "10000"))

# The advertiser account for LIVE writes (B3) is stored PER-TENANT in the DB
# (cm_platform_accounts), set via `cm set-advertiser`. Blinkit doesn't expose it in its
# read APIs, so it's captured once at onboarding. No global env var — see repo.get_advertiser.
