"""Bid-optimizer orchestration (MP-agnostic).

A ~15-min control loop: for each active bid rule, read the keyword's live sponsored
position, step the CPM toward the target position, and route the change through the
write choke-point. Dry-run by default (positions are read, no bid is written). Runtime
state (`last_*`) is persisted to `cm_bid_runtime` — no JSON.

The decision (`_dynamic_step` / `compute_bid` / `_in_window`) is **pure** — ported from
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

def _dynamic_step(distance: float) -> float:
    """Bid step (₹) as a function of distance from target — bigger when far."""
    if distance >= 4:
        return 100
    if distance >= 3:
        return 50
    if distance >= 1:
        return 25
    return 12.5


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


def compute_bid(position: float, target: int, current_cpm: int, min_bid: int, max_bid: int,
                last_position: float | None, minutes_since_change: float | None) -> tuple[int | None, str]:
    """The bid decision. Returns (new_cpm | None, reason). None = no change:
    'target …' when already at target, or 'hold …' during the reflection window when
    position hasn't improved since the last change."""
    if position == target:
        return None, f"target achieved (pos {position})"

    step = _dynamic_step(abs(position - target))

    if position > target:                        # worse than target → raise the bid
        # HOLD: position hasn't improved since the last change and we're still inside the
        # reflection window → wait for Blinkit to catch up rather than over-bidding.
        if (last_position is not None and position >= last_position
                and minutes_since_change is not None and minutes_since_change < HOLD_MINUTES):
            return None, (f"hold — pos {position} ≥ last {last_position}, "
                          f"{minutes_since_change:.0f}min < {HOLD_MINUTES}min reflection")
        new_cpm = min(int(current_cpm + step), int(max_bid))
        return new_cpm, f"raise: pos {position} > target {target}, step ₹{step:g}"

    new_cpm = max(int(current_cpm - step), int(min_bid))   # better than target → lower the bid
    return new_cpm, f"lower: pos {position} < target {target}, step ₹{step:g}"


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
    logs.run_start(run_id, "bid_reset" if reset else "bid_optimizer", tenant_id,
                   dry_run=dry_run, platform=platform)

    now = now_ist()
    pairs = await repo.get_bid_rules(tenant_id, platform)
    if reset:                                   # end-of-window de-escalation, not optimization
        return await _reset_run(tenant_id, platform, pairs, now, run_id, dry_run)
    active = [(r, rt) for r, rt in pairs if r.state == "active" and _in_window(_rule_dict(r), now)]
    if not active:
        logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run)

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
            logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run,
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    processed = applied = skipped = errors = 0
    runtime_rows: list[dict] = []
    log_rows: list[dict] = []
    bids_cache: dict[int, dict] = {}       # campaign_id → {keyword: cpm}  (one detail fetch/campaign)
    products_cache: dict[int, list] = {}   # campaign_id → [products]
    status_cache: dict[int, str | None] = {}   # campaign_id → canonical status (same fetch)

    try:
        for rule, runtime in active:
            processed += 1
            cid, kw = rule.campaign_id, rule.keyword

            if cid not in bids_cache:
                try:
                    # ONE detail read gives status AND bids (docs/campaign-activation.md §6).
                    status_cache[cid], _, detail = await adapter.read_campaign(client, cid)
                    bids_cache[cid] = adapter.bids_from_detail(detail)
                    products_cache[cid] = await adapter.read_products(client, cid)
                except Exception as e:
                    status_cache[cid] = None
                    bids_cache[cid], products_cache[cid] = {}, []
                    logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  verdict="warn", reason=f"campaign fetch failed: {e}")

            # A stopped campaign isn't serving, so there is no position to chase — and
            # Blinkit rejects bid writes on one anyway. Skipping here saves the expensive
            # part of a bid run: a live consumer search per keyword, in a browser. Matters
            # most for a campaign that `stop_after_window` keeps dark half the day.
            # A status we couldn't read (None) is NOT treated as stopped — a read blip
            # must not silently pause optimization.
            if status_cache[cid] is not None and status_cache[cid] != "running":
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              verdict="skip", reason=f"campaign is {status_cache[cid]} — not serving")
                skipped += 1
                continue

            products = products_cache[cid]
            names = [p.get("name", "") for p in products if p.get("name")]
            pids = [str(p["pid"]) for p in products if p.get("pid")]

            current_cpm = int((runtime.last_cpm if runtime else None)
                              or bids_cache[cid].get(kw) or rule.min_bid)

            try:
                position, source = await adapter.resolve_position(
                    client, cid, kw,
                    lat=float(rule.lat or _DEFAULT_LAT), lon=float(rule.lon or _DEFAULT_LON),
                    product_names=names, product_pids=pids, brand_name=rule.brand_name,
                )
            except Exception as e:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              verdict="error", reason=f"position read failed: {e}")
                errors += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "error", current_cpm, current_cpm, str(e), dry_run, False))
                continue

            if position is None:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              verdict="skip", reason=source)
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     "skip", current_cpm, current_cpm, source, dry_run, True))
                continue

            last_pos = runtime.last_position if runtime else None
            mins = _minutes_since(runtime.last_bid_updated_at if runtime else None, now)
            new_cpm, reason = compute_bid(position, rule.target_position, current_cpm,
                                          rule.min_bid, rule.max_bid, last_pos, mins)
            logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                          verdict=(f"bid ₹{new_cpm}" if new_cpm is not None else "no change"),
                          reason=f"{reason} · {source}")

            # No change (target reached or HOLD): record the observed position, but do NOT
            # write a History row — "held / already at target" every 15 min would bury the
            # real changes (it's narrated to Cloud Logging via logs.decision above; D6).
            if new_cpm is None:
                skipped += 1
                runtime_rows.append({"rule_id": rule.id, "last_position": position})
                continue

            ok = await writes.apply_bid(
                adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                new_cpm=new_cpm, current_cpm=current_cpm, min_bid=rule.min_bid,
                max_bid=rule.max_bid, match_type=rule.match_type, dry_run=dry_run, recent_writes=0,
            )
            applied += int(ok)
            skipped += int(not ok)

            rt = {"rule_id": rule.id, "last_position": position}
            if ok and not dry_run:                 # only a REAL write changes last_cpm/timestamp
                rt["last_cpm"] = int(writes.clamp_bid(new_cpm, rule.min_bid, rule.max_bid))
                rt["last_bid_updated_at"] = now.isoformat()
            runtime_rows.append(rt)
            log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                 "apply" if ok else "skip", current_cpm, new_cpm, reason, dry_run, True))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
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
        logs.run_summary(run_id, "bid_reset", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "bid_reset", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run)

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
            logs.run_summary(run_id, "bid_reset", dry_run=dry_run,
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    processed = applied = skipped = errors = 0
    runtime_rows: list[dict] = []
    log_rows: list[dict] = []
    bids_cache: dict[int, dict] = {}
    status_cache: dict[int, str | None] = {}
    try:
        for r in to_reset:
            processed += 1
            cid, kw = r.campaign_id, r.keyword
            if cid not in bids_cache:
                try:
                    status_cache[cid], _, detail = await adapter.read_campaign(client, cid)
                    bids_cache[cid] = adapter.bids_from_detail(detail)
                except Exception as e:
                    status_cache[cid], bids_cache[cid] = None, {}
                    logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  verdict="warn", reason=f"bid read failed: {e}")

            # A stopped campaign can't take a bid write and doesn't need one — it isn't
            # serving, so a bid left high costs nothing while it's off. This is the
            # expected case when the budget engine won the race to stop it.
            if status_cache[cid] is not None and status_cache[cid] != "running":
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              verdict="skip", reason=f"campaign is {status_cache[cid]} — no bid write")
                skipped += 1
                continue

            current = int(bids_cache[cid].get(kw) or r.min_bid)
            if current <= r.min_bid:
                skipped += 1                              # already at the floor — nothing to do
                continue
            logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                          verdict=f"reset ₹{r.min_bid}", reason=f"window closed · {current}→{r.min_bid}")
            # A rejected write must not abort the whole reset: one keyword on a campaign
            # that just went dark shouldn't cost every other keyword its de-escalation, or
            # fail the job and page someone at 2am.
            try:
                ok = await writes.apply_bid(
                    adapter, client, run_id=run_id, campaign_id=cid, keyword=kw,
                    new_cpm=r.min_bid, current_cpm=current, min_bid=r.min_bid,
                    max_bid=r.max_bid, match_type=r.match_type, dry_run=dry_run, recent_writes=0,
                )
            except Exception as e:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                              verdict="skip", reason=f"reset rejected: {e}")
                skipped += 1
                continue
            applied += int(ok)
            skipped += int(not ok)
            if ok and not dry_run:
                runtime_rows.append({"rule_id": r.id, "last_cpm": int(r.min_bid)})
            log_rows.append(_row(tenant_id, platform, run_id, cid, r.campaign_name, kw,
                                 "reset" if ok else "skip", current, r.min_bid,
                                 "window closed → min", dry_run, ok))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_bid_runtime(runtime_rows)
    await repo.write_run_log(log_rows)
    logs.run_summary(run_id, "bid_reset", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


def _row(tenant_id, platform, run_id, cid, cname, kw, action, old, new, reason, dry_run, success) -> dict:
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "bid",
        "campaign_id": cid, "campaign_name": cname, "keyword": kw, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success,
    }
