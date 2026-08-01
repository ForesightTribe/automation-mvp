"""Budget-scheduler orchestration (MP-agnostic).

For each of a tenant's budget schedules: match the rule that applies *now* (IST) →
compute the target budget (or `default_budget`) → read the current budget → route
through the write choke-point. Dry-run by default (reads happen, no writes).

The rule-matching (`target_for_now` / `_matches_rule`) is a **pure function** —
ported from `ad_campaigns/scheduler.py` (validated v1 logic) and unit-tested in
tests/test_budget_rules.py without Blinkit or the DB.
"""
import uuid
from datetime import datetime, timedelta

from app.utils.time import now_ist
from campaign_manager import config, logs, repo, writes
from campaign_manager.marketplaces import get_adapter


# ── Pure rule matching (unit-tested) ────────────────────────────────────────

def _current_slot(now: datetime) -> str:
    h = now.hour
    if 6 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


def _matches_rule(rule: dict, now: datetime) -> bool:
    """Does this rule apply at `now`? (time-of-day gate → date/day against the window's
    START day). An overnight window's post-midnight tail belongs to the day it started,
    so a Sun 16:00–02:00 rule is active until Mon 02:00, and a Fri 00:00–02:00 moment is
    NOT active (that tail belongs to Thursday, which has no window)."""
    current_time = now.strftime("%H:%M")
    start_time = rule.get("start_time")
    end_time = rule.get("end_time")
    overnight = bool(start_time and end_time and end_time <= start_time)

    # ── time-of-day gate (overnight-aware) ──
    if start_time or end_time:
        if overnight:
            if current_time < start_time and current_time > end_time:
                return False
        else:
            if start_time and current_time < start_time:
                return False
            if end_time and current_time >= end_time:
                return False
    elif rule.get("time_slots") and _current_slot(now) not in rule["time_slots"]:
        return False

    # The overnight tail (past midnight, before the window end) belongs to yesterday.
    in_tail = overnight and current_time < end_time
    eff = (now - timedelta(days=1)) if in_tail else now
    eff_date = eff.strftime("%Y-%m-%d")

    if rule.get("type") == "once":
        return eff_date == (rule.get("date") or "")

    # recurring — date range + weekday, both against the effective (start) day.
    if rule.get("start_date") and eff_date < rule["start_date"]:
        return False
    if rule.get("end_date") and eff_date > rule["end_date"]:
        return False
    days = [d.lower() for d in (rule.get("days") or [])]   # empty = every day
    if not days:
        return True
    return eff.strftime("%A").lower() in days


def _reason(rule: dict) -> str:
    """Human-readable why-this-rule string (for logs + history)."""
    if rule.get("start_time") or rule.get("end_time"):
        time_desc = f"{rule.get('start_time', '00:00')}–{rule.get('end_time', '23:59')}"
    else:
        time_desc = ", ".join(rule.get("time_slots", [])) or "all day"
    if rule.get("type") == "once":
        return f"one-time {rule.get('date', '')} / {time_desc}"
    days_str = ", ".join(rule.get("days", [])) or "every day"
    date_range = ""
    if rule.get("start_date") or rule.get("end_date"):
        date_range = f" ({rule.get('start_date', '')}–{rule.get('end_date', '')})"
    return f"{days_str}{date_range} / {time_desc}"


def target_for_now(default_budget: float, rules: list[dict], now: datetime) -> tuple[float, str]:
    """The budget that should apply right now: the first matching rule's budget, else
    the default. Returns (target, reason)."""
    for rule in rules:
        if _matches_rule(rule, now):
            return rule["budget"], _reason(rule)
    return default_budget, "no active rule — default budget"


def _rule_to_dict(r) -> dict:
    """CmBudgetRule ORM row → the plain dict the matcher expects."""
    return {
        "type": r.type, "days": r.days or [], "time_slots": r.time_slots or [],
        "start_time": r.start_time, "end_time": r.end_time,
        "start_date": r.start_date, "end_date": r.end_date,
        "date": r.date, "budget": r.budget,
    }


# ── Orchestration ───────────────────────────────────────────────────────────

async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "budget_scheduler", tenant_id, dry_run=dry_run, platform=platform)

    schedules = await repo.get_budget_schedules(tenant_id, platform)
    if not schedules:
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=0)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 0}

    adapter = get_adapter(platform)
    processed = applied = skipped = errors = 0
    log_rows: list[dict] = []

    # A session/browser is only set up when there's work — reads happen even in dry-run.
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
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
            logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    now = now_ist()  # captured after setup so the time is fresh at a boundary
    try:
        for schedule, rules in schedules:
            if schedule.state != "active":
                continue
            processed += 1
            cid, cname = schedule.campaign_id, schedule.campaign_name
            target, reason = target_for_now(
                schedule.default_budget, [_rule_to_dict(r) for r in rules], now
            )

            if target is None or target <= 0:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                              verdict="skip", reason=f"non-positive target · {reason}")
                skipped += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "skip", None, target, reason, dry_run, True))
                continue

            logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                          verdict=f"target ₹{target:g}", reason=reason)
            try:
                current = await adapter.read_budget(client, cid)
            except Exception as e:
                logs.decision(run_id, dry_run=dry_run, campaign_id=cid,
                              verdict="error", reason=f"read failed: {e}")
                errors += 1
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     "error", None, target, str(e), dry_run, False))
                continue

            # recent_writes=0 in dry-run (nothing real is counted); real count is wired
            # for live mode (V5), where the rate-limit guardrail actually gates writes.
            ok = await writes.apply_budget(
                adapter, client, run_id=run_id, campaign_id=cid,
                target=target, current=current, dry_run=dry_run, recent_writes=0,
            )
            action = "apply" if ok else ("no-op" if current == target else "skip")
            applied += int(ok)
            skipped += int(not ok)
            # A no-op (budget already correct — the common case for the hourly poll) is
            # narrated to Cloud Logging via `logs.decision` above, but NOT written to the
            # History table: hundreds of "nothing changed" rows would bury the real changes
            # (D6 — verbose narration goes to logs, History holds actual actions only).
            if action != "no-op":
                log_rows.append(_row(tenant_id, platform, run_id, cid, cname,
                                     action, current, target, reason, dry_run, True))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_run_log(log_rows)
    logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}


def _row(tenant_id, platform, run_id, cid, cname, action, old, new, reason, dry_run, success) -> dict:
    return {
        "tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "budget",
        "campaign_id": cid, "campaign_name": cname, "keyword": None, "action": action,
        "old_value": old, "new_value": new, "reason": reason,
        "dry_run": dry_run, "success": success,
    }
