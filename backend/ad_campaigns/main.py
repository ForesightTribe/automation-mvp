"""
Blinkit Ad Campaign Manager — terminal tool.
Run from backend/: python -m ad_campaigns.main
"""
import asyncio
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from ad_campaigns.client import setup
from ad_campaigns.schedules import load_schedules, save_schedules, load_log
from ad_campaigns import bid_scheduler
from ad_campaigns.bid_scheduler import _load_bid_schedules, _save_bid_schedules

console = Console()
TENANT_ID = "a870fd8d-7373-47ec-ad69-5dd08ce35542"
_IST = timezone(timedelta(hours=5, minutes=30))


def _status_color(status: str) -> str:
    return {
        "ACTIVE": "green",
        "STOPPED": "red",
        "ON_HOLD": "yellow",
        "PAUSED": "yellow",
    }.get(status.upper(), "white")


def _show_campaigns(campaigns: list[dict]):
    table = Table(
        title=f"Campaigns ({len(campaigns)} total)",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Name", max_width=42)
    table.add_column("Type", style="blue", width=22)
    table.add_column("Status", width=10)
    table.add_column("Budget Spent", justify="right", style="yellow")
    table.add_column("Impressions", justify="right")
    table.add_column("ROAS", justify="right", style="green")

    for i, c in enumerate(campaigns, 1):
        status = c.get("campaign_status", "")
        color = _status_color(status)
        table.add_row(
            str(i),
            str(c.get("id", "")),
            c.get("campaign_name", ""),
            c.get("campaign_type", ""),
            f"[{color}]{status}[/{color}]",
            f"₹{c.get('budget_consumed', 0):,.0f}",
            f"{c.get('impressions', 0):,}",
            str(c.get("roas", 0)),
        )
    console.print(table)


_DAY_ALIASES = {
    "mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
    "fri": "friday", "sat": "saturday", "sun": "sunday",
}
_VALID_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_VALID_SLOTS = {"morning", "afternoon", "evening", "night"}


def _parse_date(raw: str) -> str | None:
    """Accept 'today' or 'YYYY-MM-DD'. Returns 'YYYY-MM-DD' or None if invalid."""
    raw = raw.strip().lower()
    if raw == "today":
        return datetime.now(_IST).strftime("%Y-%m-%d")
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        return None


def _parse_days(raw: str) -> list[str]:
    out = []
    for part in raw.lower().replace(" ", "").split(","):
        day = _DAY_ALIASES.get(part, part)
        if day in _VALID_DAYS:
            out.append(day)
    return out


def _parse_slots(raw: str) -> list[str]:
    return [s for s in raw.lower().replace(" ", "").split(",") if s in _VALID_SLOTS]


def _show_schedules(schedules: list[dict]):
    if not schedules:
        console.print("[dim]No schedules configured yet.[/dim]")
        return
    table = Table(title="Budget Schedules", box=box.ROUNDED, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Campaign", max_width=36)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Default ₹", justify="right")
    table.add_column("Rules", max_width=52)
    for i, s in enumerate(schedules, 1):
        def _rule_text(r: dict) -> str:
            slots = "[blue]" + ", ".join(r.get("time_slots", [])) + "[/blue]"
            budget = f"[green]₹{r['budget']:,.0f}[/green]"
            if r.get("type") == "once":
                return f"[magenta]{r['date']}[/magenta] / {slots} → {budget}"
            days = "[yellow]" + ", ".join(r.get("days", [])) + "[/yellow]"
            return f"{days} / {slots} → {budget}"

        rules_text = "\n".join(_rule_text(r) for r in s.get("rules", [])) or "[dim]none[/dim]"
        table.add_row(
            str(i),
            s.get("campaign_name", ""),
            str(s.get("campaign_id", "")),
            f"₹{s.get('default_budget', 0):,.0f}",
            rules_text,
        )
    console.print(table)


def _show_bid_schedules(schedules: list[dict]):
    if not schedules:
        console.print("[dim]No bid schedules configured yet.[/dim]")
        return
    table = Table(title="Bid Schedules", box=box.ROUNDED, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Campaign", max_width=32)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Status", width=8)
    table.add_column("Keywords", max_width=56)
    for i, s in enumerate(schedules, 1):
        active_color = "green" if s.get("active", True) else "yellow"
        active_label = f"[{active_color}]{'ON' if s.get('active', True) else 'OFF'}[/{active_color}]"
        kw_lines = []
        for kw in s.get("keywords", []):
            slots_str = ",".join(kw.get("time_slots", [])) or "always"
            days_str = ",".join(kw.get("days", [])) or "daily"
            kw_lines.append(
                f"[bold]{kw['keyword']}[/bold] pos={kw['target_position']} "
                f"₹{kw['min_bid']}–{kw['max_bid']} step={kw.get('step',50)} "
                f"[dim]{slots_str} / {days_str}[/dim]"
            )
        table.add_row(str(i), s.get("campaign_name", ""), str(s.get("campaign_id", "")),
                      active_label, "\n".join(kw_lines) or "[dim]none[/dim]")
    console.print(table)


def _pick_campaign(campaigns: list[dict]) -> dict | None:
    campaign_id = Prompt.ask("Enter campaign ID")
    campaign = next((c for c in campaigns if str(c.get("id")) == campaign_id), None)
    if not campaign:
        console.print(f"[red]Campaign {campaign_id} not found in the list.[/red]")
    return campaign


async def main():
    console.print(Panel("[bold cyan]Blinkit Ad Campaign Manager[/bold cyan]", border_style="cyan"))
    console.print(f"[dim]Tenant: {TENANT_ID}[/dim]\n")

    console.print("[yellow]Loading session from DB and opening browser...[/yellow]")
    try:
        pw, browser, client = await setup(TENANT_ID)
        console.print("[green]✓ Authenticated[/green]\n")
    except Exception as e:
        console.print(f"[red]Auth failed: {e}[/red]")
        return

    campaigns: list[dict] = []

    try:
        while True:
            console.print("\n[bold]What do you want to do?[/bold]")
            console.print("  [cyan]1[/cyan] List all campaigns")
            console.print("  [cyan]2[/cyan] Rename a campaign")
            console.print("  [cyan]3[/cyan] Update daily budget")
            console.print("  [cyan]4[/cyan] Manage budget schedules")
            console.print("  [cyan]5[/cyan] View schedule history")
            console.print("  [cyan]6[/cyan] Manage bid schedules (rank-chasing)")
            console.print("  [cyan]7[/cyan] Run bid optimizer now")
            console.print("  [cyan]q[/cyan] Quit")

            choice = Prompt.ask("\nEnter choice")

            if choice == "q":
                break

            elif choice == "1":
                console.print("[yellow]Fetching campaigns...[/yellow]")
                campaigns = await client.get_campaigns()
                _show_campaigns(campaigns)

            elif choice == "2":
                if not campaigns:
                    console.print("[yellow]Fetching campaigns first...[/yellow]")
                    campaigns = await client.get_campaigns()
                    _show_campaigns(campaigns)

                campaign = _pick_campaign(campaigns)
                if not campaign:
                    continue

                current_name = campaign.get("campaign_name", "")
                console.print(f"Current name: [bold]{current_name}[/bold]")
                new_name = Prompt.ask("New name")

                if not new_name.strip():
                    console.print("[red]Name cannot be empty.[/red]")
                    continue

                if Confirm.ask(f"Rename to [bold cyan]{new_name}[/bold cyan]?"):
                    console.print("[yellow]Updating...[/yellow]")
                    try:
                        resp = await client.update_campaign(
                            int(campaign["id"]), {"name": new_name}
                        )
                        if resp.get("status") or resp.get("success"):
                            console.print("[green]✓ Campaign renamed successfully[/green]")
                            campaign["campaign_name"] = new_name
                        else:
                            console.print(f"[red]Update failed: {resp}[/red]")
                    except Exception as e:
                        console.print(f"[red]Error: {e}[/red]")

            elif choice == "3":
                if not campaigns:
                    console.print("[yellow]Fetching campaigns first...[/yellow]")
                    campaigns = await client.get_campaigns()
                    _show_campaigns(campaigns)

                campaign = _pick_campaign(campaigns)
                if not campaign:
                    continue

                console.print(f"Campaign: [bold]{campaign.get('campaign_name')}[/bold]")

                detail, _ = await client.get_campaign_detail(int(campaign["id"]))
                current_budget = detail.get("campaign_budget", 0)
                current_pacing = detail.get("pacing_type", "DAILY")
                console.print(f"Current daily budget: [bold]₹{current_budget:,.0f}[/bold]  Pacing: [bold]{current_pacing}[/bold]")

                new_budget = Prompt.ask("New daily budget (₹)")
                try:
                    new_budget_val = float(new_budget)
                except ValueError:
                    console.print("[red]Invalid amount.[/red]")
                    continue

                if Confirm.ask(f"Set daily budget to [bold cyan]₹{new_budget_val:,.0f}[/bold cyan]?"):
                    console.print("[yellow]Updating...[/yellow]")
                    try:
                        resp = await client.update_campaign(
                            int(campaign["id"]),
                            {
                                "bidding_strategy": {
                                    "total_budget": new_budget_val,
                                    "pacing_type": current_pacing,
                                }
                            },
                        )
                        if resp.get("status") or resp.get("success"):
                            console.print("[green]✓ Budget updated successfully[/green]")
                        else:
                            api_msg = resp.get("message", str(resp))
                            console.print(f"[yellow]API rejected ({api_msg}) — trying UI automation (~30s)...[/yellow]")
                            try:
                                resp = await client.update_campaign_budget_via_ui(
                                    int(campaign["id"]), new_budget_val
                                )
                                if resp.get("status") or resp.get("success"):
                                    console.print("[green]✓ Budget updated via UI automation[/green]")
                                else:
                                    console.print(f"[red]UI update failed: {resp}[/red]")
                            except Exception as ui_err:
                                console.print(f"[red]UI automation error: {ui_err}[/red]")
                                console.print("[dim]Check blinkit_step*.png screenshots in backend/ad_campaigns/[/dim]")
                    except Exception as e:
                        console.print(f"[red]Error: {e}[/red]")

            elif choice == "4":
                schedules = load_schedules()
                _show_schedules(schedules)

                console.print("\n  [cyan]a[/cyan] Add schedule")
                console.print("  [cyan]r[/cyan] Remove schedule")
                console.print("  [cyan]b[/cyan] Back")
                sub = Prompt.ask("\nEnter sub-choice")

                if sub == "b":
                    continue

                elif sub == "a":
                    if not campaigns:
                        console.print("[yellow]Fetching campaigns first...[/yellow]")
                        campaigns = await client.get_campaigns()
                        _show_campaigns(campaigns)

                    campaign = _pick_campaign(campaigns)
                    if not campaign:
                        continue

                    campaign_id = int(campaign["id"])
                    campaign_name = campaign.get("campaign_name", str(campaign_id))

                    existing = next((s for s in schedules if s["campaign_id"] == campaign_id), None)
                    if existing:
                        console.print(f"[yellow]Schedule already exists for {campaign_name}. Remove it first to re-add.[/yellow]")
                        continue

                    console.print(f"\nCampaign: [bold]{campaign_name}[/bold]")
                    raw_default = Prompt.ask("Default budget ₹ (used outside scheduled slots)")
                    try:
                        default_budget = float(raw_default)
                    except ValueError:
                        console.print("[red]Invalid amount.[/red]")
                        continue

                    rules: list[dict] = []
                    while Confirm.ask("\nAdd a rule?"):
                        console.print("  [cyan]r[/cyan] Recurring  (every week on specific days, e.g. every Saturday)")
                        console.print("  [cyan]o[/cyan] One-time   (specific date only, e.g. today evening)")
                        rule_type = Prompt.ask("Rule type")

                        if rule_type not in ("r", "o"):
                            console.print("[red]Enter r or o.[/red]")
                            continue

                        console.print("[dim]Slots: morning(6-12) afternoon(12-18) evening(18-22) night(22-6)[/dim]")
                        raw_slots = Prompt.ask("Time slots (comma separated, e.g. evening,night)")
                        slots = _parse_slots(raw_slots)
                        if not slots:
                            console.print("[red]No valid slots entered. Skipping rule.[/red]")
                            continue

                        if rule_type == "r":
                            console.print("[dim]Days: monday–sunday  (or mon/tue/wed/thu/fri/sat/sun)[/dim]")
                            raw_days = Prompt.ask("Days (comma separated, e.g. saturday,sunday)")
                            days = _parse_days(raw_days)
                            if not days:
                                console.print("[red]No valid days entered. Skipping rule.[/red]")
                                continue
                            label = f"{', '.join(days)} / {', '.join(slots)}"
                            raw_budget = Prompt.ask(f"Budget ₹ for {label}")
                            try:
                                rule_budget = float(raw_budget)
                            except ValueError:
                                console.print("[red]Invalid amount.[/red]")
                                continue
                            rules.append({"type": "recurring", "days": days, "time_slots": slots, "budget": rule_budget})

                        else:
                            raw_date = Prompt.ask("Date (YYYY-MM-DD or 'today')")
                            date_str = _parse_date(raw_date)
                            if not date_str:
                                console.print("[red]Invalid date. Use YYYY-MM-DD or 'today'.[/red]")
                                continue
                            label = f"{date_str} / {', '.join(slots)}"
                            raw_budget = Prompt.ask(f"Budget ₹ for {label}")
                            try:
                                rule_budget = float(raw_budget)
                            except ValueError:
                                console.print("[red]Invalid amount.[/red]")
                                continue
                            rules.append({"type": "once", "date": date_str, "time_slots": slots, "budget": rule_budget})

                        console.print(f"[green]✓ Rule added[/green]")

                    schedules.append({
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "default_budget": default_budget,
                        "rules": rules,
                    })
                    save_schedules(schedules)
                    console.print(f"\n[green]✓ Schedule saved for {campaign_name}[/green]")
                    console.print("[dim]Run: python -m ad_campaigns.scheduler  (or automate with Task Scheduler)[/dim]")

                elif sub == "r":
                    if not schedules:
                        console.print("[yellow]No schedules to remove.[/yellow]")
                        continue
                    _show_schedules(schedules)
                    raw_num = Prompt.ask("Enter # to remove")
                    try:
                        idx = int(raw_num) - 1
                        if not (0 <= idx < len(schedules)):
                            raise ValueError
                    except ValueError:
                        console.print("[red]Invalid number.[/red]")
                        continue
                    removed = schedules.pop(idx)
                    save_schedules(schedules)
                    console.print(f"[green]✓ Removed schedule for {removed.get('campaign_name')}[/green]")

                else:
                    console.print("[red]Invalid sub-choice.[/red]")

            elif choice == "5":
                log = load_log()
                if not log:
                    console.print("[dim]No scheduler runs recorded yet.[/dim]")
                    continue
                table = Table(title=f"Scheduler History ({len(log)} entries)", box=box.ROUNDED, show_lines=False)
                table.add_column("Time (IST)", style="dim", width=22)
                table.add_column("Campaign", max_width=36)
                table.add_column("Budget", justify="right", style="yellow")
                table.add_column("Rule", style="dim", max_width=40)
                table.add_column("Result", width=8)
                for entry in reversed(log[-50:]):
                    result = "[green]✓[/green]" if entry.get("success") else "[red]✗[/red]"
                    table.add_row(
                        entry.get("timestamp", ""),
                        entry.get("campaign_name", ""),
                        f"₹{entry.get('budget_applied', 0):,.0f}",
                        entry.get("rule", ""),
                        result,
                    )
                console.print(table)

            elif choice == "6":
                bid_schedules = _load_bid_schedules()
                _show_bid_schedules(bid_schedules)

                console.print("\n  [cyan]a[/cyan] Add bid schedule")
                console.print("  [cyan]r[/cyan] Remove bid schedule")
                console.print("  [cyan]t[/cyan] Toggle active/inactive")
                console.print("  [cyan]b[/cyan] Back")
                sub = Prompt.ask("\nEnter sub-choice")

                if sub == "b":
                    continue

                elif sub == "a":
                    if not campaigns:
                        console.print("[yellow]Fetching campaigns first...[/yellow]")
                        campaigns = await client.get_campaigns()
                        _show_campaigns(campaigns)

                    campaign = _pick_campaign(campaigns)
                    if not campaign:
                        continue

                    campaign_id = int(campaign["id"])
                    campaign_name = campaign.get("campaign_name", str(campaign_id))

                    existing = next((s for s in bid_schedules if s["campaign_id"] == campaign_id), None)
                    if existing:
                        console.print(f"[yellow]Bid schedule already exists for {campaign_name}.[/yellow]")
                        console.print("[dim]Remove it first, then re-add.[/dim]")
                        continue

                    console.print(f"\nCampaign: [bold]{campaign_name}[/bold]")
                    console.print("[dim]Fetching current keyword report...[/dim]")
                    try:
                        reports = await client.get_campaign_report(campaign_id, days=7)
                    except Exception as e:
                        console.print(f"[red]Failed to fetch report: {e}[/red]")
                        reports = []

                    if reports:
                        table = Table(title="Keywords (last 7 days)", box=box.SIMPLE)
                        table.add_column("Keyword", max_width=36)
                        table.add_column("Position", justify="right")
                        table.add_column("CPM ₹", justify="right")
                        table.add_column("Impressions", justify="right")
                        for r in reports:
                            table.add_row(
                                r.get("keyword", ""),
                                str(r.get("most_viewed_position", "-")),
                                f"₹{r.get('cpm', 0)}",
                                f"{r.get('impressions', 0):,}",
                            )
                        console.print(table)
                    else:
                        console.print("[dim]No keyword data available yet. You can still add rules manually.[/dim]")

                    keywords: list[dict] = []
                    while Confirm.ask("\nAdd a keyword bid rule?"):
                        kw_name = Prompt.ask("Keyword (exact text, e.g. mojito)")
                        if not kw_name.strip():
                            continue

                        try:
                            target_pos = int(Prompt.ask("Target position (1 = top, e.g. 1 or 3)"))
                            min_bid = int(Prompt.ask("Min bid ₹ (e.g. 500)"))
                            max_bid = int(Prompt.ask("Max bid ₹ (e.g. 900)"))
                            step = int(Prompt.ask("Step ₹ per cycle (e.g. 50)"))
                        except ValueError:
                            console.print("[red]Invalid number. Skipping.[/red]")
                            continue

                        if min_bid >= max_bid:
                            console.print("[red]Min bid must be less than max bid.[/red]")
                            continue

                        console.print("[dim]Slots: morning(6-12) afternoon(12-18) evening(18-22) night(22-6)[/dim]")
                        raw_slots = Prompt.ask("Active time slots (comma separated, leave blank = always)")
                        slots = _parse_slots(raw_slots) if raw_slots.strip() else []

                        console.print("[dim]Days: monday–sunday  (leave blank = every day)[/dim]")
                        raw_days = Prompt.ask("Active days (comma separated, leave blank = every day)")
                        days = _parse_days(raw_days) if raw_days.strip() else []

                        keywords.append({
                            "keyword": kw_name.strip(),
                            "match_type": "EXACT",
                            "target_position": target_pos,
                            "min_bid": min_bid,
                            "max_bid": max_bid,
                            "step": step,
                            "time_slots": slots,
                            "days": days,
                        })
                        console.print(f"[green]✓ Rule added for '{kw_name}'[/green]")

                    if not keywords:
                        console.print("[yellow]No keywords added. Cancelled.[/yellow]")
                        continue

                    bid_schedules.append({
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "active": True,
                        "keywords": keywords,
                    })
                    _save_bid_schedules(bid_schedules)
                    console.print(f"\n[green]✓ Bid schedule saved for {campaign_name}[/green]")
                    console.print("[dim]Run option 7 to execute, or: python -m ad_campaigns.bid_scheduler[/dim]")

                elif sub == "r":
                    if not bid_schedules:
                        console.print("[yellow]No bid schedules to remove.[/yellow]")
                        continue
                    raw_num = Prompt.ask("Enter # to remove")
                    try:
                        idx = int(raw_num) - 1
                        if not (0 <= idx < len(bid_schedules)):
                            raise ValueError
                    except ValueError:
                        console.print("[red]Invalid number.[/red]")
                        continue
                    removed = bid_schedules.pop(idx)
                    _save_bid_schedules(bid_schedules)
                    console.print(f"[green]✓ Removed bid schedule for {removed.get('campaign_name')}[/green]")

                elif sub == "t":
                    if not bid_schedules:
                        console.print("[yellow]No bid schedules.[/yellow]")
                        continue
                    raw_num = Prompt.ask("Enter # to toggle")
                    try:
                        idx = int(raw_num) - 1
                        if not (0 <= idx < len(bid_schedules)):
                            raise ValueError
                    except ValueError:
                        console.print("[red]Invalid number.[/red]")
                        continue
                    bid_schedules[idx]["active"] = not bid_schedules[idx].get("active", True)
                    state = "ACTIVE" if bid_schedules[idx]["active"] else "INACTIVE"
                    _save_bid_schedules(bid_schedules)
                    console.print(f"[green]✓ {bid_schedules[idx]['campaign_name']} → {state}[/green]")

                else:
                    console.print("[red]Invalid sub-choice.[/red]")

            elif choice == "7":
                console.print("[yellow]Running bid optimizer...[/yellow]")
                try:
                    entries = await bid_scheduler.run(client)
                    if not entries:
                        console.print("[dim]No active bid rules for current time slot.[/dim]")
                    else:
                        for e in entries:
                            color = "green" if e.get("success") else "red"
                            kw = e.get("keyword", "")
                            detail = e.get("action", e.get("detail", ""))
                            console.print(f"  [{color}]{e.get('campaign_name')}[/{color}]"
                                          f"[dim] {kw}[/dim] — {detail}")
                except Exception as e:
                    console.print(f"[red]Bid optimizer error: {e}[/red]")

            else:
                console.print("[red]Invalid choice.[/red]")

    finally:
        await browser.close()
        await pw.stop()
        console.print("\n[dim]Browser closed.[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
