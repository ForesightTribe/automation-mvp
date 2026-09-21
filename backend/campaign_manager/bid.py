"""Bid-optimizer orchestration (MP-agnostic).

A ~15-min control loop: for each active bid rule, read the keyword's live sponsored
position, step the CPM toward the target position, and route the change through the
write choke-point. Dry-run by default (positions are read, no bid is written). Runtime
state (`last_*`) is persisted to `cm_bid_runtime` — no JSON.

Each window is bracketed by the floor: the first fire of a window writes `min_bid` (and
re-checks until Blinkit reads it back), and the end-of-window `--reset` run writes it
again. The pair is deliberate — the reset is best-effort (the campaign may be dark, or
Blinkit may refuse), and without the window-open floor a reset that failed last night is
never recovered, so the bid ratchets up across days until it pins at `max_bid`. An all-day
rule's run of consecutive days counts as ONE window: no floor at midnight, and a reset only
where the run ends (`window.run_start`, `reconciler._bid_reset_fires`).

The decision (`compute_bid` / `next_raise_step` / `_in_window`) is **pure** — ported from
`ad_campaigns.bid_optimizer` (validated v1 logic) and unit-tested in
tests/test_bid_logic.py without Blinkit or the DB. The Blinkit-specific position
sourcing lives behind `adapter.resolve_position` (D17). MVP scrapes every keyword live;
tiering (cheap sources for at-target keywords) is deferred — see the impl-doc backlog.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import settings
from app.utils.time import now_ist
from campaign_manager import config, coverage, lifecycle, logs, repo, stock, window, writes
from campaign_manager.marketplaces import get_adapter

HOLD_MINUTES = 10                       # after a bid change, wait this long before nudging again
_DEFAULT_LAT, _DEFAULT_LON = 12.9767, 77.5713   # Bengaluru fallback when a rule has no location

# The end-of-window reset is FIRED a minute early (see reconciler._bid_reset_fires) so the
# bid drops back before the budget engine — a parallel lane — can stop the campaign, after
# which Blinkit refuses bid writes. This look-ahead is what makes the early fire see the
# window as closed; it must exceed the reconciler's lead so a few seconds of browser-setup
# drift can't land it back inside the window.
RESET_LOOKAHEAD_MINUTES = 2

# Said when an automation is paused or deleted while a tick is mid-flight (see
# `_still_active`). One sentence, in the client's language, because it lands in the log
# beside the decision it is cancelling.
_PAUSED_MIDRUN = ("this automation was paused or deleted while the run was in progress — "
                  "leaving the bid alone")


# ── Pure decision logic (unit-tested) ────────────────────────────────────────
#
# WHEN a rule applies is answered by `campaign_manager.window`, shared with the budget
# engine, the reconciler and the API's status. These two are the bid engine's view of it:
# a rule in bid vocabulary (`stop_time` / `stop_date`) in, translated once.

def _in_window(rule: dict, now: datetime) -> bool:
    """Is the rule active right now? — `window.in_window` (overnight tails, the weekday
    filter, `once` dates, the exclusive end)."""
    return window.in_window(window.from_bid(rule), now)


def _window_start(rule: dict, now: datetime) -> datetime:
    """When the rule's CURRENT window opened — `window.window_start`. Only meaningful while
    the rule is in window (callers filter on `_in_window` first)."""
    return window.window_start(window.from_bid(rule), now)


def _window_opened(rule: dict, updated_at: datetime | None, now: datetime) -> bool:
    """Has this window already been opened — i.e. is the floor already behind us?

    Measured from `window.run_start`, not `_window_start`: an all-day rule's midnight joins
    yesterday's window to today's, so a tick at 00:01 that last persisted at 23:46 is carrying
    on, not opening. Everything else keeps anchoring to its own window's start."""
    return bool(updated_at and updated_at >= window.run_start(window.from_bid(rule), now))


def is_recovery(position: float, target: int, current_cpm: int,
                last_holding_cpm: int | None) -> bool:
    """Did OUR OWN drift cause this miss, rather than the market moving against us?

    True when we're off target at a bid BELOW one we know was holding — which only happens
    when the last drift step went too far. If we're off target at (or above) the last
    holding bid, the market moved and a normal raise is the right answer. The orchestration
    uses the same predicate to decide when to start the drift pause, so the two can't drift
    apart."""
    return (position > target and last_holding_cpm is not None
            and int(last_holding_cpm) > int(current_cpm))


def next_raise_step(current_cpm: int, last_step: int | None, improved: bool, *,
                    min_step: int, pct: float, escalate: float) -> int:
    """How much to add on this raise.

    Deliberately NOT a function of distance-from-target. Slots sit ~4 apart, so slot
    distance was almost always ≥4 or 1–2 and the old tier table collapsed to two values
    (its ₹50 tier fired once in 88 recorded steps) — and slot distance says nothing about
    rupee distance anyway, because the bid→position curve is a staircase with treads
    hundreds wide.

    What it uses instead is the one signal each tick already gives us: did the LAST raise
    move the position?
      - it didn't → we are mid-tread, whatever we added wasn't enough → escalate;
      - it did   → we crossed a riser → back to base, so we don't blow past the next one.

    Capped at the current bid, so one tick can never more than double it.
    """
    base = max(int(min_step), int(current_cpm * pct / 100))
    step = base if (last_step is None or improved) else max(base, int(last_step * escalate))
    return max(int(min_step), min(step, int(current_cpm)))


def resolve_ceiling(rule_max_bid: int | None, absolute: int) -> int:
    """A rule's effective bid ceiling.

    `max_bid` is optional: sometimes the target position is wanted whatever it costs. The
    absolute cap makes that safe without special-casing anything downstream — every caller
    still receives a plain int, so the decision logic, the clamps and their tests are
    untouched by the feature. A rule that DOES set a ceiling is capped at the lower of the
    two, which also catches a typo'd `max_bid`."""
    if rule_max_bid is None:
        return int(absolute)
    return min(int(rule_max_bid), int(absolute))


def effective_floor(rule_min_bid: int, marketplace_floor: int | None) -> int:
    """A rule's effective minimum bid — the sibling of `resolve_ceiling` (V7.6).

    The marketplace publishes its own minimum PER KEYWORD, and it can move. A rule written
    weeks ago cannot know today's, so the engine bids at the higher of the two: below the
    marketplace floor the write is refused or silently raised anyway, and a rule's `min_bid`
    is a statement of the client's own floor, not a claim about what the auction allows.

    `None` means we could not read a floor — a lookup failure, or a keyword the campaign
    does not carry yet. That must fall back to the rule's own value: refusing to bid because
    a read failed is worse than bidding at the configured minimum.
    """
    if marketplace_floor is None:
        return int(rule_min_bid)
    return max(int(rule_min_bid), int(marketplace_floor))


def stored_effective_target(rule_target: int, max_bid: int, stored_target: int | None,
                            stored_at_max: int | None) -> int | None:
    """The relaxed target still in force, or None to chase the rule's real target.

    Distrusted whenever the ceiling it was derived at no longer matches the rule's — an
    edit to `max_bid` invalidates the conclusion in both directions. Raising it is the
    dangerous one: a stale relaxed target would have the optimizer keep drifting DOWN just
    after being given more room to climb. Also distrusted if it isn't strictly worse than
    the real target, which would make it meaningless."""
    if stored_target is None or stored_at_max is None:
        return None
    if int(stored_at_max) != int(max_bid):
        return None
    if int(stored_target) <= int(rule_target):
        return None
    return int(stored_target)


def should_relax_target(position: float, rule_target: int, current_cpm: int, max_bid: int,
                        last_position: float | None) -> bool:
    """Is the real target out of reach at the ceiling, so the position we DID get should
    become the working target?

    True only while pinned at `max_bid` with nothing left to try, and only after the
    previous tick also missed — one bad scrape must not relax a target for the rest of the
    window. Left alone, this state is the worst outcome in the system: the bid sits at the
    maximum, every tick recomputes the same value, the no-op guardrail rejects it, and the
    campaign pays the ceiling for a position the ceiling did not buy."""
    return (position > rule_target and int(current_cpm) >= int(max_bid)
            and last_position is not None and last_position > rule_target)


