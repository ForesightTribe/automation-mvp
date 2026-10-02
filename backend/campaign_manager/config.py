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

# ── Settling an automation that has ended (campaign_manager/lifecycle.py) ───
#
# When an automation's last window closes, its own end-of-window run tears it down: the bid
# back to its floor, the budget back to its default, the campaign stopped if asked. If that
# run never lands, an hourly settle pass retries it — at most SETTLE_MAX_ATTEMPTS times, and
# only within SETTLE_MAX_AGE_HOURS of the close. Past that a person has had time to take
# over, and tearing down would overwrite what they chose.
SETTLE_MAX_ATTEMPTS: int = int(os.getenv("CM_SETTLE_MAX_ATTEMPTS", "3"))
SETTLE_MAX_AGE_HOURS: float = float(os.getenv("CM_SETTLE_MAX_AGE_HOURS", "24"))

# ── Multi-store measurement + stock (coverage.py, stock.py) ─────────────────
#
# A keyword automation measures at up to BID_MAX_STORES frozen stores per city
# (`cm_city_stores` ranks 1..N). HOW it uses them is the marketplace's store strategy:
#
#   EVERY_STORE (Blinkit) — read every store each tick and bid for target at every one where
#       the campaign is in stock (coverage.py). N stores = N searches a tick.
#   ROTATE (Zepto, C6) — read ONE store a tick and move to the next only when that one can't
#       sell the campaign (rotation.py). Zepto's anonymous search allows a few requests a
#       minute, and its search hides sold-out products, so it can't afford — or use — a read
#       of every store. The set is still 3 deep: it is the fallback order, not a fan-out.
BID_MAX_STORES: int = int(os.getenv("CM_BID_MAX_STORES", "3"))
_MAX_STORES_OVERRIDES: dict[str, int] = {
    "zepto": int(os.getenv("CM_ZEPTO_BID_MAX_STORES", "3")),
}

EVERY_STORE = "every_store"
ROTATE = "rotate"
_STORE_STRATEGY: dict[str, str] = {"zepto": ROTATE}


def max_stores(platform: str) -> int:
    """How many ranked stores a city may measure at on this marketplace."""
    return max(1, min(BID_MAX_STORES, _MAX_STORES_OVERRIDES.get(platform, BID_MAX_STORES)))


def store_strategy(platform: str) -> str:
    """`EVERY_STORE` or `ROTATE` — see above. Anything unlisted keeps Blinkit's behaviour."""
    return _STORE_STRATEGY.get(platform, EVERY_STORE)


# ROTATE only: once a full cycle of stores has come back unable to sell the campaign, the bid
# is held and ONE store is checked every this many minutes (in rotation) until one can sell
# again. The ~15-minute tick keeps running; it just doesn't search while resting.
# 30, not 60 (2026-10-02): stock at a Zepto store is a unit or two and turns over within
# hours, so an hourly check left a restock unseen for up to 3 hours across a 3-store set.
STOCK_REST_MINUTES: int = int(os.getenv("CM_STOCK_REST_MINUTES", "30"))


# Stock is one brand search per store, reused across runs until it is this old. Inventory
# does not flip every 15 minutes, and one read serves every keyword at the store.
STOCK_MAX_AGE_MINUTES: int = int(os.getenv("CM_STOCK_MAX_AGE_MINUTES", "60"))
# Cap on that brand search when the client's watchlist row sets no `brand_cap`. Blinkit pads
# a brand search with other brands' products; walking the whole tail invites HTTP 429.
STOCK_DEFAULT_BRAND_CAP: int = int(os.getenv("CM_STOCK_DEFAULT_BRAND_CAP", "48"))
# `cm_bid_store_reads` grows with time (a row per store per tick), so it is trimmed.
STORE_READS_RETENTION_DAYS: int = int(os.getenv("CM_STORE_READS_RETENTION_DAYS", "30"))
# A store still not showing our ad after this many checks with the bid ALREADY at its ceiling
# is left out for the rest of the window: the ceiling can't buy a slot there, and chasing it
# would hold every other store at max_bid too. 0 disables giving up.
BID_GIVE_UP_TICKS: int = int(os.getenv("CM_BID_GIVE_UP_TICKS", "2"))
# Warn once a store has given no usable reading this many checks in a row — the decision is
# quietly running on fewer stores. Warning, not error: it is not an outage.
STORE_PROBLEM_WARN_TICKS: int = int(os.getenv("CM_STORE_PROBLEM_WARN_TICKS", "2"))

# Zepto keyword-bid automations: OFF by default (2026-09-29) — see
# `marketplaces.keyword_bidding_refusal`. `1` turns them back on (a supervised test).
ZEPTO_KEYWORD_BIDDING: bool = _flag("CM_ZEPTO_KEYWORD_BIDDING", False)

# Zepto's shopper search through a proxy: OFF by default (2026-09-30).
#
# Zepto's firewall refuses the VM's own address outright (a data-centre range), so on the VM
# — and only there — the bid engine's rank and stock reads go out through a consumer-line
# proxy. Through a proxy Zepto also refuses our normal replayed search, so a proxied session
# searches by typing into Zepto's own page
# (`scraper/platforms/zepto/public_data/typed_search.py`); the switch selects both at once.
# Nothing else uses it — not the scrapes, not the Explorer, not the ads API.
#
#   CM_ZEPTO_SHOPPER_PROXY_ON=1                           the switch
#   CM_ZEPTO_SHOPPER_PROXY=http://user:pass@host:port     the address. A SECRET: that
#       machine's .env only — never in git, never logged (host:port is all that is printed).
#
# On WITHOUT a usable address holds every bid and says why. It never quietly goes direct.
ZEPTO_SHOPPER_PROXY_ON: bool = _flag("CM_ZEPTO_SHOPPER_PROXY_ON", False)
ZEPTO_SHOPPER_PROXY: str = os.getenv("CM_ZEPTO_SHOPPER_PROXY", "").strip()
# A search Zepto refuses ("login to search") waits about a minute before its one retry. This
# is the most a single proxied run may spend waiting like that; past it, a refused search
# fails at once and its bid is held, so one bad spell cannot eat the whole 15-minute tick.
ZEPTO_SHOPPER_WAIT_BUDGET_S: float = float(os.getenv("CM_ZEPTO_SHOPPER_WAIT_BUDGET_S", "180"))

# ── Prepaid ad wallet (wallet.py, ZC-C12) ───────────────────────────────────
#
# Zepto ads spend from a prepaid wallet; when it runs dry every campaign stops delivering
# whatever its budget says, and topping it up is not in our permissions. Below this balance
# (₹) each run warns; at zero it is an ERROR, which alerts. Default ≈ a day of Brik Oven's
# spend (₹5–9k/day in Sept 2026). A marketplace without a wallet is never checked.
WALLET_WARN_BELOW: float = float(os.getenv("CM_WALLET_WARN_BELOW", "5000"))
# The engines run every 15–60 minutes; a History line on every run would bury the real
# changes. Logs get it every run, History at most once per this many hours.
WALLET_NOTE_EVERY_HOURS: float = float(os.getenv("CM_WALLET_NOTE_EVERY_HOURS", "6"))

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
