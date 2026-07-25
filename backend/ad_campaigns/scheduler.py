"""
Blinkit budget scheduler — applies budget rules based on current IST time.

Run from backend/:
    python -m ad_campaigns.scheduler

Set up Windows Task Scheduler to run this every 30-60 minutes for full automation.

Time slots (IST):
    morning   06:00 – 12:00
    afternoon 12:00 – 18:00
    evening   18:00 – 22:00
    night     22:00 – 06:00
"""
import asyncio
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.table import Table
from rich import box

from ad_campaigns.client import setup
from ad_campaigns.schedules import load_schedules

console = Console()

_IST = timezone(timedelta(hours=5, minutes=30))
TENANT_ID = "a870fd8d-7373-47ec-ad69-5dd08ce35542"


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
    today = now.strftime("%Y-%m-%d")
    start_date = rule.get("start_date")
    end_date = rule.get("end_date")
    if start_date and today < start_date:
        return False
    if end_date and today > end_date:
        return False

    start_time = rule.get("start_time")
    end_time = rule.get("end_time")
    if start_time or end_time:
        current_time = now.strftime("%H:%M")
        if start_time and end_time and end_time <= start_time:
            # Midnight-crossing range (e.g. 18:15–02:00): active if after start OR before end
            if current_time < start_time and current_time > end_time:
                return False
        else:
            if start_time and current_time < start_time:
                return False
            if end_time and current_time >= end_time:
                return False
    elif rule.get("time_slots") and _current_slot(now) not in rule["time_slots"]:
        return False

    if rule.get("type") == "once":
        rule_date = rule.get("date", "")
        if today == rule_date:
            return True
        # Midnight-crossing: also match on the next calendar day if still before end_time
        _st = rule.get("start_time", "")
        _et = rule.get("end_time", "")
        if _st and _et and _et <= _st:
            from datetime import timedelta
            try:
                next_day = (datetime.strptime(rule_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                if today == next_day:
                    return now.strftime("%H:%M") < _et
            except ValueError:
                pass
        return False
    # recurring — empty days list means "every day" (used when date range is the constraint)
    days = [d.lower() for d in rule.get("days", [])]
    if not days:
        return True
    return now.strftime("%A").lower() in days


async def _run_core(client, now: datetime, schedules: list[dict] | None = None) -> list[dict]:
    """Apply budget rules using an already-connected BlinkitClient. Returns log entries."""
    if schedules is None:
        schedules = load_schedules()
    if not schedules:
        console.print("[yellow]No schedules found. Add via: python -m ad_campaigns.main → option 4[/yellow]")
        return []

    log_entries: list[dict] = []

    current_slot = _current_slot(now)
    console.print(
        f"[dim]Scheduler — {now.strftime('%A %d %b %Y, %H:%M IST')} "
        f"(slot: {current_slot})[/dim]\n"
    )

    table = Table(title="Scheduled Budget Actions", box=box.ROUNDED, show_lines=False)
    table.add_column("Campaign", max_width=38)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Budget", justify="right", style="yellow")
    table.add_column("Reason", style="dim")
    table.add_column("Result", width=10)

    for sched in schedules:
        if not sched.get("enabled", True):
            continue
        campaign_id = sched["campaign_id"]
        campaign_name = sched.get("campaign_name", str(campaign_id))
        default_budget = sched.get("default_budget", 0)

        matched_rule = next(
            (r for r in sched.get("rules", []) if _matches_rule(r, now)),
            None,
        )

        if matched_rule:
            target_budget = matched_rule["budget"]
            # Build time description: prefer explicit time range over slot names
            if matched_rule.get("start_time") or matched_rule.get("end_time"):
                time_desc = f"{matched_rule.get('start_time', '00:00')}–{matched_rule.get('end_time', '23:59')}"
            else:
                time_desc = ", ".join(matched_rule.get("time_slots", []))
            if matched_rule.get("type") == "once":
                reason = f"one-time {matched_rule.get('date', '')} / {time_desc}"
            else:
                days_str = ", ".join(matched_rule.get("days", [])) or "every day"
                date_range = ""
                if matched_rule.get("start_date") or matched_rule.get("end_date"):
                    date_range = f" ({matched_rule.get('start_date', '')}–{matched_rule.get('end_date', '')})"
                reason = f"{days_str}{date_range} / {time_desc}"
        else:
            target_budget = default_budget
            reason = "No active rule — default budget applied"

        if target_budget <= 0:
            table.add_row(campaign_name, str(campaign_id), "—", reason, "[yellow]skipped[/yellow]")
            continue

        changes = {"bidding_strategy": {"total_budget": float(target_budget), "pacing_type": "DAILY"}}

        try:
            # Attempt 1: full payload
            resp = await client.update_campaign(campaign_id, changes)
            console.print(f"[dim]  API response for {campaign_name}: {resp}[/dim]")
            success = bool(resp.get("status") or resp.get("success"))

            # Attempt 2: empty pids (handles delisted products)
            if not success:
                resp = await client.update_campaign(campaign_id, changes, empty_pids=True)
                console.print(f"[dim]  API retry (empty pids) for {campaign_name}: {resp}[/dim]")
                success = bool(resp.get("status") or resp.get("success"))

            if not success:
                msgs = resp.get("message", [])
                msg_str = " | ".join(str(m) for m in msgs) if isinstance(msgs, list) else str(msgs)
                console.print(f"[yellow]  ⚠ {campaign_name}: {msg_str}[/yellow]")

        except Exception as exc:
            console.print(f"[red]  ✗ {campaign_name}: {exc}[/red]")
            success = False
            reason = f"{reason} [error: {exc}]"

        result = "[green]✓ done[/green]" if success else "[red]✗ failed[/red]"

        log_entries.append({
            "timestamp": now.strftime("%Y-%m-%d %H:%M IST"),
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "budget_applied": target_budget,
            "rule": reason,
            "success": success,
        })

        table.add_row(
            campaign_name,
            str(campaign_id),
            f"₹{target_budget:,.0f}",
            reason,
            result,
        )

    console.print(table)
    console.print("\n[dim]Browser closed.[/dim]")
    return log_entries


async def run_with_state(storage_state: dict, schedules: list[dict] | None = None) -> list[dict]:
    """Run scheduler with a pre-loaded storage state. Returns log entries."""
    from ad_campaigns.client import setup_with_state
    pw, browser, client = await setup_with_state(storage_state)
    try:
        now = datetime.now(_IST)  # capture AFTER browser setup so time is fresh
        return await _run_core(client, now, schedules=schedules)
    finally:
        await browser.close()
        await pw.stop()


async def run() -> None:
    pw, browser, client = await setup(TENANT_ID)
    try:
        now = datetime.now(_IST)  # capture AFTER browser setup so time is fresh
        await _run_core(client, now)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(run())