def compute_bid(position: float, target: int, current_cpm: int, min_bid: int, max_bid: int,
                last_position: float | None, minutes_since_change: float | None, *,
                last_holding_cpm: int | None = None, drift_paused: bool = False,
                drift_pct: float = 0.0, drift_min_step: int = 5,
                raise_step: int, position_text: str | None = None) -> tuple[int | None, str]:
    """The bid decision. Returns (new_cpm | None, reason); None = no change.

    "Holding" means position is at target **or better** — better is a success, not an error
    to correct. Blinkit's sponsored slots sit on a sparse lattice (observed positions are
    ~89% 1/5/9/13/17), so a target of 3 is frequently unreachable and demanding exact
    equality would mean never settling. Zepto's slots move around instead, which the same
    `>` / `<=` comparisons handle without change.

    Three outcomes when off target: `recover` (snap back precisely — our drift overshot),
    `hold` (inside the reflection window, position hasn't improved), or `raise`.

    `raise_step` is REQUIRED — the caller computes it with `next_raise_step`, which is the
    only place that knows whether the last raise moved us. It used to be optional, falling
    back to a fixed ₹100/50/25/12.5 ladder; that ladder is gone (see below).

    When holding, `drift_pct` decides everything. Above 0, holding shaves `drift_pct`% off
    the bid each tick, gated on two consecutive holding observations and on the
    post-overshoot pause. At **0 the kill switch simply FREEZES the bid** — hold the
    position, never trim.

    ⚠️ 0 used to mean "step down the ₹100/50/25/12.5 ladder when better than target". That
    ladder was removed 2026-09-01: it is denominated in rupees at Blinkit's CPM scale, so
    on a ₹12 Zepto CPC it produced a ₹12.5-₹100 step — a safety switch more dangerous than
    the feature it disabled, and reachable ONLY in the incident where someone reaches for
    it. Freezing is what "turn off cost trimming" is assumed to mean anyway. Production
    runs at the default of 7, so nothing live changed.
    """
    drift_on = drift_pct > 0

    if position > target:                        # ── off target ──
        # Our own drift went a step too far: go straight back to the bid we KNOW was
        # holding, rather than a fresh raise that would overshoot past it and spend the
        # next hour drifting back down.
        if drift_on and is_recovery(position, target, current_cpm, last_holding_cpm):
            return int(last_holding_cpm), (
                f"dropped to position {position:g} after trimming — going back to "
                f"₹{last_holding_cpm}, which was holding")
        # HOLD: position hasn't improved since the last change and we're still inside the
        # reflection window → wait for Blinkit to catch up rather than over-bidding.
        if (last_position is not None and position >= last_position
                and minutes_since_change is not None and minutes_since_change < HOLD_MINUTES):
            return None, (
                f"holding at ₹{current_cpm} — position has not improved since the last "
                f"change {minutes_since_change:.0f} min ago")
        # `raise_step` comes from `next_raise_step`, which escalates while the position
        # isn't moving. It is the caller's job precisely because only the caller knows
        # that history.
        step = raise_step
        new_cpm = min(int(current_cpm + step), int(max_bid))
        # `position_text` replaces the number when it is a placeholder — "position 49" only
        # means "not on the page", and a client reading History should see that instead.
        why = (position_text if position_text is not None
               else f"position {position:g} is worse than target {target}")
        return new_cpm, f"raising to ₹{new_cpm} (+₹{step:g}) because {why}"

    # ── holding (at target or better) ──
    # Kill switch: hold the position and never trim. Deliberately a no-op rather than a
    # step down — a rupee-denominated ladder cannot be right on two marketplaces whose
    # bids differ by ~40x, and the switch exists to make the optimizer STOP, not to make
    # it do something else.
    if not drift_on:
        return None, (f"target held at position {position:g} — cost trimming is switched "
                      f"off, so the bid stays at ₹{current_cpm}")

    # A single reading was unreliable ~28% of the time in the v1 log, so never spend a
    # write on one. Requiring the PREVIOUS tick to have held too also stops us undoing a
    # raise the moment it lands — the climb gets one tick to prove itself first.
    if last_position is None or last_position > target:
        return None, (f"target held at position {position:g} — no change yet, waiting for "
                      f"a second confirmation before trimming")
    if drift_paused:
        return None, (f"target held at position {position:g} — cost trimming paused after "
                      f"overshooting")

    step = max(current_cpm * drift_pct / 100.0, float(drift_min_step))
    new_cpm = max(int(current_cpm - step), int(min_bid))
    if new_cpm >= current_cpm:                   # already sitting on min_bid
        return None, (f"target held at position {position:g} — already at the ₹{min_bid} "
                      f"floor")
    return new_cpm, (f"target held, trimming cost to ₹{new_cpm} (−{drift_pct:g}%) to find "
                     f"the cheapest bid that keeps position {position:g}")


