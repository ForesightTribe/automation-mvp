"""CLI for Campaign Manager v2 — the `cm` group.

Every command is **DRY-RUN by default**; pass `--live` to actually touch Blinkit.
These are the same commands the scheduler runs via `jobs run cm.<type>` (the job's
`live` param maps to `--live`). Direct = dev/manual/debug; scheduler = production.
"""
import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table

from campaign_manager import config, repo

app = typer.Typer(
    help="Campaign Manager v2 — budget scheduler, bid optimizer, reconciler (dry-run by default)."
)
console = Console()


def _dry(live: bool) -> bool:
    """--live overrides the dry-run default; otherwise fall back to the config default."""
    return False if live else config.DRY_RUN_DEFAULT


_TENANT = typer.Option(..., "--tenant", "-t", help="Tenant UUID")
_LIVE = typer.Option(
    False, "--live/--dry-run",
    help="--live actually writes to Blinkit; --dry-run (default) computes + logs but writes nothing.",
)


@app.command("budget-scheduler")
def budget_scheduler(tenant: str = _TENANT, live: bool = _LIVE):
    """Apply budget rules for the current IST slot (dry-run unless --live)."""
    from campaign_manager import budget
    asyncio.run(budget.run(uuid.UUID(tenant), dry_run=_dry(live)))


@app.command("bid-optimizer")
def bid_optimizer(tenant: str = _TENANT, live: bool = _LIVE):
    """Run one bid-optimizer pass (dry-run unless --live)."""
    from campaign_manager import bid
    asyncio.run(bid.run(uuid.UUID(tenant), dry_run=_dry(live)))


@app.command("reconcile")
def reconcile(tenant: str = _TENANT, live: bool = _LIVE):
    """Compile a tenant's rules into job_schedules (dry-run unless --live)."""
    from campaign_manager import reconciler
    asyncio.run(reconciler.reconcile(uuid.UUID(tenant), dry_run=_dry(live)))


@app.command("set-advertiser")
def set_advertiser(
    tenant: str = _TENANT,
    id: int = typer.Option(..., "--id", help="Advertiser (ad-account) id — capture it from a Blinkit dashboard PUT payload"),
    platform: str = typer.Option("blinkit", "--platform"),
):
    """Store a tenant's advertiser account id (live writes send this). Capture it once from
    a real dashboard budget/bid PUT (DevTools → Network → the request body's advertiser_id)."""
    async def _run():
        await repo.set_advertiser(uuid.UUID(tenant), id, platform)
        console.print(f"[green]Stored advertiser {id}[/green] for tenant {tenant} ({platform}). "
                      "Live writes will now send it.")

    asyncio.run(_run())


@app.command("advertiser")
def advertiser(tenant: str = _TENANT, platform: str = typer.Option("blinkit", "--platform")):
    """Show the advertiser writes will use (the STORED value) vs. what Blinkit's code would
    derive (often a stale fallback). Read-only. Opens the session to read the derived value."""
    from campaign_manager.marketplaces import get_adapter

    async def _run():
        stored = await repo.get_advertiser(uuid.UUID(tenant), platform)
        a = get_adapter(platform)
        derived = None
        try:
            pw, browser, client = await a.setup(tenant)
            try:
                derived = await a.resolve_advertiser(client)
            finally:
                await browser.close()
                await pw.stop()
        except Exception as e:
            console.print(f"[yellow]couldn't read Blinkit-derived id: {e}[/yellow]")

        if stored is None:
            console.print("[red]No stored advertiser[/red] — live writes will refuse. "
                          f"Set it: [bold]cm set-advertiser -t {tenant} --id <n>[/bold]")
        else:
            console.print(f"stored (writes will use) = [bold]{stored}[/bold]")
        if derived is not None:
            flag = "" if derived == stored else "  [yellow]← differs from stored (likely a stale fallback)[/yellow]"
            console.print(f"Blinkit-derived            = {derived}{flag}")

    asyncio.run(_run())


