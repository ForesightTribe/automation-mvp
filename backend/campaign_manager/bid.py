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
        if current_time < st and current_time > et:
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
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "bid_optimizer", tenant_id, dry_run=dry_run, platform=platform)

    now = now_ist()
    pairs = await repo.get_bid_rules(tenant_id, platform)
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

    try:
        for rule, runtime in active:
            processed += 1
            cid, kw = rule.campaign_id, rule.keyword

            if cid not in bids_cache:
                try:
                    bids_cache[cid] = await adapter.read_bids(client, cid)
                    products_cache[cid] = await adapter.read_products(client, cid)
                except Exception as e:
                    bids_cache[cid], products_cache[cid] = {}, []
                    logs.decision(run_id, dry_run=dry_run, campaign_id=cid, keyword=kw,
                                  verdict="warn", reason=f"campaign fetch failed: {e}")
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

            # No change (target reached or HOLD): record the observed position only.
            if new_cpm is None:
                action = "target" if reason.startswith("target") else "hold"
                skipped += 1
                runtime_rows.append({"rule_id": rule.id, "last_position": position})
                log_rows.append(_row(tenant_id, platform, run_id, cid, rule.campaign_name, kw,
                                     action, current_cpm, current_cpm, reason, dry_run, True))
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


def _row(tenant_id, platform, run_id, cid, cname, kw, action, old, new, reason, dry_run, success) -> dict:
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "bid",
        "campaign_id": cid, "campaign_name": cname, "keyword": kw, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success,
    }