def _minutes_since(iso_ts: str | None, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        return (now - datetime.fromisoformat(iso_ts)).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def _rule_dict(r) -> dict:
    return {"type": r.type, "date": r.date, "days": getattr(r, "days", None),
            "start_date": r.start_date, "stop_date": r.stop_date,
            "start_time": r.start_time, "stop_time": r.stop_time}


def measurement_stores(rule, city_stores: dict, saved_ids: dict | None = None) -> list:
    """Where this rule reads its position: `[repo.MeasurementStore, …]`, anchor first.

    A rule saved by city (`city_id` set) measures at that city's FROZEN SET — the client's
    set, else the global one (`repo.city_stores_for`) — looked up on every run, so changing a
    city's stores moves every automation measuring there on the next tick, with no edits. A
    city with nothing frozen, and a rule pinned to one store (`city_id` NULL), keep the single
    store saved on the rule. Only a rule with neither falls back to the Bengaluru default.

    `saved_ids` maps saved coordinates to their catalog store id, so a saved store's stock can
    be looked up; without it that store's stock is unknown (it still counts).
    `getattr`: pre-migration rows and test doubles carry no `city_id` at all.
    """
    city_id = getattr(rule, "city_id", None)
    frozen = city_stores.get(city_id) if city_id is not None else None
    if frozen:
        return list(frozen)
    if rule.lat is not None and rule.lon is not None:
        lat, lon = float(rule.lat), float(rule.lon)
        return [repo.MeasurementStore(
            lat=lat, lon=lon, label=(rule.location_name or "").strip(),
            merchant_id=(saved_ids or {}).get((lat, lon), ""), city_id=city_id, source="rule")]
    return [repo.MeasurementStore(lat=_DEFAULT_LAT, lon=_DEFAULT_LON, label="", merchant_id="",
                                  city_id=None, source="default")]


def measurement_point(rule, city_stores: dict) -> tuple[float, float, str | None, str]:
    """The ANCHOR of `measurement_stores`, as `(lat, lon, label, source)`."""
    anchor = measurement_stores(rule, city_stores)[0]
    return float(anchor.lat), float(anchor.lon), (anchor.label or None), anchor.source


# ── Orchestration ────────────────────────────────────────────────────────────

async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              reset: bool = False, platform: str = "blinkit",
              run_id: str | None = None) -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = run_id or logs.new_run_id()
    started = now_ist()
    logs.run_start(run_id, "bid_reset" if reset else "bid_optimizer", tenant_id,
                   dry_run=dry_run, platform=platform,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    now = started
    # Active rules in EVERY calendar state. The optimizer narrows to in-window below. The reset
    # must still see a rule whose window closed a moment ago — which, if that was its last
    # window, is already ENDED at that minute — and it picks only those (`_reset_selection`).
    pairs = await repo.get_bid_rules(tenant_id, platform, state="active",
                                     calendar=repo.ANY_CALENDAR)
    if reset:                                   # end-of-window de-escalation, not optimization
        return await _reset_run(tenant_id, platform, pairs, now, run_id, dry_run)
    # Open NOW *and* still open once the reset's look-ahead has passed.
    #
    # The second half is what keeps the optimizer and the reset off the same keyword. The
    # reset evaluates windows at `now + RESET_LOOKAHEAD_MINUTES` (it is fired a minute early
    # so the bid drops before the budget engine can stop the campaign), so for ~2 minutes at
    # window close it considers a keyword closed while this loop still considered it open.
    # While the job guard treated a reset as an optimizer run they could never overlap, so
    # that sliver was harmless. Now that they can run together (migration a2d5f81c9b34) it
    # would be a genuine race over one bid — the optimizer raising it at the same moment the
    # reset drops it, last writer wins, which is exactly what the reset exists to prevent.
    #
    # Skipping it costs nothing: a keyword two minutes from closing is about to be reset to
    # its floor, so raising its bid was always money spent on a position we are about to
    # give up.
    #
    # ⚠️ BOTH tests are needed, not just the look-ahead one. Testing only `now + lookahead`
    # would also open every window two minutes EARLY, which would start bidding before the
    # window the client configured.
    soon = now + timedelta(minutes=RESET_LOOKAHEAD_MINUTES)
    active = [(r, rt) for r, rt in pairs
              if _in_window(_rule_dict(r), now)
              and _in_window(_rule_dict(r), soon)]
    if not active:
        logs.note(run_id, "No keyword automations are in window right now", dry_run=dry_run)
        logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    # Where each rule measures: its city's frozen store SET (the client's, else the global one),
    # resolved NOW rather than read off the rule — see `measurement_stores`. Two queries for the
    # whole run, made before any browser exists so a DB blip cannot leak one.
    city_stores = await repo.city_stores_for(
        platform, tenant_id, {getattr(r, "city_id", None) for r, _ in active},
        run_id=run_id, dry_run=dry_run)
    saved_ids = await repo.store_ids_at(platform, _saved_coords(active, city_stores))
    rule_stores = {r.id: measurement_stores(r, city_stores, saved_ids) for r, _ in active}
    # What each rule's stores showed on recent ticks — to give up on a store that stays out of
    # reach at the ceiling, and to warn about one that keeps giving unusable readings.
    # Fail-open: without it nothing is given up and nothing is warned about.
    try:
        store_history = await repo.recent_store_reads(
            tenant_id, platform, [r.id for r, _ in active],
            since=now - timedelta(hours=26), dry_run=dry_run)
    except Exception as e:
        store_history = {}
        logs.note(run_id, f"could not load recent store readings ({e}) — no store is given up "
                          f"this run", dry_run=dry_run, level="warning")

    adapter = get_adapter(platform)
    mp = platform.title()          # what a human reads in the log lines below
    # Resolved ONCE per run so every decision, log line and runtime write in this run
    # agrees about whether drift is armed. Read per-marketplace: the percentages are
    # shared, but a marketplace may override the rupee floors they bottom out at.
    drift_pct = config.bid_tuning(platform, "BID_DRIFT_PCT")
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError as e:
        logs.session_expired(run_id, dry_run=dry_run)
        await _record_run_blocked(
            tenant_id, platform, run_id, [r for r, _ in active],
            _plain(e, f"could not sign in to {mp}, so no bids were changed"), dry_run)
        logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run, platform=platform)

    # Live runs must pass the account guardrail (B3) before any write.
    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            await _record_run_blocked(
                tenant_id, platform, run_id, [r for r, _ in active],
                _plain(e, "the ad account could not be confirmed, so no bids were changed"),
                dry_run)
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    processed = applied = skipped = errors = 0
    runtime_rows: list[dict] = []
    log_rows: list[dict] = []
    # Catalogue write-back, flushed once with the rows above (campaign_manager/writes.py).
    patches: list[dict] = []
    store_rows: list[dict] = []            # cm_bid_store_reads — what each store showed
    bids_cache: dict[int, dict] = {}       # campaign_id → {keyword: cpm}  (one detail fetch/campaign)
    products_cache: dict[int, list] = {}   # campaign_id → [products]
    status_cache: dict[int, str | None] = {}   # campaign_id → canonical status (same fetch)
    # campaign_id → {(keyword, match_type): marketplace minimum bid} (V7.6).
    floors_cache: dict[int, dict] = {}
    # (keyword, lat, lon) → (results, error). ONE consumer-search scrape per distinct pair
    # for the whole run — see the note at the fetch site.
    positions_cache: dict[tuple, tuple[list, Exception | None]] = {}

    # One consumer-side session for every keyword in the run — a single warm-up, then a
    # bare API request per (keyword, store). It used to be one Playwright driver + Chromium
    # PER KEYWORD, each doing two full page loads, which cost ~10-60s apiece and made
    # Blinkit see a dozen cold clients from one IP within minutes.
    # The warm-up uses the first rule's store so the session is established somewhere real;
    # every search then overrides lat/lon in the headers anyway.
    logs.note(run_id, f"{len(active)} keyword automations active in this window",
              dry_run=dry_run)
    _anchor0 = rule_stores[active[0][0].id][0]
    pos_session = await adapter.open_position_session(pw, float(_anchor0.lat),
                                                      float(_anchor0.lon))
    stock_searches = 0

    try:
        # Stock for every store this run measures at, before any decision: one brand search
        # per store, cached for an hour (campaign_manager/stock.py). Never raises — knowing
        # nothing just means every store counts.
        stock_by_store, stock_searches = await stock.load(
            adapter, pos_session, tenant_id, platform,
            [s for stores in rule_stores.values() for s in stores],
            now=now, run_id=run_id, dry_run=dry_run)
        for rule, runtime in active:
            processed += 1
            cid, kw = rule.campaign_id, rule.keyword
            logs.blank(run_id, dry_run=dry_run)
            logs.rule_header(run_id, dry_run=dry_run, index=processed, total=len(active),
                             campaign_name=rule.campaign_name, campaign_id=cid)
            # Resolved ONCE, so everything downstream — the decision, the clamps, the
            # relaxation — keeps taking a plain int and never has to know `max_bid` is
            # optional. `rule.max_bid` must not be read directly below this line.
            ceiling = resolve_ceiling(rule.max_bid, config.bid_tuning(platform, "BID_MAX_ABSOLUTE"))

            if cid not in bids_cache:
                try:
                    # ONE detail read gives status AND bids (docs/campaign-manager.md §8.3).
                    status_cache[cid], _, detail = await adapter.read_campaign(client, cid)
                    bids_cache[cid] = adapter.bids_from_detail(detail)
                    products_cache[cid] = await adapter.read_products(client, cid)
                    # +1 request per campaign (never per keyword) for the marketplace's own
                    # minimum bids. Read live, not from the nightly scrape: this decides
                    # what gets written to a real account (V7.6).
                    floors_cache[cid] = await adapter.read_bid_floors(client, cid, detail)
                except Exception as e:
                    status_cache[cid] = None
                    bids_cache[cid], products_cache[cid] = {}, []
                    floors_cache[cid] = {}
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  level="warning",
                                  msg=f"could not read the campaign from {mp} — {e}")

            # The floor is resolved ONCE, exactly like `ceiling` above, so every clamp,
            # decision and reset downstream takes a plain int: **`rule.min_bid` must not be
            # read directly below this line.** A rule may sit BELOW the marketplace's
            # minimum (it can move, and a rule written months ago cannot know today's), and
            # the engine's job is to write something Blinkit will accept — so the effective
            # floor is the higher of the two.
            # `read_bid_floors` keys its dict in OUR match-type vocabulary, so this is a
            # plain lookup. It used to call `adapter._api_match(...)` — the MP-agnostic
            # engine reaching into a private function only Blinkit has, which raised
            # AttributeError on every Zepto run.
            min_bid = effective_floor(rule.min_bid, floors_cache.get(cid, {}).get(
                (kw, (rule.match_type or "EXACT").upper())))
            if min_bid != rule.min_bid:
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="warning",
                              msg=(f"Blinkit's minimum for this keyword is ₹{min_bid}, above "
                                   f"the rule's ₹{min_bid} — bidding at ₹{min_bid}"))

            stores = rule_stores[rule.id]
            anchor = stores[0]
            live_cpm = bids_cache[cid].get(kw)
            logs.rule_context(
                run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                target=rule.target_position,
                current_cpm=live_cpm if live_cpm is not None else min_bid,
                min_bid=min_bid, max_bid=rule.max_bid,
                location_name=anchor.label or None, lat=anchor.lat, lon=anchor.lon,
                store_source=anchor.source, store_count=len(stores))

            # A stopped campaign isn't serving, so there is no position to chase — and
            # Blinkit rejects bid writes on one anyway. Skipping here saves the expensive
            # part of a bid run: a live consumer search per keyword. Matters most for a
            # campaign that `stop_after_window` keeps dark half the day.
            # A status we couldn't read (None) is NOT treated as stopped — a read blip
            # must not silently pause optimization.
            if status_cache[cid] is not None and status_cache[cid] != "running":
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             level="warning",
                             msg=f"campaign is {status_cache[cid]} on {mp} — not serving, "
                                 f"so there is nothing to optimise")
                skipped += 1
                continue

            # ── Window open: every window starts its bid at the floor (D-bid-open) ──
            #
            # The end-of-window reset is BEST EFFORT — the campaign may already be dark, or
            # Blinkit may refuse the write — so a window must not trust that it happened.
            # It re-establishes the floor itself. Without this, a reset that failed last
            # night is never recovered: `current_cpm` reads yesterday's `last_cpm` and steps
            # UP from it, so the bid ratchets across days until it pins at max_bid.
            #
            # "First fire of this window" = runtime `updated_at` older than the window's
            # start. No new column: `updated_at` is stamped every time a tick persists
            # runtime for this rule, and the skip paths below deliberately don't persist —
            # so a tick that couldn't do its job leaves the NEXT one still opening.
            #
            # The floor only counts as established once Blinkit READS BACK min_bid. The
            # budget engine restarts the campaign on the same boundary minute from a
            # parallel lane, and a RESTART re-submits the bids it read (restart.py) — so it
            # can land on top of our write. Re-checking each tick makes that self-correcting
            # (worst case: one lost tick) instead of silently losing the floor for a day.
            #
            # An all-day rule's midnight is NOT a window start (`_window_opened`): its bid
            # carries straight across, and it is floored only by the reset when its run of
            # days actually ends.
            opened = _window_opened(_rule_dict(rule),
                                    runtime.updated_at if runtime else None, now)
            if not opened and (live_cpm is None or int(live_cpm) != int(min_bid)):
                # Decision BEFORE the write, as everywhere else — a log that reports the
                # outcome before the reason that caused it is exactly what makes a run
                # hard to read.
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             msg="first run of today's window — resetting to the floor "
                                 "before optimising")
                if not await _still_active(rule.id):
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                 level="warning", msg=_PAUSED_MIDRUN)
                    skipped += 1
                    continue
                outcome: dict = {}
                ok, write_error = await _safe_apply_bid(
                    adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                    new_cpm=min_bid, current_cpm=live_cpm, min_bid=min_bid,
                    max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                    recent_writes=0, applied=patches, outcome=outcome,
                )
                applied += int(ok)
                skipped += int(not ok and write_error is None)
                errors += int(write_error is not None)
                was = f" (was ₹{live_cpm})" if live_cpm is not None else ""
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                             msg=(f"applied — bid is now ₹{min_bid}{was}" if ok else
                                  _plain(write_error, f"not applied — the change to "
                                                      f"₹{min_bid} could not be sent to {mp}")
                                  if write_error is not None else
                                  f"not applied — {mp} rejected the change to ₹{min_bid}"))
                open_reason = (f"the window opened, so the bid starts at its "
                               f"₹{min_bid} floor")
                action, success, reason = _write_verdict(ok, write_error, outcome, mp=mp,
                                                         landed="open", why=open_reason)
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     action, live_cpm, min_bid, reason, dry_run, success,
                                     rule_id=rule.id, target=rule.target_position))
                # No runtime row on purpose: `updated_at` must stay behind the window start
                # so the next tick re-checks that the floor actually stuck. Dry-run never
                # changes the live bid, though, so it would re-open every tick forever and
                # never exercise the optimizer — stamp it there and move on.
                if dry_run:
                    runtime_rows.append({"rule_id": rule.id})
                continue                       # no position scrape — the bid just moved

            # ── min_bid / max_bid are INVARIANTS, not just clamps on a computed value ──
            #
            # They used to be applied only to a bid the optimizer decided to change. When
            # the decision was "no change" — the common case once a target is held — an
            # edit that lowered `max_bid` below the live bid did nothing at all until the
            # next window opened, leaving the campaign a full day over its ceiling.
            # Enforced here every tick instead, so an edit lands on the next cycle.
            if live_cpm is not None:
                bounded = writes.clamp_bid(live_cpm, min_bid, ceiling)
                if int(bounded) != int(live_cpm):
                    # Not rate-limited: this is a correctness write, not optimization, and
                    # it cannot run away — one write puts the bid back inside the bounds.
                    why = ("above the" if int(live_cpm) > int(ceiling) else "below the")
                    limit = ceiling if int(live_cpm) > int(ceiling) else min_bid
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                 msg=f"live bid ₹{live_cpm} is {why} ₹{limit} limit — "
                                     f"forcing it back into range")
                    if not await _still_active(rule.id):
                        logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                     level="warning", msg=_PAUSED_MIDRUN)
                        skipped += 1
                        continue
                    outcome = {}
                    ok, write_error = await _safe_apply_bid(
                        adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                        new_cpm=bounded, current_cpm=live_cpm, min_bid=min_bid,
                        max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                        recent_writes=0, applied=patches, outcome=outcome,
                    )
                    applied += int(ok)
                    skipped += int(not ok and write_error is None)
                    errors += int(write_error is not None)
                    logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                                 msg=(f"applied — bid is now ₹{bounded}" if ok else
                                      _plain(write_error, f"not applied — the change to "
                                                          f"₹{bounded} could not be sent to {mp}")
                                      if write_error is not None else
                                      f"not applied — {mp} rejected the change to ₹{bounded}"))
                    # Present tense: this sentence also heads a row whose write did NOT land,
                    # and "was brought back" would then describe something that never happened.
                    bounds_reason = (f"the live bid of ₹{live_cpm} is {why} ₹{limit} limit, "
                                     f"so it goes back to ₹{bounded}")
                    action, success, reason = _write_verdict(ok, write_error, outcome, mp=mp,
                                                             landed="bounds", why=bounds_reason)
                    log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                         action, live_cpm, bounded, reason, dry_run, success,
                                         rule_id=rule.id, target=rule.target_position))
                    if ok and not dry_run:
                        runtime_rows.append({"rule_id": rule.id, "last_cpm": int(bounded)})
                    continue               # no position scrape — the bid just moved

            # Handed to `locate_position` as-is. This used to unpack `name`/`pid` HERE,
            # which meant the MP-agnostic engine knew Blinkit's field names — and on any
            # other marketplace produced two empty lists, so nothing matched and the run
            # reported "product not in results" forever, silently. The adapter owns the
            # shape now; `read_products` returns `{pid, name}` on both marketplaces.
            products = products_cache[cid]

            # On the tick that CONFIRMS the floor, Blinkit reads back min_bid but runtime
            # still holds yesterday's `last_cpm` — stepping from that would undo the open.
            # `open_stamp` also writes the corrected `last_cpm` below, so the tick after
            # this one (which sees `opened`) reads the floor, not the stale value.
            open_stamp = not opened
            current_cpm = (int(min_bid) if open_stamp else
                           int((runtime.last_cpm if runtime else None)
                               or bids_cache[cid].get(kw) or min_bid))

            # ── Read every measurement store; act on the worst one that counts ──
            #
            # The goal is the target position at EVERY store where the campaign can be sold,
            # which is the same as the worst such store being at target — so everything below
            # is unchanged; it is simply handed the binding store's position
            # (campaign_manager/coverage.py). A store where stock CONFIRMS the campaign can't
            # sell is not read: we could not have won there, and counting it as a miss is how
            # a stock-out used to turn into a raise.
            campaign_pids = {str(p.get("pid")) for p in products if p.get("pid")}
            # A store not showing our ad even at the ceiling, check after check, can't be won at
            # this ceiling — chasing it would hold every other store at max_bid too.
            window_open_at = _window_start(_rule_dict(rule), now)
            give_up_ticks = config.BID_GIVE_UP_TICKS
            given_up = {
                s.merchant_id: (f"not showing even at the ₹{ceiling} ceiling for "
                                f"{give_up_ticks} checks — left out until this window ends")
                for s in stores
                if s.merchant_id and coverage.gave_up(
                    store_history.get((rule.id, s.merchant_id), []),
                    window_start=window_open_at, ceiling=ceiling, ticks=give_up_ticks)
            }
            readings = await _read_stores(
                adapter, pos_session, positions_cache, stores, kw,
                products=products, campaign_pids=campaign_pids, stock_by_store=stock_by_store,
                campaign_id=cid, match_type=rule.match_type, brand_name=rule.brand_name,
                given_up=given_up)
            outcome = coverage.aggregate(readings)
            for reading in outcome.readings:
                logs.store_reading(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                   reading=reading, many=len(stores) > 1)
                # A store that keeps giving nothing usable drops out of every decision quietly
                # — say so once it has happened twice in a row.
                streak = coverage.unusable_streak(
                    store_history.get((rule.id, reading.store.merchant_id), []),
                    reading.verdict) if reading.store.merchant_id else 0
                if streak >= config.STORE_PROBLEM_WARN_TICKS:
                    name = reading.store.label or reading.store.merchant_id
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  level="warning",
                                  msg=f"{name} has given no usable reading for {streak} checks "
                                      f"in a row — decisions are running without it")
            store_rows.extend(_store_rows(tenant_id, platform, run_id, rule, outcome.readings,
                                          outcome, current_cpm, dry_run))

            if outcome.kind == "no_stock":
                why = ("none of this campaign's products are available at the stores we check "
                       "— a stock problem, not a bidding one, so the bid is left alone")
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             level="warning", msg=why)
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "skip", current_cpm, current_cpm, why, dry_run, True,
                                     rule_id=rule.id, target=rule.target_position))
                continue
            if outcome.kind == "unwinnable":
                why = (f"every store we count has stayed out of reach at the ₹{ceiling} ceiling "
                       f"— the bid stays where it is until this window ends")
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             level="warning", msg=why)
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "skip", current_cpm, current_cpm, why, dry_run, True,
                                     rule_id=rule.id, target=rule.target_position))
                continue
            if outcome.kind == "error":
                err = outcome.binding.detail if outcome.binding else "no store could be read"
                # A failed search is a fault worth an ERROR; a reading we merely couldn't trust
                # (no products, a cut-short page) is not — it must not page anyone.
                failed = bool(outcome.binding and outcome.binding.verdict == coverage.ERROR)
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="error" if failed else "warning",
                              msg=f"no store gave a usable reading — {err}. Bid left unchanged")
                errors += int(failed)
                skipped += int(not failed)
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "error" if failed else "skip", current_cpm, current_cpm,
                                     _plain(err, "no store gave a usable search reading, so "
                                                 "the bid was left unchanged"), dry_run,
                                     not failed,
                                     rule_id=rule.id, target=rule.target_position))
                continue

            binding = outcome.binding
            position, source = binding.position, binding.detail
            # Which store set the decision — said only when there was more than one to choose.
            at_store = (f" at {binding.store.label or binding.store.merchant_id}"
                        if outcome.counted > 1 else "")
            # ── Not in a sponsored slot ──────────────────────────────────────
            #
            # Being absent is the WORST outcome, not a neutral one: the whole point of a
            # sponsored slot is to appear. Skipping would mean a keyword outbid off the page
            # can never climb back. So an opted-in marketplace treats absence as "worse than
            # anything we could see" and raises; the reading already carries the synthetic
            # position `len(results) + 1` (coverage.absent_position), which keeps escalation
            # honest — still absent next tick reads as "not improved".
            #
            # ⚠️ OPT-IN PER MARKETPLACE (`getattr(..., False)`), so a new marketplace never
            # starts bidding against a signal nobody has verified it can read. Both live
            # marketplaces opt in: Zepto's marker is `tagsV2` + `uclId`, Blinkit's
            # `ads_campaign_id`.
            #
            # A store only gets here if it COUNTS — stock confirmed or unknown. A confirmed
            # stock-out never reaches this raise.
            absent = binding.verdict == coverage.ABSENT
            if absent and not getattr(adapter, "RAISE_WHEN_ABSENT", False):
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="warning",
                              msg=f"no sponsored slot for us{at_store} — {source}, leaving the "
                                  f"bid unchanged")
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "skip", current_cpm, current_cpm, source, dry_run, True,
                                     rule_id=rule.id, target=rule.target_position))
                continue
            if absent:
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="warning",
                              msg=f"no sponsored slot for us{at_store} — bidding up to get onto "
                                  f"the page")
            else:
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              msg=(f"worst of {outcome.counted} stores: position "
                                   f"{position:g}{at_store}" if outcome.counted > 1 else
                                   f"our ad is at position {position:g}"),
                              position=position)

            last_pos = runtime.last_position if runtime else None
            mins = _minutes_since(runtime.last_bid_updated_at if runtime else None, now)
            # Drift state. `open_stamp` means the window just opened, which clears all of
            # it — yesterday's holding price says nothing about today, a pause must not
            # outlive the window that caused it, and a target relaxed against yesterday's
            # competition must be re-earned so every day retries the REAL target.
            holding_cpm = None if open_stamp else (runtime.last_holding_cpm if runtime else None)
            paused_until = None if open_stamp else (runtime.drift_paused_until if runtime else None)
            drift_paused = bool(paused_until and paused_until > now)

            # Raise escalation. "Improved" = the position got BETTER since the last tick,
            # i.e. the last raise crossed a riser — so go back to the base step rather than
            # keep accelerating into the next one. A window that just opened starts fresh.
            improved = last_pos is not None and position < last_pos
            step_now = next_raise_step(
                current_cpm, None if open_stamp else (runtime.raise_step if runtime else None),
                improved, min_step=config.bid_tuning(platform, "BID_RAISE_MIN_STEP"),
                pct=config.bid_tuning(platform, "BID_RAISE_PCT"),
                escalate=config.bid_tuning(platform, "BID_RAISE_ESCALATE"),
            )

            # ── Unreachable target: chase what the ceiling can actually buy ──
            eff = None if open_stamp else stored_effective_target(
                rule.target_position, ceiling,
                runtime.effective_target if runtime else None,
                runtime.effective_at_max_bid if runtime else None,
            )
            # NEVER relax against a synthetic position. Relaxing would set the working
            # target to `len(results) + 1`, at which point the synthetic position equals
            # the target, `compute_bid` reads it as HOLDING, and drift-down starts
            # trimming the bid — undoing the very climb that is trying to get us onto the
            # page. Relaxation is for "the ceiling cannot buy position 3"; it means
            # nothing when we never saw a slot at all.
            relaxed_now = (not absent) and eff is None and should_relax_target(
                position, rule.target_position, current_cpm, ceiling, last_pos)
            if relaxed_now:
                eff = int(position)
            target = eff if eff is not None else rule.target_position
            if relaxed_now:
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             level="warning",
                             msg=f"position {rule.target_position} unreachable at the "
                                 f"₹{ceiling} ceiling — settling for position {target} and "
                                 f"optimising cost for that")
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "relax", current_cpm, current_cpm,
                                     f"target position {rule.target_position} unreachable at "
                                     f"max ₹{ceiling} — now holding position {target}",
                                     dry_run, True,
                                     rule_id=rule.id, position=position, target=target))

            new_cpm, reason = compute_bid(
                position, target, current_cpm, min_bid, ceiling,
                last_pos, mins, last_holding_cpm=holding_cpm, drift_paused=drift_paused,
                drift_pct=drift_pct, drift_min_step=config.bid_tuning(platform, "BID_DRIFT_MIN_STEP"),
                raise_step=step_now,
                position_text=(f"our ad is not in a sponsored slot{at_store}" if absent else None),
            )
            if outcome.counted > 1 and not absent:
                # Name the store that set it, so History says WHICH store is holding a bid up.
                reason = (f"{reason} — worst of {outcome.counted} stores is "
                          f"{binding.store.label or binding.store.merchant_id}")
            recovering = (drift_pct > 0
                          and is_recovery(position, target, current_cpm, holding_cpm))
            # `reason` is already a full sentence. The escalation clause is added here
            # because only the orchestration knows the step grew — compute_bid is handed
            # the step, not the history behind it.
            escalated = (new_cpm is not None and position > target and not improved
                         and (runtime.raise_step if runtime else None)
                         and step_now > int(runtime.raise_step))
            msg = reason + ("; the last raise did not move us, so the step grew"
                            if escalated else "")
            logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, msg=msg,
                         level="info" if new_cpm is not None else "info")

            # The snap-back price is refreshed on EVERY holding tick, not just the first.
            # Stale, it would send us back to a price that worked an hour ago — the point
            # is to track the market, not to fight it.
            rt: dict = {"rule_id": rule.id, "last_position": position}
            if open_stamp:                         # observed truth: Blinkit reads back the floor
                rt["last_cpm"] = int(min_bid)
                rt["last_holding_cpm"] = None
                rt["drift_paused_until"] = None
                rt["effective_target"] = None
                rt["effective_at_max_bid"] = None
                rt["raise_step"] = None
            # Only a real raise carries the escalation forward. A recovery snap-back is a
            # precise return to a known price, not a climb, and holding ticks aren't
            # climbing at all — letting either escalate would have the next genuine raise
            # start from an inflated step.
            if new_cpm is not None and position > target and not recovering:
                rt["raise_step"] = int(step_now)
            elif improved or position <= target:
                rt["raise_step"] = None            # crossed a riser → start again at base
            if relaxed_now:                        # pin the ceiling it was concluded at
                rt["effective_target"] = int(target)
                rt["effective_at_max_bid"] = int(ceiling)
            if position <= target:
                rt["last_holding_cpm"] = int(current_cpm)
            elif recovering:
                # Our own drift overshot. Stop shaving for a while so we don't walk into
                # the same wall every tick — but RAISES stay ungated, so a competitor
                # outbidding us during the pause is still answered immediately.
                rt["drift_paused_until"] = now + timedelta(minutes=config.bid_tuning(platform, "BID_DRIFT_PAUSE_MINUTES"))

            # No change (target held, HOLD, awaiting confirmation, or drift paused).
            #
            # These USED to be dropped, on the grounds that a row every 15 minutes would
            # bury the real changes in History. That was solved in the wrong place: the
            # noise belonged in the default VIEW, not in what we are willing to remember.
            # A per-automation drill-down needs exactly these ticks — "why did my bid not
            # move for six hours" is answered by them and by nothing else — so they are
            # recorded, and `/history` filters them out of the default view instead.
            #
            # `hold` when we are off target and waiting for the marketplace to reflect the
            # last change; `no-op` when there was simply nothing to do.
            if new_cpm is None:
                skipped += 1
                runtime_rows.append(rt)
                log_rows.append(_row(
                    tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                    "hold" if position > target else "no-op",
                    current_cpm, current_cpm, reason, dry_run, True,
                    rule_id=rule.id, position=None if absent else position, target=target))
                continue

            # Per-KEYWORD rate limit: the guard exists to catch a runaway loop, and a
            # per-campaign count would make a multi-keyword campaign throttle keywords
            # that are behaving. Drift writes up to 4×/hour/keyword against a cap of 12.
            recent = await repo.recent_write_count(
                tenant_id, cid, window_minutes=config.RATE_WINDOW_MINUTES,
                kind="bid", keyword=kw,
            )
            if not await _still_active(rule.id):
                # No runtime row either: `write_bid_runtime` stamps `updated_at`, and a
                # paused rule's `updated_at` is exactly what Resume reads to decide whether
                # the window still counts as opened.
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             level="warning", msg=_PAUSED_MIDRUN)
                skipped += 1
                continue
            outcome: dict = {}
            ok, write_error = await _safe_apply_bid(
                adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                new_cpm=new_cpm, current_cpm=current_cpm, min_bid=min_bid,
                max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                recent_writes=recent, applied=patches, outcome=outcome,
            )
            applied += int(ok)
            skipped += int(not ok and write_error is None)
            errors += int(write_error is not None)
            final = int(writes.clamp_bid(new_cpm, min_bid, ceiling))
            if ok:
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=True,
                             msg=(f"would set bid to ₹{final} — not sent" if dry_run
                                  else f"applied — bid is now ₹{final}"))
            elif write_error is not None:
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=False,
                             msg=_plain(write_error,
                                        f"not applied — the change to ₹{final} could not "
                                        f"be sent to {mp}"))
            else:
                # The choke point already knows why — rate limit, the marketplace's own
                # bounds, its refusal message, "already ₹X" — so say that rather than guess.
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=False,
                             msg=f"not applied — {outcome.get('reason') or f'{mp} rejected the change to ₹{final}'}")

            if ok and not dry_run:                 # only a REAL write changes last_cpm/timestamp
                rt["last_cpm"] = final
                rt["last_bid_updated_at"] = now.isoformat()
            runtime_rows.append(rt)
            drifted = drift_pct > 0 and position <= target
            action, success, reason = _write_verdict(
                ok, write_error, outcome, mp=mp, why=reason,
                landed="recover" if recovering else ("drift" if drifted else "apply"))
            log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                 action, current_cpm, new_cpm, reason, dry_run, success,
                                 # The placeholder for "not on the page" is not a position.
                                 rule_id=rule.id, position=None if absent else position,
                                 target=target))
    except writes.SessionExpired as e:
        # The client already tried to re-authenticate once and could not. Continuing would
        # fire the same doomed call at every remaining keyword while logging that the
        # MARKETPLACE rejected the bids — which is the misreporting this whole path exists
        # to stop. Abort, and say what actually happened.
        logs.session_expired(run_id, dry_run=dry_run)
        logs.note(run_id, f"stopped after {processed} of {len(active)} automations — {e}",
                  dry_run=dry_run)
        errors += 1
    finally:
        await adapter.close_position_session(pos_session)
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    await repo.record_applied(tenant_id, platform, patches)
    await repo.write_store_reads(store_rows)
    logs.blank(run_id, dry_run=dry_run)
    logs.run_summary(
        run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
        processed=processed, applied=applied, skipped=skipped, errors=errors,
        seconds=(now_ist() - started).total_seconds(),
        note=(f"{len(positions_cache)} position searches"
              + (f" + {stock_searches} stock searches" if stock_searches else "")
              + f" for {processed} keywords"))
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