@app.command("set-budget")
def set_budget(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    budget: float = typer.Option(..., "--budget", help="Daily budget (₹)"),
    live: bool = _LIVE,
):
    """One-off: set a campaign's daily budget now (dry-run unless --live). [V4]"""
    typer.echo(f"cm set-budget is a V4 stub (tenant={tenant} campaign={campaign} "
               f"budget={budget} dry_run={_dry(live)}).")


@app.command("sync-campaign-data")
def sync_campaign_data(tenant: str = _TENANT):
    """Refresh campaign_data_cache (keywords + products) for a tenant. [V-later]"""
    typer.echo(f"cm sync-campaign-data is a stub (tenant={tenant}).")


# ── Rules CRUD (`cm rules …`) — manage automations from the CLI ─────────────
# The rules are the source of truth; after editing, run `cm reconcile -t <id> --live`
# to compile them into job_schedules. (The V4 API will enqueue that for you.)

rules_app = typer.Typer(help="Create / list / remove CM rules (budget schedules + bid rules).")
app.add_typer(rules_app, name="rules")

_RECONCILE_HINT = "[dim]→ run `cm reconcile -t {t} --live` to sync schedules.[/dim]"


def _days(csv: str | None) -> list:
    return [d.strip().lower() for d in csv.split(",") if d.strip()] if csv else []


@rules_app.command("add-budget-schedule")
def add_budget_schedule(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Blinkit campaign id"),
    default_budget: float = typer.Option(..., "--default-budget", help="Fallback budget when no rule matches (₹)"),
    name: str = typer.Option(None, "--name", help="Human label"),
    campaign_name: str = typer.Option("", "--campaign-name", help="Campaign name (for logs/UI)"),
    platform: str = typer.Option("blinkit", "--platform"),
    # optional inline first rule
    budget: float = typer.Option(None, "--budget", help="If set, also create one rule with this budget (₹)"),
    start_time: str = typer.Option(None, "--start-time", help="Rule window start 'HH:MM' (IST)"),
    end_time: str = typer.Option(None, "--end-time", help="Rule window end 'HH:MM' (IST)"),
    days: str = typer.Option(None, "--days", help="Comma list e.g. 'monday,friday' (empty = every day)"),
    start_date: str = typer.Option(None, "--start-date", help="'YYYY-MM-DD'"),
    end_date: str = typer.Option(None, "--end-date", help="'YYYY-MM-DD' (expiry → reset one-shot)"),
    once: bool = typer.Option(False, "--once", help="Inline rule is a one-time rule (needs --date)"),
    date: str = typer.Option(None, "--date", help="'YYYY-MM-DD' for a --once inline rule"),
):
    """Create a budget schedule for a campaign, optionally with one inline rule."""
    if once and not date:
        console.print("[red]--once needs --date[/red]"); raise typer.Exit(1)

    async def _run():
        s = await repo.create_budget_schedule(
            uuid.UUID(tenant), platform, campaign, campaign_name or f"campaign {campaign}",
            default_budget, name,
        )
        console.print(f"[green]Budget schedule #{s.id} created[/green] (campaign {campaign}, "
                      f"default ₹{default_budget:g})")
        if budget is not None:
            r = await repo.add_budget_rule(
                s.id, budget=budget, type="once" if once else "recurring", days=_days(days),
                start_time=start_time, end_time=end_time, start_date=start_date,
                end_date=end_date, date=date,
            )
            console.print(f"  [green]+ rule #{r.id}[/green] ₹{budget:g} "
                          f"({'once ' + str(date) if once else 'recurring'} {start_time or ''}–{end_time or ''})")
        console.print(_RECONCILE_HINT.format(t=tenant))

    asyncio.run(_run())


