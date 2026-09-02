"""Bid-optimizer orchestration (MP-agnostic).

A ~15-min control loop: for each active bid rule, read the keyword's live sponsored
position, step the CPM toward the target position, and route the change through the
write choke-point. Dry-run by default (positions are read, no bid is written). Runtime
state (`last_*`) is persisted to `cm_bid_runtime` — no JSON.

Each window is bracketed by the floor: the first fire of a window writes `min_bid` (and
re-checks until Blinkit reads it back), and the end-of-window `--reset` run writes it
again. The pair is deliberate — the reset is best-effort (the campaign may be dark, or
Blinkit may refuse), and without the window-open floor a reset that failed last night is
never recovered, so the bid ratchets up across days until it pins at `max_bid`.

The decision (`compute_bid` / `next_raise_step` / `_in_window`) is **pure** — ported from
`ad_campaigns.bid_optimizer` (validated v1 logic) and unit-tested in
tests/test_bid_logic.py without Blinkit or the DB. The Blinkit-specific position
sourcing lives behind `adapter.resolve_position` (D17). MVP scrapes every keyword live;
tiering (cheap sources for at-target keywords) is deferred — see the impl-doc backlog.
"""
import uuid
from datetime import datetime, timedelta

from app.utils.time import now_ist
from campaign_manager import config, logs, repo, writes
from campaign_manager.marketplaces import get_adapter

HOLD_MINUTES = 10                       # after a bid change, wait this long before nudging again
_DEFAULT_LAT, _DEFAULT_LON = 12.9767, 77.5713   # Bengaluru fallback when a rule has no location

# The end-of-window reset is FIRED a minute early (see reconciler._bid_reset_fires) so the
# bid drops back before the budget engine — a parallel lane — can stop the campaign, after
# which Blinkit refuses bid writes. This look-ahead is what makes the early fire see the
# window as closed; it must exceed the reconciler's lead so a few seconds of browser-setup
# drift can't land it back inside the window.
RESET_LOOKAHEAD_MINUTES = 2


# ── Pure decision logic (unit-tested) ────────────────────────────────────────

def _time_ok(current_time: str, st: str | None, et: str | None) -> bool:
    """Is `current_time` inside the [st, et] time-of-day window? Handles a window that
    crosses midnight (et <= st → active after start OR before end). Mirrors budget."""
    if not (st or et):
        return True
    if st and et and et <= st:                   # crosses midnight (e.g. 18:00–02:00)
        # `et` is EXCLUSIVE, matching the non-overnight branch below. It used to be
        # `> et`, so an 18:00–02:00 rule was still "in window" AT 02:00 — which would make
        # the end-of-window reset skip the very keyword it fires for. Same inconsistency
        # found and fixed in budget._matches_rule on 2026-08-07; the two must stay
        # symmetric, so it is fixed here too.
        if current_time < st and current_time >= et:
            return False
    else:
        if st and current_time < st:
            return False
        if et and current_time >= et:
            return False
    return True


def _in_window(rule: dict, now: datetime) -> bool:
    """Is the rule active right now? (mirrors budget rule-matching.) Two shapes —
    recurring (date range + optional weekday filter) and once (single date). An overnight
    window's post-midnight tail belongs to the day it STARTED, so a Sun 16:00–02:00 rule
    runs to Mon 02:00, and a weekday filter of Fri/Sat/Sun still covers Sunday's tail."""
    current_time = now.strftime("%H:%M")
    st, et = rule.get("start_time"), rule.get("stop_time")
    if not _time_ok(current_time, st, et):
        return False

    overnight = bool(st and et and et <= st)
    in_tail = overnight and current_time < et
    eff = (now - timedelta(days=1)) if in_tail else now
    eff_date = eff.strftime("%Y-%m-%d")

    if rule.get("type") == "once":
        return eff_date == (rule.get("date") or "")

    if rule.get("start_date") and eff_date < rule["start_date"]:
        return False
    if rule.get("stop_date") and eff_date > rule["stop_date"]:
        return False
    days = [d.lower() for d in (rule.get("days") or [])]   # empty = every day
    if not days:
        return True
    return eff.strftime("%A").lower() in days


def _parse_hhmm(s: str | None) -> tuple[int, int] | None:
    """'HH:MM' → (hour, minute); None if empty/unparseable. Deliberately a local copy of
    the reconciler's: this module stays importable without the jobs/scheduler stack so the
    decision logic is unit-testable with no DB and no Blinkit."""
    if not s:
        return None
    try:
        parts = s.split(":")
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return None
    return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None