def _saved_coords(active, city_stores: dict) -> set:
    """Saved coordinates of rules that will measure at their OWN store — pinned, or in a city
    with nothing frozen — whose catalog store id is needed to look their stock up."""
    return {(r.lat, r.lon) for r, _ in active
            if r.lat is not None and r.lon is not None
            and not city_stores.get(getattr(r, "city_id", None))}


async def _read_stores(adapter, session, positions_cache: dict, stores, keyword: str, *,
                       products, campaign_pids, stock_by_store: dict, campaign_id, match_type,
                       brand_name, given_up: dict | None = None) -> list:
    """Read one keyword at each measurement store → `[coverage.Reading]`, in the stores' order.

    A store whose stock CONFIRMS the campaign can't sell there, or one given up at the ceiling
    for this window (`given_up`: merchant_id → why), is not searched at all. Every other store
    is — once per (keyword, store) for the whole run, shared across rules through
    `positions_cache`: several campaigns routinely target the same keyword at the same store
    (on 2026-08-22 thirteen rules resolved to four pairs, and the duplicate searches got
    Blinkit timing out). A failed fetch is cached as the failure too; re-scraping a keyword
    that just timed out only feeds the throttling that caused it.

    A search that answered but proves nothing becomes UNTRUSTED rather than "absent": no
    products at all, a page cut short with our ad unseen, or a campaign whose products we
    couldn't read. Any of those counted as absent would raise the bid on no evidence.

    Never raises: a store that can't be read becomes an ERROR reading, and the decision is
    left to the stores that could."""
    given_up = given_up or {}
    # Without product ids or a brand to match on, "our ad isn't there" is unknowable.
    identifiable = bool(products) or bool(brand_name)
    readings = []
    for store in stores:
        known = stock_by_store.get(store.merchant_id) if store.merchant_id else None
        elig = coverage.eligibility(campaign_pids, known)
        if not coverage.counts(elig):
            readings.append(coverage.Reading(
                store, elig, coverage.SKIPPED,
                detail=("every product of this campaign is sold out here"
                        if elig == coverage.OUT_OF_STOCK
                        else "none of this campaign's products are sold here")))
            continue
        if store.merchant_id and store.merchant_id in given_up:
            readings.append(coverage.Reading(store, elig, coverage.GAVE_UP,
                                             detail=given_up[store.merchant_id]))
            continue
        key = (keyword, float(store.lat), float(store.lon))
        if key not in positions_cache:
            try:
                positions_cache[key] = (await adapter.fetch_positions(
                    session, keyword, store.lat, store.lon), None)
            except Exception as e:
                positions_cache[key] = ([], e)
        results, fetch_error = positions_cache[key]
        if fetch_error is not None:
            readings.append(coverage.Reading(
                store, elig, coverage.ERROR,
                detail=str(fetch_error) or type(fetch_error).__name__))
            continue
        if not results:
            # Used to become "position 1" — the empty page read as target held, and the bid
            # was trimmed on nothing.
            readings.append(coverage.Reading(
                store, elig, coverage.UNTRUSTED,
                detail="the search came back with no products at all, so it says nothing "
                       "about our ad"))
            continue
        try:
            # `campaign_id` and `match_type` matter where results say which campaign won a
            # slot (Zepto); Blinkit ignores them. Passed always, so no per-marketplace branch.
            position, source = adapter.locate_position(
                results, keyword, store.lat, store.lon, products=products,
                campaign_id=campaign_id, match_type=match_type, brand_name=brand_name)
        except Exception as e:
            readings.append(coverage.Reading(store, elig, coverage.ERROR,
                                             detail=str(e) or type(e).__name__))
            continue
        if position is None and getattr(results, "truncated", False):
            readings.append(coverage.Reading(
                store, elig, coverage.UNTRUSTED, results=len(results),
                detail="the search was cut short after its first page, so not seeing our ad "
                       "proves nothing"))
        elif position is None and not identifiable:
            readings.append(coverage.Reading(
                store, elig, coverage.UNTRUSTED, results=len(results),
                detail="this campaign's products couldn't be read, so we can't tell whether "
                       "our ad is on the page"))
        elif position is None:
            readings.append(coverage.Reading(store, elig, coverage.ABSENT,
                                             coverage.absent_position(len(results)),
                                             len(results), source))
        else:
            readings.append(coverage.Reading(store, elig, coverage.SPONSORED, float(position),
                                             len(results), source))
    return readings


