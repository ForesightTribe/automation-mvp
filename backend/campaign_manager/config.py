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
# BID_DRIFT_PCT = 0 is the KILL SWITCH and the default: at 0 the optimizer behaves exactly
# as it did before this feature (freeze at target, step down only when BETTER than target).
# Set it to 7 to arm the drift. Read at import, so the runner must be restarted to change it.
BID_DRIFT_PCT: float = float(os.getenv("CM_BID_DRIFT_PCT", "0"))
# Floor for one drift step, so a small bid still moves (7% of ₹60 would round to nothing).
BID_DRIFT_MIN_STEP: int = int(os.getenv("CM_BID_DRIFT_MIN_STEP", "5"))
# After a drift goes one step too far and loses the position, how long before trying again.
# The dial between cost and position: shorter = cheaper but more dips below target.
BID_DRIFT_PAUSE_MINUTES: int = int(os.getenv("CM_BID_DRIFT_PAUSE_MINUTES", "90"))

# The advertiser account for LIVE writes (B3) is stored PER-TENANT in the DB
# (cm_platform_accounts), set via `cm set-advertiser`. Blinkit doesn't expose it in its
# read APIs, so it's captured once at onboarding. No global env var — see repo.get_advertiser.