def _window_start(rule: dict, now: datetime) -> datetime:
    """The datetime the rule's CURRENT window opened. Only meaningful while the rule is in
    window (callers filter on `_in_window` first).

    An overnight window's post-midnight tail belongs to the day it STARTED — the same rule
    `_in_window` uses — so at 01:00 an 18:00–02:00 rule reports YESTERDAY 18:00. That is
    what keeps "first fire of this window" from resetting itself at midnight. A rule with
    no start_time opens at midnight of its effective day.
    """
    st, et = rule.get("start_time"), rule.get("stop_time")
    hm = _parse_hhmm(st)
    sh, sm = hm if hm else (0, 0)
    overnight = bool(st and et and et <= st)
    in_tail = overnight and now.strftime("%H:%M") < et
    eff = (now - timedelta(days=1)) if in_tail else now
    return eff.replace(hour=sh, minute=sm, second=0, microsecond=0)


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
                raise_step: int) -> tuple[int | None, str]:
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
        return new_cpm, (f"raising to ₹{new_cpm} (+₹{step:g}) because position "
                         f"{position:g} is worse than target {target}")

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


# ── Orchestration ────────────────────────────────────────────────────────────

async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              reset: bool = False, platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    started = now_ist()
    logs.run_start(run_id, "bid_reset" if reset else "bid_optimizer", tenant_id,
                   dry_run=dry_run, platform=platform,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    now = started
    pairs = await repo.get_bid_rules(tenant_id, platform)
    if reset:                                   # end-of-window de-escalation, not optimization
        return await _reset_run(tenant_id, platform, pairs, now, run_id, dry_run)
    active = [(r, rt) for r, rt in pairs if r.state == "active" and _in_window(_rule_dict(r), now)]
    if not active:
        logs.note(run_id, "No keyword automations are in window right now", dry_run=dry_run)
        logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    mp = platform.title()          # what a human reads in the log lines below
    # Resolved ONCE per run so every decision, log line and runtime write in this run
    # agrees about whether drift is armed. Read per-marketplace: the percentages are
    # shared, but a marketplace may override the rupee floors they bottom out at.
    drift_pct = config.bid_tuning(platform, "BID_DRIFT_PCT")
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
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
    bids_cache: dict[int, dict] = {}       # campaign_id → {keyword: cpm}  (one detail fetch/campaign)
    products_cache: dict[int, list] = {}   # campaign_id → [products]
    status_cache: dict[int, str | None] = {}   # campaign_id → canonical status (same fetch)
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
    _first = active[0][0]
    pos_session = await adapter.open_position_session(
        pw, float(_first.lat or _DEFAULT_LAT), float(_first.lon or _DEFAULT_LON))

    try:
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
                except Exception as e:
                    status_cache[cid] = None
                    bids_cache[cid], products_cache[cid] = {}, []
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  level="warning",
                                  msg=f"could not read the campaign from {mp} — {e}")

            lat, lon = float(rule.lat or _DEFAULT_LAT), float(rule.lon or _DEFAULT_LON)
            live_cpm = bids_cache[cid].get(kw)
            logs.rule_context(
                run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                target=rule.target_position,
                current_cpm=live_cpm if live_cpm is not None else rule.min_bid,
                min_bid=rule.min_bid, max_bid=rule.max_bid,
                location_name=rule.location_name, lat=lat, lon=lon)

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
            opened = bool(runtime and runtime.updated_at
                          and runtime.updated_at >= _window_start(_rule_dict(rule), now))
            if not opened and (live_cpm is None or int(live_cpm) != int(rule.min_bid)):
                # Decision BEFORE the write, as everywhere else — a log that reports the
                # outcome before the reason that caused it is exactly what makes a run
                # hard to read.
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             msg="first run of today's window — resetting to the floor "
                                 "before optimising")
                ok = await writes.apply_bid(
                    adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                    new_cpm=rule.min_bid, current_cpm=live_cpm, min_bid=rule.min_bid,
                    max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                    recent_writes=0,
                )
                applied += int(ok)
                skipped += int(not ok)
                was = f" (was ₹{live_cpm})" if live_cpm is not None else ""
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                             msg=(f"applied — bid is now ₹{rule.min_bid}{was}" if ok else
                                  f"not applied — {mp} rejected the change to ₹{rule.min_bid}"))
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "open" if ok else "skip", live_cpm, rule.min_bid,
                                     "window opened → min", dry_run, ok))
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
                bounded = writes.clamp_bid(live_cpm, rule.min_bid, ceiling)
                if int(bounded) != int(live_cpm):
                    # Not rate-limited: this is a correctness write, not optimization, and
                    # it cannot run away — one write puts the bid back inside the bounds.
                    why = ("above the" if int(live_cpm) > int(ceiling) else "below the")
                    limit = ceiling if int(live_cpm) > int(ceiling) else rule.min_bid
                    logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                 msg=f"live bid ₹{live_cpm} is {why} ₹{limit} limit — "
                                     f"forcing it back into range")
                    ok = await writes.apply_bid(
                        adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                        new_cpm=bounded, current_cpm=live_cpm, min_bid=rule.min_bid,
                        max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                        recent_writes=0,
                    )
                    applied += int(ok)
                    skipped += int(not ok)
                    logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                                 msg=(f"applied — bid is now ₹{bounded}" if ok else
                                      f"not applied — {mp} rejected the change to ₹{bounded}"))
                    log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                         "bounds" if ok else "skip", live_cpm, bounded,
                                         f"live bid {why} — forced into [{rule.min_bid}–"
                                         f"{ceiling}]", dry_run, ok))
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
            current_cpm = (int(rule.min_bid) if open_stamp else
                           int((runtime.last_cpm if runtime else None)
                               or bids_cache[cid].get(kw) or rule.min_bid))

            # ── One scrape per (keyword, store), not per rule ──
            # Several campaigns routinely target the SAME keyword at the same store — on
            # 2026-08-22 thirteen rules resolved to four distinct pairs, so the run fired
            # five identical "cotton candy" searches back to back and Blinkit began timing
            # them out. The search results are identical for a shared pair; only the
            # product match differs, so the fetch is shared and `locate_position` runs
            # per rule. A failed fetch is cached as the failure too — re-scraping a
            # keyword that just timed out only feeds the throttling that caused it.
            pos_key = (kw, lat, lon)
            reused = pos_key in positions_cache
            if not reused:
                try:
                    positions_cache[pos_key] = (await adapter.fetch_positions(
                        pos_session, kw, lat, lon), None)
                except Exception as e:
                    positions_cache[pos_key] = ([], e)
            results, fetch_error = positions_cache[pos_key]

            try:
                if fetch_error is not None:
                    raise fetch_error
                # `campaign_id` and `match_type` matter on a marketplace whose search
                # results say which campaign and keyword won each sponsored slot (Zepto
                # does; Blinkit does not and ignores them). Passing them unconditionally
                # keeps the engine free of per-marketplace branching.
                position, source = adapter.locate_position(
                    results, kw, lat, lon,
                    products=products, campaign_id=cid, match_type=rule.match_type,
                    brand_name=rule.brand_name,
                )
            except Exception as e:
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="error",
                              msg=f"could not check position — {e}. Bid left unchanged")
                errors += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "error", current_cpm, current_cpm, str(e), dry_run, False))
                continue

            # What the search saw. A rule reusing this run's scrape says so, rather than
            # implying it went and looked again.
            sponsored = sum(1 for r in results if r.get("is_ad"))
            seen = (f'reusing this run\'s "{kw}" search'
                    if reused else
                    f"found {len(results)} product{'' if len(results) == 1 else 's'}, "
                    f"{sponsored} sponsored")
            # ── Not in the results ──────────────────────────────────────────
            #
            # Being absent is the WORST outcome, not a neutral one: the whole point of a
            # sponsored slot is to appear. Skipping here means that once a keyword is
            # outbid off the page it can never climb back — every tick sees "absent",
            # skips, and the bid never moves. Worse, the next window open writes
            # `min_bid`, which is lower still.
            #
            # So an opted-in marketplace treats absence as "worse than anything we could
            # see" and raises. The synthetic position is `len(results) + 1` — a genuine
            # lower bound on where we are, and one that keeps the escalation honest: if
            # the next tick is still absent the position has not improved, so the step
            # grows exactly as it would for a real slot.
            #
            # ⚠️ OPT-IN PER MARKETPLACE (`getattr(..., False)`), because the guard this
            # replaces was protecting against something real on Blinkit: its DOM fallback
            # reported every result as organic, so "absent" could mean a broken SOURCE
            # rather than a missing ad, and raising against that is bidding on garbage.
            # Zepto's marker is positive and verified (`tagsV2` + `uclId`), so absence
            # there is a fact about the auction. Blinkit declares nothing and is unchanged.
            absent = position is None
            if absent and not getattr(adapter, "RAISE_WHEN_ABSENT", False):
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="warning", msg=f"{seen} — {source}, leaving the bid unchanged")
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "skip", current_cpm, current_cpm, source, dry_run, True))
                continue
            if absent:
                position = float(len(results) + 1)
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              level="warning",
                              msg=f"{seen} — {source}. Treating that as worse than position "
                                  f"{len(results)} and bidding up to get on the page")
            else:
                logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              msg=f"{seen} — our ad is at position {position:g}",
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
                                     dry_run, True))

            new_cpm, reason = compute_bid(
                position, target, current_cpm, rule.min_bid, ceiling,
                last_pos, mins, last_holding_cpm=holding_cpm, drift_paused=drift_paused,
                drift_pct=drift_pct, drift_min_step=config.bid_tuning(platform, "BID_DRIFT_MIN_STEP"),
                raise_step=step_now,
            )
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
                rt["last_cpm"] = int(rule.min_bid)
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

            # No change (target held, HOLD, awaiting confirmation, or drift paused): record
            # the observed position, but do NOT write a History row — those every 15 min
            # would bury the real changes (narrated to Cloud Logging above; D6).
            if new_cpm is None:
                skipped += 1
                runtime_rows.append(rt)
                continue

            # Per-KEYWORD rate limit: the guard exists to catch a runaway loop, and a
            # per-campaign count would make a multi-keyword campaign throttle keywords
            # that are behaving. Drift writes up to 4×/hour/keyword against a cap of 12.
            recent = await repo.recent_write_count(
                tenant_id, cid, window_minutes=config.RATE_WINDOW_MINUTES,
                kind="bid", keyword=kw,
            )
            ok = await writes.apply_bid(
                adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                new_cpm=new_cpm, current_cpm=current_cpm, min_bid=rule.min_bid,
                max_bid=ceiling, match_type=rule.match_type, dry_run=dry_run,
                recent_writes=recent,
            )
            applied += int(ok)
            skipped += int(not ok)
            final = int(writes.clamp_bid(new_cpm, rule.min_bid, ceiling))
            if ok:
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=True,
                             msg=(f"would set bid to ₹{final} — not sent" if dry_run
                                  else f"applied — bid is now ₹{final}"))
            elif recent >= config.MAX_WRITES_PER_WINDOW:
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=False,
                             msg=f"not applied — rate limit reached ({recent} changes this hour)")
            elif final == int(current_cpm):
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=False,
                             msg=f"not applied — the bid is already ₹{final}")
            else:
                logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=False,
                             msg=f"not applied — {mp} rejected the change to ₹{final}")

            if ok and not dry_run:                 # only a REAL write changes last_cpm/timestamp
                rt["last_cpm"] = final
                rt["last_bid_updated_at"] = now.isoformat()
            runtime_rows.append(rt)
            drifted = drift_pct > 0 and position <= target
            action = "recover" if recovering else ("drift" if drifted else "apply")
            log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                 action if ok else "skip", current_cpm, new_cpm, reason, dry_run, True))
    finally:
        await adapter.close_position_session(pos_session)
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    logs.blank(run_id, dry_run=dry_run)
    logs.run_summary(
        run_id, "bid_optimizer", dry_run=dry_run, unit="automations",
        processed=processed, applied=applied, skipped=skipped, errors=errors,
        seconds=(now_ist() - started).total_seconds(),
        note=f"{len(positions_cache)} searches for {processed} keywords")
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