def _store_rows(tenant_id, platform, run_id, rule, readings, outcome, bid, dry_run) -> list[dict]:
    """`cm_bid_store_reads` rows for one rule's tick. Stamped here, like `_row`: the run is
    persisted in one batch at the end, and each row should say when its store was read."""
    now = now_ist()
    return [{
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "rule_id": rule.id,
        "campaign_id": rule.campaign_id, "keyword": rule.keyword,
        "city_id": getattr(rule, "city_id", None),
        "merchant_id": r.store.merchant_id or "", "store_label": r.store.label or "",
        "rank": int(getattr(r.store, "rank", 1) or 1),
        "bid": int(bid) if bid is not None else None,
        "eligibility": r.eligibility, "verdict": r.verdict,
        # Only a real sponsored slot is a position; ABSENT's is a placeholder for the decision.
        "position": r.position if r.verdict == coverage.SPONSORED else None,
        "binding": outcome.binding is r,
        "detail": " ".join((r.detail or "").split())[:500] or None,
        "dry_run": dry_run, "observed_at": now,
    } for r in readings]


@dataclass
class _Target:
    """One keyword to floor. Field names match what `_record_run_blocked` and `_row` read
    off a rule, so a target can stand in for one — which is the point: an on-demand reset
    may outlive the rule that asked for it (Delete + reset), so it cannot hold a reference
    to one."""
    campaign_id: int
    keyword: str
    min_bid: int                            # the requested floor, before the marketplace's
    campaign_name: str | None = None
    match_type: str = "EXACT"
    max_bid: int | None = None
    id: str | None = None                   # rule id, for History; None once the rule is gone
    target_position: int | None = None