@rules_app.command("add-budget-rule")
def add_budget_rule(
    schedule: int = typer.Option(..., "--schedule", help="Budget schedule id (from `cm rules list`)"),
    budget: float = typer.Option(..., "--budget", help="Budget this rule applies (₹)"),
    once: bool = typer.Option(False, "--once", help="One-time rule (needs --date)"),
    start_time: str = typer.Option(None, "--start-time", help="'HH:MM' (IST)"),
    end_time: str = typer.Option(None, "--end-time", help="'HH:MM' (IST)"),
    days: str = typer.Option(None, "--days", help="Comma list e.g. 'monday,friday'"),
    start_date: str = typer.Option(None, "--start-date"),
    end_date: str = typer.Option(None, "--end-date"),
    date: str = typer.Option(None, "--date", help="'YYYY-MM-DD' for a --once rule"),
):
    """Add a rule to an existing budget schedule."""
    if once and not date:
        console.print("[red]--once needs --date[/red]"); raise typer.Exit(1)

    async def _run():
        r = await repo.add_budget_rule(
            schedule, budget=budget, type="once" if once else "recurring", days=_days(days),
            start_time=start_time, end_time=end_time, start_date=start_date,
            end_date=end_date, date=date,
        )
        console.print(f"[green]Rule #{r.id} added[/green] to schedule #{schedule} — ₹{budget:g}")

    asyncio.run(_run())


@rules_app.command("add-bid")
def add_bid(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Blinkit campaign id"),
    keyword: str = typer.Option(..., "--keyword", help="Search keyword to chase"),
    target: int = typer.Option(..., "--target", help="Target sponsored position (e.g. 3)"),
    min_bid: int = typer.Option(..., "--min-bid", help="Floor CPM (₹)"),
    max_bid: int = typer.Option(..., "--max-bid", help="Ceiling CPM (₹)"),
    campaign_name: str = typer.Option("", "--campaign-name"),
    match_type: str = typer.Option("EXACT", "--match-type", help="EXACT | BROAD"),
    start_time: str = typer.Option(None, "--start-time", help="Active-window start 'HH:MM' (IST; may cross midnight)"),
    stop_time: str = typer.Option(None, "--stop-time", help="Active-window end 'HH:MM' (IST; ≤ start = overnight)"),
    once: bool = typer.Option(False, "--once", help="Single-date span instead of a daily window (needs --date)"),
    date: str = typer.Option(None, "--date", help="'YYYY-MM-DD' for a --once span"),
    days: str = typer.Option(None, "--days", help="Recurring weekday filter, e.g. 'friday,saturday,sunday' (empty = every day)"),
    start_date: str = typer.Option(None, "--start-date", help="Recurring: first active day"),
    stop_date: str = typer.Option(None, "--stop-date", help="Recurring: last active day"),
    city: str = typer.Option(None, "--city", help="Measure position at a representative store in this city (auto lat/lon from the catalog)"),
    location_id: str = typer.Option(None, "--location-id", help="Measure at a specific store (merchant_id from `cli locations list`)"),
    lat: float = typer.Option(None, "--lat", help="Store latitude — manual override of --city/--location-id"),
    lon: float = typer.Option(None, "--lon", help="Store longitude — manual override"),
    location: str = typer.Option(None, "--location", help="Store label (for logs/UI)"),
    brand: str = typer.Option(None, "--brand", help="Brand name — fallback product match"),
    platform: str = typer.Option("blinkit", "--platform"),
):
    """Create a keyword bid rule (recurring daily window, or a --once single-date span).

    Location (where position is measured) comes from `--lat/--lon`, or `--location-id`
    (a specific store), or `--city` (a representative store, auto-resolved from the
    darkstore catalog). Explicit `--lat/--lon` wins.
    """
    if once and not date:
        console.print("[red]--once needs --date[/red]"); raise typer.Exit(1)

    async def _run():
        rlat, rlon, rloc = lat, lon, location
        if (lat is None or lon is None) and (city or location_id):
            store = await repo.resolve_store(platform, city=city, location_id=location_id)
            if not store:
                what = f"location-id {location_id}" if location_id else f"city {city!r}"
                console.print(f"[red]no active {platform} store found for {what} "
                              f"(try `cli locations list --city …`)[/red]")
                raise typer.Exit(1)
            rlat, rlon, catalog_label = store
            rloc = location or catalog_label
            console.print(f"[dim]measuring at {rloc} ({rlat}, {rlon})[/dim]")

        r = await repo.create_bid_rule(
            uuid.UUID(tenant), platform, campaign, campaign_name or f"campaign {campaign}",
            keyword, target, min_bid, max_bid, match_type=match_type,
            type="once" if once else "recurring", date=date, days=_days(days),
            start_time=start_time, stop_time=stop_time, start_date=start_date,
            stop_date=stop_date, lat=rlat, lon=rlon, location_name=rloc, brand_name=brand,
        )
        shape = f"once {date}" if once else "recurring"
        console.print(f"[green]Bid rule {r.id} created[/green] — {keyword!r} → pos {target} "
                      f"[{min_bid}–{max_bid}] on campaign {campaign} ({shape})")
        console.print(_RECONCILE_HINT.format(t=tenant))

    asyncio.run(_run())