async def _reset_run(tenant_id: uuid.UUID, platform: str, pairs, now: datetime,
                     run_id: str, dry_run: bool) -> dict:
    """End-of-window reset: set each just-closed keyword's bid back to its `min_bid`, so a
    bid the optimizer pushed up doesn't keep spending high after the window. No position
    scrape (cheap). Skips a keyword still covered by an in-window rule, and any bid already
    at/below its floor. Only a real (live) write updates runtime `last_cpm`."""
    # Windows are evaluated slightly AHEAD of now, because the reconciler fires this run a
    # minute BEFORE the window's stop time — so the bid drops back before the budget engine
    # (a parallel lane) can stop the campaign, after which Blinkit refuses bid writes. At
    # the nominal stop time the look-ahead changes nothing, so a reset fired exactly on the
    # boundary, or by hand mid-window, behaves as it always did.
    at = now + timedelta(minutes=RESET_LOOKAHEAD_MINUTES)
    active = [r for r, _ in pairs if r.state == "active"]
    live_keys = {(r.campaign_id, r.keyword) for r in active if _in_window(_rule_dict(r), at)}
    to_reset = [r for r in active
                if not _in_window(_rule_dict(r), at)
                and (r.campaign_id, r.keyword) not in live_keys]
    if not to_reset:
        logs.note(run_id, "No keyword windows are closing right now", dry_run=dry_run)
        logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    mp = platform.title()
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
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
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    logs.note(run_id, f"{len(to_reset)} keywords closing their window", dry_run=dry_run)

    processed = applied = skipped = errors = 0
    runtime_rows: list[dict] = []
    log_rows: list[dict] = []
    bids_cache: dict[int, dict] = {}
    status_cache: dict[int, str | None] = {}
    try:
        for r in to_reset:
            processed += 1
            cid, kw = r.campaign_id, r.keyword
            logs.blank(run_id, dry_run=dry_run)
            logs.rule_header(run_id, dry_run=dry_run, index=processed, total=len(to_reset),
                             campaign_name=r.campaign_name, campaign_id=cid)
            if cid not in bids_cache:
                try:
                    status_cache[cid], _, detail = await adapter.read_campaign(client, cid)
                    bids_cache[cid] = adapter.bids_from_detail(detail)
                except Exception as e:
                    status_cache[cid], bids_cache[cid] = None, {}
                    logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  level="warning",
                                  msg=f"could not read the current bid from {mp} — {e}")

            status = status_cache[cid]
            # An UNREADABLE bid is not a bid at the floor. This used to fall back to
            # `min_bid`, which the check below then read as "already there, nothing to do"
            # and skipped in silence — no decision line, no History row. It was the reset's
            # single most likely way to do nothing at all while looking healthy. `None` now
            # means "we don't know", and we write anyway.
            current = bids_cache[cid].get(kw)
            shown = f"₹{current}" if current is not None else "unknown"
            logs.observed(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                          msg=f'keyword "{kw}" · window closed · current bid {shown}')

            if current is not None and int(current) <= int(r.min_bid):
                # Genuinely already at the floor. Skipped rather than written because a
                # keyword-bid write is a FULL campaign PUT (client.update_keyword_bids
                # re-submits budget, dates and pids too), and the budget engine writes the
                # same campaign from a parallel lane around this minute — so a PUT that
                # changes nothing is a free chance to clobber a budget. Logged either way.
                logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                             msg=f"already at the ₹{r.min_bid} floor — nothing to change")
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, r.campaign_name, kw,
                                     "skip", current, r.min_bid,
                                     f"window closed · already at min ₹{current}", dry_run, True))
                continue

            # No status gate. `held` (ON_HOLD) is a RUNNING campaign whose budget ran out —
            # Blinkit takes an UPDATE on it, and budget.py already treats it as writable.
            # A genuinely stopped campaign gets the write refused, and that refusal is the
            # useful outcome: a failed History row you can see, not an invisible skip.
            # A rejected write must not abort the whole reset either — one dark campaign
            # shouldn't cost every other keyword its de-escalation.
            logs.decided(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                         msg=f"resetting to the ₹{r.min_bid} floor so it does not spend high "
                             f"overnight (campaign is {status or 'in an unknown state'})")
            try:
                ok = await writes.apply_bid(
                    adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                    new_cpm=r.min_bid, current_cpm=current, min_bid=r.min_bid,
                    max_bid=resolve_ceiling(r.max_bid, config.bid_tuning(platform, "BID_MAX_ABSOLUTE")),
                    match_type=r.match_type, dry_run=dry_run, recent_writes=0,
                )
                err = None
            except Exception as e:
                ok, err = False, str(e)
            applied += int(ok)
            errors += int(not ok)
            logs.applied(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw, ok=ok,
                         msg=(f"would set bid to ₹{r.min_bid} — not sent" if (ok and dry_run)
                              else f"applied — bid is now ₹{r.min_bid}" if ok
                              else f"not applied — {mp} rejected the reset"
                                   + (f" ({err})" if err else "")))
            if ok and not dry_run:
                runtime_rows.append({"rule_id": r.id, "last_cpm": int(r.min_bid)})
            log_rows.append(_row(tenant_id, platform, run_id, cid, r.campaign_name, kw,
                                 "reset", current, r.min_bid,
                                 err or f"window closed → min (campaign {status or 'unknown'})",
                                 dry_run, ok))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    logs.blank(run_id, dry_run=dry_run)
    logs.run_summary(run_id, "bid_reset", dry_run=dry_run, unit="keywords",
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


def _row(tenant_id, platform, run_id, cid, cname, kw, action, old, new, reason, dry_run, success) -> dict:
    # `timestamp` is stamped HERE, when the decision is made — not left to the model
    # default. The rows are all persisted in one batch at the end of the run, so the
    # default fired at insert time and gave every row the SAME timestamp: a run spanning
    # 16:30–16:38 produced thirteen History rows all reading 16:38:49, with no usable
    # ordering. That is what made History unreadable.
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "bid",
        "campaign_id": cid, "campaign_name": cname, "keyword": kw, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success, "timestamp": now_ist(),
    }