def _reset_grace_seconds() -> float:
    """How far back the reset looks for a window that was open: the scheduler's misfire
    grace — a fire that late still counts as on time — PLUS the look-ahead, because the
    look-back starts from `now + RESET_LOOKAHEAD_MINUTES`, not from `now`."""
    return settings.SCHEDULER_MISFIRE_GRACE_SECONDS + RESET_LOOKAHEAD_MINUTES * 60


def _reset_selection(rules, at: datetime, grace_seconds: float) -> list:
    """The rules an end-of-window reset floors at `at`: those whose window JUST closed.

    ⚠️ The edge, not the level. This used to take every rule NOT in window — and a rule that
    has ENDED is never in window, so every reset fire of ANY automation re-floored every ended
    rule the tenant had, indefinitely, along with every rule that had not started yet (found
    2026-09-10). Now only a window that closed within the grace counts. A close missed
    entirely — the runner was down — is not recovered here: a recurring rule's next window
    opens at its floor anyway, but a one-time rule's last window stays where it was left.

    A keyword another rule still has open at `at` is left to that rule.
    """
    live_keys = {(r.campaign_id, r.keyword) for r in rules if _in_window(_rule_dict(r), at)}
    return [r for r in rules
            if window.just_closed(window.from_bid(r), at, grace_seconds)
            and (r.campaign_id, r.keyword) not in live_keys]


def _settle_selection(rules, now: datetime) -> list:
    """Active rules that ENDED without their final reset landing — the settle-once safety net
    (campaign_manager/lifecycle.py). Their end-of-window reset never landed (the runner was
    down, or the write failed), so this floors them once more: within SETTLE_MAX_AGE_HOURS of
    the close, and at most SETTLE_MAX_ATTEMPTS times. A keyword another rule has open is left
    to that rule."""
    live_keys = {(r.campaign_id, r.keyword) for r in rules if _in_window(_rule_dict(r), now)}
    return [r for r in rules
            if (r.campaign_id, r.keyword) not in live_keys
            and lifecycle.bid_rule_needs_settle(r, now)]


# What the client reads in History for a keyword floored by the settle pass rather than at
# its own close.
_SETTLE_PHRASE = "this automation ended and its final reset never landed"


async def _reset_run(tenant_id: uuid.UUID, platform: str, pairs, now: datetime,
                     run_id: str, dry_run: bool) -> dict:
    """End-of-window reset: set each just-closed keyword's bid back to its `min_bid`, so a
    bid the optimizer pushed up doesn't keep spending high after the window. No position
    scrape (cheap). Skips a keyword still covered by an in-window rule, and any bid already
    at/below its floor. Only a real (live) write updates runtime `last_cpm`.

    The same run settles rules that ended without their final reset landing
    (`_settle_selection`). Wherever a floor is an automation's LAST teardown, landing it
    latches `settled_at` — see `_floor_bids`.

    Selection only (`_reset_selection`, `_settle_selection`) — the writing is `_floor_bids`,
    shared with the on-demand reset."""
    # Windows are evaluated slightly AHEAD of now, because the reconciler fires this run a
    # minute BEFORE the window's stop time — so the bid drops back before the budget engine
    # (a parallel lane) can stop the campaign, after which Blinkit refuses bid writes. At
    # the nominal stop time the look-ahead changes nothing, so a reset fired exactly on the
    # boundary behaves as it always did.
    at = now + timedelta(minutes=RESET_LOOKAHEAD_MINUTES)
    rules = [r for r, _ in pairs]
    closing = _reset_selection(rules, at, _reset_grace_seconds())
    taken = {r.id for r in closing}
    settling = [r for r in _settle_selection(rules, now) if r.id not in taken]
    # Which of these floors is its automation's FINAL teardown — and the close it covers.
    settle_closes = {r.id: close for r in closing + settling
                     if (close := lifecycle.bid_rule_close(r)) is not None
                     and close != datetime.min and close <= at}
    return await _floor_bids(tenant_id, platform, [_target_of(r) for r in closing + settling],
                             run_id=run_id, dry_run=dry_run,
                             phrase="the window closed",
                             empty_note="No keyword windows are closing right now",
                             settle_closes=settle_closes,
                             phrases={r.id: _SETTLE_PHRASE for r in settling})


