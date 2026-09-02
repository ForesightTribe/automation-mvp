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

# ── Bid raise (climbing toward the target position) ─────────────────────────
#
# The step is NOT scaled by distance-from-target any more. Sponsored slots sit ~4 apart
# (1/5/9/13/17), so slot distance was almost always either ≥4 or 1–2 — the old four-tier
# table resolved to ₹100 or ₹25 and its ₹50 tier fired once in 88 recorded steps. Worse,
# slot distance says nothing about RUPEE distance: the bid→position curve is a staircase
# with treads hundreds of rupees wide, so "one slot away" can cost ₹50 or ₹600.
#
# Instead the step escalates on the feedback we already have every tick: if the last raise
# did NOT improve the position we are mid-tread and the next step must be bigger; if it did,
# we crossed a riser and reset. Overshoot is safe because drift-down walks it back — climb
# fast to find the position, descend slowly to find the price.
#
# ESCALATE = 1.0 disables escalation and leaves a flat max(MIN_STEP, PCT%) step.
BID_RAISE_MIN_STEP: int = int(os.getenv("CM_BID_RAISE_MIN_STEP", "50"))
BID_RAISE_PCT: float = float(os.getenv("CM_BID_RAISE_PCT", "8"))
BID_RAISE_ESCALATE: float = float(os.getenv("CM_BID_RAISE_ESCALATE", "1.5"))

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

# ── Per-marketplace tuning ──────────────────────────────────────────────────
#
# Everything above is the DEFAULT, and Blinkit uses it unchanged. A marketplace whose
# bids live at a different order of magnitude overrides only the values that are
# denominated in RUPEES — percentages already scale by themselves.
#
# Zepto bids in CPC at ~₹10-25 (observed: our test campaign at ₹10-12, competitors'
# winning bids ₹15-21). Blinkit bids CPM up to ~₹900. So Blinkit's ₹50 raise floor is
# a 417% jump on a ₹12 Zepto bid, and its ₹5 drift floor a 42% cut — both floors
# dominate the percentages completely and neither is survivable. Note also that
# `int(12 * 8/100) == 0`: at this scale the percentage term rounds away to nothing and
# the min-step floor IS the algorithm, so getting it right is not a nicety.
#
# ⚠️ BID_RAISE_MIN_STEP = 2, not 1. Escalation is integer — `int(1 * 1.5) == 1` — so at
# a ₹1 step it never fires and the climb is a flat ₹1/tick: 13 ticks to cross a ₹21
# winning bid, most of a window spent underbidding. ₹2 is the smallest step that grows.
#
# The platform's own MINIMUM BID is deliberately NOT here. That is a fact Zepto
# publishes, not a knob we tune, so it lives with MIN_DAILY_BUDGET in the adapter's
# endpoints.py — where nobody can "tune" it below what the marketplace accepts.
_BID_TUNING_OVERRIDES: dict[str, dict[str, float]] = {
    "zepto": {
        "BID_RAISE_MIN_STEP": int(os.getenv("CM_ZEPTO_BID_RAISE_MIN_STEP", "2")),
        "BID_RAISE_PCT": float(os.getenv("CM_ZEPTO_BID_RAISE_PCT", "15")),
        "BID_DRIFT_MIN_STEP": int(os.getenv("CM_ZEPTO_BID_DRIFT_MIN_STEP", "1")),
        "BID_MAX_ABSOLUTE": int(os.getenv("CM_ZEPTO_BID_MAX_ABSOLUTE", "100")),
    },
}

# The tunables, and their defaults. A name absent from a platform's override block
# resolves here — so a constant with NO override is provably identical on every
# marketplace, which is what protects live Blinkit from a Zepto-driven change.
_BID_DEFAULTS: dict[str, float] = {
    "BID_RAISE_MIN_STEP": BID_RAISE_MIN_STEP,
    "BID_RAISE_PCT": BID_RAISE_PCT,
    "BID_RAISE_ESCALATE": BID_RAISE_ESCALATE,
    "BID_DRIFT_PCT": BID_DRIFT_PCT,
    "BID_DRIFT_MIN_STEP": BID_DRIFT_MIN_STEP,
    "BID_DRIFT_PAUSE_MINUTES": BID_DRIFT_PAUSE_MINUTES,
    "BID_MAX_ABSOLUTE": BID_MAX_ABSOLUTE,
}


def bid_tuning(platform: str, name: str):
    """The value of bid tunable `name` for `platform`, falling back to the default.

    Raises on an unknown name rather than returning a default: a typo'd tunable would
    otherwise silently resolve to whatever the fallback happened to be, which is the
    kind of bug that only shows up as a campaign spending oddly.
    """
    if name not in _BID_DEFAULTS:
        raise KeyError(
            f"unknown bid tunable {name!r} — known: {sorted(_BID_DEFAULTS)}")
    return _BID_TUNING_OVERRIDES.get(platform, {}).get(name, _BID_DEFAULTS[name])


# The advertiser account for LIVE writes (B3) is stored PER-TENANT in the DB
# (cm_platform_accounts), set via `cm set-advertiser`. Blinkit doesn't expose it in its
# read APIs, so it's captured once at onboarding. No global env var — see repo.get_advertiser.