@rules_app.command("list")
def list_rules(tenant: str = _TENANT, platform: str = typer.Option("blinkit", "--platform")):
    """List a tenant's budget schedules (+ rules) and bid rules."""
    async def _run():
        tid = uuid.UUID(tenant)
        schedules = await repo.get_budget_schedules(tid, platform)
        bids = await repo.get_bid_rules(tid, platform)

        if not schedules:
            console.print("[dim]No budget schedules.[/dim]")
        for s, rules in schedules:
            state = "[green]on[/green]" if s.enabled else "[red]off[/red]"
            console.print(f"\n[bold]Budget schedule #{s.id}[/bold] · campaign {s.campaign_id} "
                          f"({s.campaign_name}) · default ₹{s.default_budget:g} · {state}")
            if not rules:
                console.print("  [dim](no rules — always default)[/dim]")
            for r in rules:
                when = (f"once {r.date}" if r.type == "once"
                        else (", ".join(r.days) or "every day"))
                window = f"{r.start_time or '00:00'}–{r.end_time or '23:59'}"
                dates = f" [{r.start_date or ''}…{r.end_date or ''}]" if (r.start_date or r.end_date) else ""
                console.print(f"    rule #{r.id}: ₹{r.budget:g} · {when} · {window}{dates}")

        console.print()
        if not bids:
            console.print("[dim]No bid rules.[/dim]")
            return
        table = Table(show_header=True, header_style="bold", title="Bid rules")
        for col in ("rule id", "campaign", "keyword", "target", "min", "max", "window", "last pos", "last cpm"):
            table.add_column(col)
        for r, rt in bids:
            win = f"{r.start_time or '—'}–{r.stop_time or '—'}"
            table.add_row(r.id, str(r.campaign_id), r.keyword, str(r.target_position),
                          str(r.min_bid), str(r.max_bid), win,
                          f"{rt.last_position:g}" if rt and rt.last_position is not None else "—",
                          str(rt.last_cpm) if rt and rt.last_cpm is not None else "—")
        console.print(table)

    asyncio.run(_run())


@rules_app.command("remove-budget-rule")
def remove_budget_rule(rule: int = typer.Option(..., "--rule", help="Budget rule id (from `cm rules list`)")):
    """Delete ONE budget rule, keeping its schedule — the clean way to revert a bump
    (the schedule's default budget then applies on the next run)."""
    async def _run():
        ok = await repo.delete_budget_rule(rule)
        console.print(f"[green]Removed budget rule #{rule}[/green]" if ok
                      else f"[red]No budget rule #{rule}[/red]")

    asyncio.run(_run())


@rules_app.command("remove-budget")
def remove_budget(schedule: int = typer.Option(..., "--schedule", help="Budget schedule id")):
    """Delete a budget schedule and all its rules."""
    async def _run():
        ok = await repo.delete_budget_schedule(schedule)
        console.print(f"[green]Removed budget schedule #{schedule}[/green]" if ok
                      else f"[red]No budget schedule #{schedule}[/red]")

    asyncio.run(_run())


@rules_app.command("remove-bid")
def remove_bid(rule: str = typer.Option(..., "--rule", help="Bid rule id (full hex from `cm rules list`)")):
    """Delete a bid rule (and its runtime row)."""
    async def _run():
        ok = await repo.delete_bid_rule(rule)
        console.print(f"[green]Removed bid rule {rule}[/green]" if ok
                      else f"[red]No bid rule {rule}[/red]")

    asyncio.run(_run())