def _target_of(rule) -> _Target:
    return _Target(campaign_id=rule.campaign_id, keyword=rule.keyword,
                   min_bid=rule.min_bid, campaign_name=rule.campaign_name,
                   match_type=rule.match_type or "EXACT", max_bid=rule.max_bid,
                   id=rule.id, target_position=rule.target_position)


async def set_bid(tenant_id: uuid.UUID, *, campaign_id: int, keyword: str, cpm: int,
                  match_type: str = "EXACT", platform: str = "blinkit",
                  dry_run: bool | None = None, run_id: str | None = None) -> dict:
    """Write ONE keyword's bid, now. The mechanism behind Reset (and Delete + reset).

    Deliberately takes plain values rather than a rule id: Delete + reset removes the rule
    before this job runs, so anything that had to look one up would have nothing to find.
    A rule that IS still there is used only to enrich the History row (name, target) and to
    honour its ceiling.

    Refuses to touch a keyword that an ACTIVE, in-window rule is currently bidding on —
    flooring a bid another automation is defending would just start a fight it wins 15
    minutes later.
    """
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = run_id or logs.new_run_id()
    logs.run_start(run_id, "set_bid", tenant_id, dry_run=dry_run, platform=platform,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    now = now_ist()
    mine = None
    # Any state: a paused rule for this keyword still names the History row. Whether to refuse
    # is decided below, and only an active, in-window rule refuses.
    for r, _rt in await repo.get_bid_rules(tenant_id, platform, state=repo.ANY_STATE,
                                           calendar=repo.ANY_CALENDAR):
        if r.campaign_id != campaign_id or r.keyword != keyword:
            continue
        if r.state == "active" and _in_window(_rule_dict(r), now):
            logs.note(run_id, f'"{keyword}" is being bid on by an active automation right '
                              f"now — leaving it alone", dry_run=dry_run, level="warning")
            logs.run_summary(run_id, "set_bid", dry_run=dry_run, unit="keywords",
                             processed=1, applied=0, skipped=1, errors=0)
            return {"processed": 1, "applied": 0, "skipped": 1, "errors": 0}
        mine = mine or r

    target = _Target(campaign_id=campaign_id, keyword=keyword, min_bid=int(cpm),
                     campaign_name=mine.campaign_name if mine else
                     await _campaign_name(tenant_id, campaign_id, platform),
                     match_type=(mine.match_type if mine else match_type) or "EXACT",
                     max_bid=mine.max_bid if mine else None,
                     id=mine.id if mine else None,
                     target_position=mine.target_position if mine else None)
    return await _floor_bids(tenant_id, platform, [target], run_id=run_id, dry_run=dry_run,
                             phrase="this automation was reset", empty_note="")


async def _campaign_name(tenant_id: uuid.UUID, campaign_id: int, platform: str) -> str | None:
    """The campaign's name from the catalogue, for a History row whose rule is already gone.
    Best-effort — a nameless row is worse than one from a stale scrape, not worse than one
    that failed to render."""
    try:
        campaign, _ = await repo.get_bid_context(tenant_id, campaign_id, platform)
        return getattr(campaign, "name", None)
    except Exception:
        return None


async def _floor_bids(tenant_id: uuid.UUID, platform: str, to_reset: list[_Target], *,
                      run_id: str, dry_run: bool, phrase: str, empty_note: str,
                      settle_closes: dict | None = None, phrases: dict | None = None) -> dict:
    """Write each target's bid down to its floor. Shared by the end-of-window reset and the
    on-demand one — one writer, two selectors, so a fix to either reaches both.

    `phrase` is the client-facing reason ("the window closed" / "this automation was
    reset"), overridable per rule id by `phrases`; everything else about the write is
    identical. `settle_closes` names the rule ids whose floor is their automation's FINAL
    teardown, with the close it covers: a floor that lands (or finds the bid already there)
    latches `settled_at`, one that fails counts an attempt."""
    if not to_reset:
        if empty_note:
            logs.note(run_id, empty_note, dry_run=dry_run)
        logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    mp = platform.title()
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError as e:
        logs.session_expired(run_id, dry_run=dry_run)
        await _record_run_blocked(
            tenant_id, platform, run_id, to_reset,
            _plain(e, f"could not sign in to {mp}, so the bid was not reset to its floor — "
                      f"it stays where the automation left it"), dry_run)
        logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run, platform=platform)

    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            await _record_run_blocked(
                tenant_id, platform, run_id, to_reset,
                _plain(e, "the ad account could not be confirmed, so the bid was not "
                          "reset to its floor"), dry_run)
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    logs.note(run_id, f"{len(to_reset)} keyword{'' if len(to_reset) == 1 else 's'} to reset "
                      f"to the floor — {phrase}", dry_run=dry_run)

    processed = applied = skipped = errors = 0
    runtime_rows: list[dict] = []
    log_rows: list[dict] = []
    # Catalogue write-back, flushed once with the rows above (campaign_manager/writes.py).
    patches: list[dict] = []
    landed_ids: list[str] = []                 # floors that landed or were already in place
    failed_ids: list[str] = []
    bids_cache: dict[int, dict] = {}
    status_cache: dict[int, str | None] = {}
    floors_cache: dict[int, dict] = {}
    try:
        for r in to_reset:
            processed += 1
            cid, kw = r.campaign_id, r.keyword
            say = (phrases or {}).get(r.id) or phrase
            logs.blank(run_id, dry_run=dry_run)
            logs.rule_header(run_id, dry_run=dry_run, index=processed, total=len(to_reset),
                             campaign_name=r.campaign_name, campaign_id=cid)
            if cid not in bids_cache:
                try:
                    status_cache[cid], _, detail = await adapter.read_campaign(client, cid)
                    bids_cache[cid] = adapter.bids_from_detail(detail)
                    floors_cache[cid] = await adapter.read_bid_floors(client, cid, detail)
                except Exception as e:
                    status_cache[cid], bids_cache[cid] = None, {}
                    floors_cache[cid] = {}
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  level="warning",
                                  msg=f"could not read the current bid from {mp} — {e}")

            # The reset writes the bid back DOWN to the floor, so it has to respect the
            # marketplace's own minimum too — writing below it would be refused, leaving
            # the keyword parked at its high in-window bid overnight (V7.6).
            min_bid = effective_floor(r.min_bid, floors_cache.get(cid, {}).get(
                (kw, (r.match_type or "EXACT").upper())))
            status = status_cache[cid]
            # An UNREADABLE bid is not a bid at the floor. This used to fall back to
            # `min_bid`, which the check below then read as "already there, nothing to do"
            # and skipped in silence — no decision line, no History row. It was the reset's
            # single most likely way to do nothing at all while looking healthy. `None` now
            # means "we don't know", and we write anyway.
            current = bids_cache[cid].get(kw)
            shown = f"₹{current}" if current is not None else "unknown"
            logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                          msg=f'keyword "{kw}" · {say} · current bid {shown}')

            if current is not None and int(current) <= int(min_bid):
                # Genuinely already at the floor. Skipped rather than written because a
                # keyword-bid write is a FULL campaign PUT (client.update_keyword_bids
                # re-submits budget, dates and pids too), and the budget engine writes the
                # same campaign from a parallel lane around this minute — so a PUT that
                # changes nothing is a free chance to clobber a budget. Logged either way.
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             msg=f"already at the ₹{min_bid} floor — nothing to change")
                skipped += 1
                landed_ids.append(r.id)
                log_rows.append(_row(tenant_id, platform, run_id, cid, r.campaign_name, kw,
                                     "skip", current, min_bid,
                                     f"{say} and the bid is already at its "
                                     f"₹{current} floor, so nothing to change", dry_run, True,
                                     rule_id=r.id, target=r.target_position))
                continue

            # No status gate. `held` (ON_HOLD) is a RUNNING campaign whose budget ran out —
            # Blinkit takes an UPDATE on it, and budget.py already treats it as writable.
            # A genuinely stopped campaign gets the write refused, and that refusal is the
            # useful outcome: a failed History row you can see, not an invisible skip.
            # A rejected write must not abort the whole reset either — one dark campaign
            # shouldn't cost every other keyword its de-escalation.
            logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                         msg=f"{say} — resetting to the ₹{min_bid} floor so it does not "
                             f"keep spending high (campaign is "
                             f"{status or 'in an unknown state'})")
            outcome: dict = {}
            try:
                ok = await writes.apply_bid(
                    adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                    new_cpm=min_bid, current_cpm=current, min_bid=min_bid,
                    max_bid=resolve_ceiling(
                        r.max_bid, config.bid_tuning(platform, "BID_MAX_ABSOLUTE")),
                    match_type=r.match_type, dry_run=dry_run, recent_writes=0,
                    applied=patches, outcome=outcome,
                )
                err = None
            except Exception as e:
                ok, err = False, str(e)
            applied += int(ok)
            errors += int(not ok)
            (landed_ids if ok else failed_ids).append(r.id)
            stuck = _stranded(mp, status, current) if not ok else ""
            logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                         msg=(f"would set bid to ₹{min_bid} — not sent" if (ok and dry_run)
                              else f"applied — bid is now ₹{min_bid}" if ok
                              else f"not applied — {stuck or f'{mp} rejected the reset'}"
                                   + (f" ({err})" if err else "")))
            # `r.id` is None once the rule is gone (Delete + reset), and a runtime row
            # cannot exist without one.
            if ok and not dry_run and r.id:
                runtime_rows.append({"rule_id": r.id, "last_cpm": int(min_bid)})
            done = f"{say}, so the bid goes back to its ₹{min_bid} floor"
            # A FAILED reset used to file `done` — "the bid goes back to its ₹200 floor" —
            # which is a description of what did not happen. The row was marked
            # unsuccessful, but the sentence beside it said the opposite, and that sentence
            # is what a client reads. When we know why it did not land, say that instead:
            # the exception when the write raised, the guardrail's or marketplace's refusal
            # (`outcome`) when it did not.
            if ok:
                reason = done
            elif stuck:
                reason = stuck
            else:
                reason = _plain(err or outcome.get("reason") or "",
                                f"{mp} would not accept the reset to ₹{min_bid}, so "
                                f"the bid did not change")
            log_rows.append(_row(tenant_id, platform, run_id, cid, r.campaign_name, kw,
                                 "reset", current, min_bid, reason, dry_run, ok,
                                 rule_id=r.id, target=r.target_position))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    # A floor that was its automation's FINAL teardown latches it; one that failed counts an
    # attempt. Live runs only — a dry run wrote nothing, so nothing has landed. Both are
    # recorded in History with the run's own rows: finished, or out of retries and left as is.
    if settle_closes and not dry_run:
        stamped = now_ist()
        finished = [i for i in landed_ids if i in settle_closes]
        await repo.mark_settled("bid", {i: lifecycle.settle_stamp(settle_closes[i], stamped)
                                        for i in finished})
        gave_up = await repo.bump_settle_attempts(
            "bid", [i for i in failed_ids if i in settle_closes]) or []
        targets = {t.id: t for t in to_reset if t.id}
        for ids, action, reason in (
                (finished, lifecycle.SETTLED, lifecycle.settled_reason("bid")),
                (gave_up, lifecycle.SETTLE_FAILED, lifecycle.settle_failed_reason("bid"))):
            for i in ids:
                t = targets[i]
                log_rows.append(lifecycle.history_row(
                    tenant_id=tenant_id, platform=platform, run_id=run_id, kind="bid",
                    action=action, campaign_id=t.campaign_id, campaign_name=t.campaign_name,
                    keyword=t.keyword, rule_id=t.id, reason=reason, timestamp=now_ist(),
                    success=action == lifecycle.SETTLED))
    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    await repo.record_applied(tenant_id, platform, patches)
    logs.blank(run_id, dry_run=dry_run)
    logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


async def _record_run_blocked(tenant_id, platform: str, run_id: str, rules, reason: str,
                              dry_run: bool) -> None:
    """Write a History row per affected automation when a run cannot start at all.

    Without this the run dies at `setup()` having written nothing, and History shows a
    silent gap: the bid simply stops moving for hours with no row saying why. That is the
    one question a client actually asks of this screen, so "the automation could not sign
    in to Blinkit, so nothing was changed" has to be IN it.

    One row per rule rather than one per run, because the question is asked per campaign —
    a run-level row is invisible from a campaign's own history.
    """
    if not rules:
        return
    rows = [_row(tenant_id, platform, run_id, r.campaign_id, r.campaign_name, r.keyword,
                 "error", None, None, reason, dry_run, False,
                 rule_id=r.id, target=r.target_position)
            for r in rules]
    try:
        await repo.write_run_log(rows)
    except Exception as e:                     # never let bookkeeping mask the real fault
        logs.note(run_id, f"could not record why the run was blocked: {e}", dry_run=dry_run)


async def _still_active(rule_id: str) -> bool:
    """Is this automation STILL active, right now, immediately before we write?

    A tick reads its rules once and then spends 30-60s scraping positions. Pause, Reset and
    Delete are meant to take effect at once — they run on a priority path in a parallel lane
    — so without this an in-flight tick could re-raise a bid a second after the user floored
    it, or write for a rule that no longer exists. One cheap read per write closes all three
    races in the same place.
    """
    rule = await repo.get_bid_rule(rule_id)
    return bool(rule and rule.state == "active")


async def _safe_apply_bid(adapter, client, **kw) -> tuple[bool, Exception | None]:
    """`writes.apply_bid`, but a failed write is ONE failed write instead of a dead run.

    Returns `(applied, error)`. `SessionExpired` still propagates — every remaining keyword
    would fail identically, and the engine has a dedicated path that says so. Everything
    else (a marketplace error, a reply that never arrived, a network drop) comes back for
    the caller to log before moving on.

    2026-09-07: an unacknowledged Blinkit reply escaped the optimizer loop, past its
    `finally`, and took `write_bid_runtime` and `write_run_log` with it — so a tick that
    HAD changed the marketplace left no history, and the drift pause it had just earned was
    lost. Bookkeeping must survive the write it is describing.
    """
    try:
        return await writes.apply_bid(adapter, client, **kw), None
    except writes.SessionExpired:
        raise
    except Exception as e:
        return False, e


# Canonical states a marketplace will not take a bid write in, and the word to say it with.
# `running` and `held` are absent deliberately: ON_HOLD is a running campaign whose budget
# ran out, and both marketplaces accept an UPDATE on one.
_UNWRITABLE = {"paused": "paused", "ended": "finished", "draft": "still a draft"}


def _stranded(mp: str, status: str | None, current) -> str:
    """Why a bid write could not land, when the campaign's own state already explains it.

    Returns `""` when it does not — an unreadable status (`None`) explains nothing, and a
    guessed reason in a client's History is worse than a marketplace's raw one.

    The second half is the part that actually costs money. A bid the reset could not lower
    stays stored at its in-window peak, and both marketplaces bring a campaign back with the
    bid it was carrying — so "paused, nothing to worry about" is wrong: the next restart
    resumes at ₹1009, silently, possibly weeks later and with no automation left to trim it
    (2026-09-15, campaign 638421). Saying so here is the only warning anyone gets.
    """
    word = _UNWRITABLE.get((status or "").lower())
    if not word:
        return ""
    shown = f"₹{int(current)}" if current is not None else "its last value"
    stays = (f"the campaign is {word} on {mp}, which does not accept bid changes — the bid "
             f"stays at {shown}")
    return (f"{stays}, and restarting the campaign would bring it back at {shown}"
            if word == "paused" else stays)


def _plain(err, what: str) -> str:
    """A failure a CLIENT can read, for the History row.

    Raw exceptions leak into this column otherwise — a Zepto block landed as four lines of
    JSON (`HTTP 299 {"error_code": "LOGIN_REQUIRED"…`), which is meaningless to the person
    reading their campaign's history and enough to break a table layout. The full text is
    still in Cloud Logging, where support can find it; this is the sentence.
    """
    detail = " ".join(str(err).split())          # collapse newlines — one row, one line
    for marker, said in _PLAIN_CAUSES:
        if marker in detail:
            detail = said
            break
    if len(detail) > 120:
        detail = detail[:117] + "…"
    return f"{what} ({detail})" if detail else what


# Failures that recur and read as noise in their raw form, said the way a client needs them.
# Matched on a fragment of the raw text; the raw text itself stays in Cloud Logging.
# Only causes we have actually diagnosed belong here — a guessed explanation is worse than
# the marketplace's own words (see `_stranded`).
_PLAIN_CAUSES = (
    # live_position.py: the search session never captured the signed headers Blinkit's
    # search API needs, so no store could be searched. 26 rows 2026-09-16…18.
    ("no Blinkit search headers captured",
     "Blinkit's search could not be opened for this check; it is retried next check"),
    # A search page that never finished loading (35 rows 2026-08-22, before the REST path).
    ("Page.goto: Timeout",
     "Blinkit's search page did not load in time; it is retried next check"),
)


def _write_verdict(ok: bool, write_error, outcome: dict, *, mp: str, landed: str,
                   why: str) -> tuple[str, bool, str]:
    """How ONE bid write is recorded: (action, success, reason).

    Four outcomes, and History has to tell them apart, because they mean different things
    to someone reading it:

      * **landed** → `landed` (apply / drift / recover / open / bounds), the decision as-is;
      * **could not be sent** (an exception) → `error`, with the cause;
      * **not needed** ("the bid is already ₹200") → `no-op`, a success: nothing was wrong;
      * **refused** (rate limit, the marketplace's own bounds, its rejection) → `skip`,
        UNSUCCESSFUL, with the refusal's own words.

    The last used to be filed as a successful `skip` whose reason was the decision — "raising
    to ₹605 because position 13 is worse than target 1" — so the table showed a raise, marked
    it green, and never said it had not happened or why.
    """
    if write_error is not None:
        return "error", False, _plain(write_error, f"{why} — but it could not be sent to {mp}")
    if ok:
        return landed, True, why
    said = (outcome or {}).get("reason")
    if writes.not_needed(outcome):
        return "no-op", True, f"{why} — {said}, so nothing was changed"
    return "skip", False, f"{why} — not applied: {said or f'{mp} did not accept the change'}"


def _row(tenant_id, platform, run_id, cid, cname, kw, action, old, new, reason, dry_run,
         success, *, rule_id=None, position=None, target=None) -> dict:
    # `timestamp` is stamped HERE, when the decision is made — not left to the model
    # default. The rows are all persisted in one batch at the end of the run, so the
    # default fired at insert time and gave every row the SAME timestamp: a run spanning
    # 16:30–16:38 produced thirteen History rows all reading 16:38:49, with no usable
    # ordering. That is what made History unreadable.
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "bid",
        "campaign_id": cid, "campaign_name": cname, "keyword": kw, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        # The decision's inputs, so a per-automation view can explain itself without
        # parsing prose out of `reason`.
        "rule_id": rule_id, "position": position, "target": target,
        "dry_run": dry_run, "success": success, "timestamp": now_ist(),
    }
