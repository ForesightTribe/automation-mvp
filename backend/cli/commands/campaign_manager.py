"""CLI for Campaign Manager v2 — the `cm` group.

Every command is **DRY-RUN by default**; pass `--live` to actually touch Blinkit.
These are the same commands the scheduler runs via `jobs run cm.<type>` (the job's
`live` param maps to `--live`). Direct = dev/manual/debug; scheduler = production.
"""
import asyncio
import uuid

import typer
from rich.console import Console
from rich.markup import escape
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
    help="--live actually writes to the marketplace; --dry-run (default) computes + logs "
    "but writes nothing.",
)
# REQUIRED on every command, deliberately. With two marketplaces live, a default
# means a mistyped or forgotten flag silently drives the WRONG account — and these
# commands move real budget. Being made to say `-m blinkit` is cheap; discovering
# you paused Zepto campaigns when you meant Blinkit is not.
#
# The same rule binds the job layer (ZC-D1, 2026-09-24): jobs/types.py no longer fills in
# `blinkit` for a cm.* job without a marketplace — it refuses to build it. Every stored
# schedule already names one (the reconciler stamps it), and so does every job the API queues.
#
# `--platform` stays accepted as an alias so older scripts and muscle memory keep
# working; `--marketplace` matches the public scrape commands and is the name to use.
# Correlation id, so a run's rows in `cm_run_log` can be found from the job that started
# it. Normally supplied by the queue (jobs/queue.py mints one at enqueue for every
# correlated cm.* type); omitted — as it is whenever a human types the command — the run
# mints its own, exactly as it always has. Nothing about typing these commands changes.
_RUN_ID = typer.Option(
    None, "--run-id",
    help="Correlation id to file this run's history rows under. Defaults to a fresh one.",
)
_MARKETPLACE = typer.Option(
    ..., "--marketplace", "-m", "--platform",
    help="Which marketplace to drive: blinkit | zepto. Required — no default, "
    "because these commands write to real ad accounts.",
)


@app.command("budget-scheduler")
def budget_scheduler(tenant: str = _TENANT, live: bool = _LIVE,
                     marketplace: str = _MARKETPLACE, run_id: str = _RUN_ID):
    """Apply budget rules for the current IST slot (dry-run unless --live)."""
    from campaign_manager import budget
    asyncio.run(budget.run(uuid.UUID(tenant), dry_run=_dry(live), platform=marketplace,
                           run_id=run_id))


@app.command("bid-optimizer")
def bid_optimizer(
    tenant: str = _TENANT,
    live: bool = _LIVE,
    marketplace: str = _MARKETPLACE,
    run_id: str = _RUN_ID,
    reset: bool = typer.Option(
        False, "--reset",
        help="End-of-window mode: de-escalate closed-window keywords to their min_bid "
        "(no position scrape), instead of optimizing. The reconciler fires this at each "
        "window's stop time.",
    ),
):
    """Run one bid-optimizer pass (dry-run unless --live). `--reset` runs the end-of-window
    de-escalation instead of optimization."""
    from campaign_manager import bid
    asyncio.run(bid.run(uuid.UUID(tenant), dry_run=_dry(live), reset=reset,
                        platform=marketplace, run_id=run_id))


@app.command("reconcile")
def reconcile(tenant: str = _TENANT, live: bool = _LIVE,
              marketplace: str = _MARKETPLACE, run_id: str = _RUN_ID):
    """Compile a tenant's rules into job_schedules (dry-run unless --live)."""
    from campaign_manager import reconciler
    asyncio.run(reconciler.reconcile(uuid.UUID(tenant), dry_run=_dry(live),
                                     platform=marketplace, run_id=run_id))


@app.command("set-advertiser")
def set_advertiser(
    tenant: str = _TENANT,
    id: str = typer.Option(
        ..., "--id",
        help="The ad-account id. Blinkit: the integer advertiser_id (run `cm advertiser "
             "-m blinkit` to read it). Zepto: the brand UUID (`cm advertiser -m zepto`)."),
    platform: str = _MARKETPLACE,
):
    """Store a tenant's ad-account id.

    Two marketplaces, two meanings — the id's shape decides which column it lands in:

    
    * Blinkit — an INTEGER that live writes SEND, so a stale one spends real money on
      the wrong account. `cm advertiser -m blinkit` reads it: from the campaign list,
      else from the account's advertiser list when that holds exactly one advertiser.
      A login that sees several advertisers gets no answer — pick by name from the
      list it prints.
    * Zepto — a brand UUID that live writes CHECK. It arrives in the login response,
      so it is never sent; storing it lets us assert the session belongs to the
      account we expect before writing.
    """
    async def _run():
        await repo.set_advertiser(uuid.UUID(tenant), id, platform)
        sends = "send" if id.strip().isdigit() else "verify against"
        console.print(f"[green]Stored ad account {id}[/green] for tenant {tenant} "
                      f"({platform}). Live writes will {sends} it.")

    asyncio.run(_run())


@app.command("advertiser")
def advertiser(tenant: str = _TENANT, platform: str = _MARKETPLACE):
    """Show the ad account writes will use (STORED) vs. what the marketplace reports
    (DERIVED). Read-only — it opens a session to read the derived value.

    On Blinkit a difference is a warning: the derived value is often a stale hardcoded
    fallback, and the stored one is what writes actually send. On Zepto the derived
    value is authoritative (it comes from the login response) — so if nothing is
    stored yet, this is where you read the brand id to store."""
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
                # Zepto returns (None, None, client) — it needs no persistent browser.
                if browser is not None:
                    await browser.close()
                if pw is not None:
                    await pw.stop()
        except Exception as e:
            console.print(f"[yellow]couldn't read the marketplace-derived id: {e}[/yellow]")

        if stored is None:
            hint = derived if derived is not None else "<value>"
            console.print("[red]No stored ad account[/red] — live writes will refuse. "
                          f"Set it: [bold]cm set-advertiser -t {tenant} "
                          f"-m {platform} --id {hint}[/bold]")
        else:
            console.print(f"stored (writes will use) = [bold]{stored}[/bold]")
        armed = await repo.get_armed(uuid.UUID(tenant), platform)
        console.print("LIVE writes: " + ("[yellow]⚡ ARMED[/yellow]" if armed
                                          else "[dim]dry (disarmed)[/dim]"))
        if derived is not None:
            same = str(derived) == str(stored)
            flag = "" if same else (
                "  [yellow]← differs from stored[/yellow]"
                + ("" if platform != "blinkit" else " (likely a stale fallback)"))
            console.print(f"{platform}-derived{' ' * max(1, 18 - len(platform))}= {derived}{flag}")

    asyncio.run(_run())


@app.command("arm")
def arm(tenant: str = _TENANT, platform: str = _MARKETPLACE):
    """⚠️ CUTOVER: arm a tenant for LIVE writes. Requires an advertiser set. Reconciles
    immediately so the tenant's scheduled runs carry --live, and the API's set-budget/reset
    write for real. Reverse with `cm disarm`."""
    async def _run():
        tid = uuid.UUID(tenant)
        if await repo.get_advertiser(tid, platform) is None:
            console.print(f"[red]No advertiser set[/red] — set it first: "
                          f"[bold]cm set-advertiser -t {tenant} --id <n>[/bold]. Not armed.")
            raise typer.Exit(1)
        if not await repo.set_armed(tid, True, platform):
            console.print("[red]Could not arm (no platform account).[/red]"); raise typer.Exit(1)
        from campaign_manager import reconciler
        await reconciler.reconcile(tid, dry_run=False, platform=platform)
        console.print(f"[yellow]⚡ ARMED[/yellow] tenant {tenant} ({platform}) for LIVE writes — "
                      "scheduled runs + UI actions now write to Blinkit. "
                      f"Disarm: [bold]cm disarm -t {tenant}[/bold]")

    asyncio.run(_run())


@app.command("disarm")
def disarm(tenant: str = _TENANT, platform: str = _MARKETPLACE):
    """Disarm a tenant → back to DRY. Reconciles so the schedules drop --live."""
    async def _run():
        tid = uuid.UUID(tenant)
        await repo.set_armed(tid, False, platform)
        from campaign_manager import reconciler
        await reconciler.reconcile(tid, dry_run=False, platform=platform)
        console.print(f"[green]Disarmed[/green] tenant {tenant} ({platform}) — back to dry-run.")

    asyncio.run(_run())


@app.command("set-budget")
def set_budget(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    budget: float = typer.Option(..., "--budget", help="Daily budget (₹)"),
    marketplace: str = _MARKETPLACE,
    live: bool = _LIVE,
    run_id: str = _RUN_ID,
):
    """One-off: set a campaign's daily budget now (dry-run unless --live)."""
    from campaign_manager import set_budget as sb
    asyncio.run(sb.run(uuid.UUID(tenant), campaign, budget, dry_run=_dry(live),
                       platform=marketplace, run_id=run_id))


@app.command("set-bid")
def set_bid(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    keyword: str = typer.Option(..., "--keyword", help="The keyword to write"),
    cpm: int = typer.Option(..., "--cpm", help="Bid to set (₹). Raised to the "
                                               "marketplace's own floor if it is higher"),
    match_type: str = typer.Option("EXACT", "--match-type", help="EXACT | BROAD"),
    marketplace: str = _MARKETPLACE,
    live: bool = _LIVE,
    run_id: str = _RUN_ID,
):
    """One-off: set a single keyword's bid now (dry-run unless --live).

    This is what Reset and Delete-with-reset run: `--cpm` is the automation's `min_bid`.
    It takes plain values rather than a rule id because Delete removes the rule before this
    job gets to run. A keyword an ACTIVE, in-window automation is currently bidding on is
    left alone — flooring it would only start a fight the optimizer wins 15 minutes later.
    """
    from campaign_manager import bid
    asyncio.run(bid.set_bid(uuid.UUID(tenant), campaign_id=campaign, keyword=keyword,
                            cpm=cpm, match_type=match_type, platform=marketplace,
                            dry_run=_dry(live), run_id=run_id))


@app.command("set-activation")
def set_activation(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    status: str = typer.Option(..., "--status", help="running (start/resume) or paused (stop)"),
    marketplace: str = _MARKETPLACE,
    budget: float | None = typer.Option(
        None, "--budget",
        help="Daily budget (₹) to restart with. Resume only — Blinkit's RESTART sets the "
        "budget, so one is always sent; omit to reuse the campaign's current budget.",
    ),
    live: bool = _LIVE,
    run_id: str = _RUN_ID,
):
    """One-off: start or stop a campaign now (dry-run unless --live).

    Stopping is a cheap, bodiless call. **Starting re-submits the whole campaign** —
    budget, keywords, bids, pids and dates are all rewritten by Blinkit's RESTART, and the
    campaign's start date is reset to today. The run logs exactly what it will overwrite
    before it writes.
    """
    from campaign_manager import set_activation as sa
    asyncio.run(sa.run(uuid.UUID(tenant), campaign, status,
                       budget=budget, dry_run=_dry(live), platform=marketplace,
                       run_id=run_id))


@app.command("stop")
def stop(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    marketplace: str = _MARKETPLACE,
    live: bool = _LIVE,
):
    """Stop a campaign now (dry-run unless --live). Shorthand for `set-activation --status paused`.

    Cheap and safe: a single bodiless call. The campaign keeps its budget, keywords and
    bids while stopped, and `cm restart` brings it back.
    """
    from campaign_manager import set_activation as sa
    asyncio.run(sa.run(uuid.UUID(tenant), campaign, "paused", dry_run=_dry(live),
                       platform=marketplace))


@app.command("restart")
def restart(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    budget: float | None = typer.Option(
        None, "--budget", help="Daily budget (₹) to restart with; omit to reuse the current one."),
    marketplace: str = _MARKETPLACE,
    live: bool = _LIVE,
):
    """Restart a stopped campaign now (dry-run unless --live). Shorthand for
    `set-activation --status running`.

    ⚠️ Not a status flip — Blinkit's RESTART **re-submits the entire campaign**: budget,
    keywords, bids, pids and dates are all rewritten from a fresh read, and the campaign's
    start date is reset to today. The run logs exactly what it will overwrite first.
    """
    from campaign_manager import set_activation as sa
    asyncio.run(sa.run(uuid.UUID(tenant), campaign, "running", budget=budget,
                       dry_run=_dry(live), platform=marketplace))


@app.command("status")
def status(
    tenant: str = _TENANT,
    campaign: int = typer.Option(..., "--campaign", help="Campaign id"),
    platform: str = _MARKETPLACE,
):
    """Show a campaign's live state — status, budget, keyword bids, dates. READ ONLY.

    Never writes, whatever flags you pass. This is the read-back check to run either side
    of a `stop` / `restart`: a restart re-submits the whole campaign, so comparing before
    and after is how you confirm nothing was silently reverted.
    """
    from campaign_manager.marketplaces import get_adapter

    async def _run():
        adapter = get_adapter(platform)
        pw, browser, client = await adapter.setup(tenant)
        try:
            state, budget, detail = await adapter.read_campaign(client, campaign)
        finally:
            # Zepto returns (None, None, client) — it needs no persistent browser.
            # Closing unguarded crashed here before Zepto existed to expose it.
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()

        name = detail.get("name") or detail.get("campaign_name") or "?"
        t = Table(title=f"Campaign {campaign} — {name}  ({platform})")
        t.add_column("Field"); t.add_column("Value")
        t.add_row("status", f"[bold]{state}[/bold] ({detail.get('status')})")
        t.add_row("daily budget", f"₹{budget}" if budget is not None else "—")

        # Keyword bids come from the adapter, which both marketplaces implement —
        # the raw detail shapes differ completely.
        # Per match type where the marketplace bids that way (Zepto) — one keyword can
        # carry EXACT ₹10 and PHRASE ₹15, and the text-keyed view shows only one of them.
        by_match = getattr(adapter, "bids_by_match_from_detail", None)
        if by_match is not None:
            for (kw, match), bid in sorted((by_match(detail) or {}).items()):
                t.add_row(f"  bid · {kw} ({match})", f"₹{bid}")
        else:
            for kw, bid in (adapter.bids_from_detail(detail) or {}).items():
                t.add_row(f"  bid · {kw}", f"₹{bid}")

        if platform == "blinkit":
            from campaign_manager.marketplaces.blinkit import restart as restart_mod
            t.add_row("allowed next", str(detail.get("allowed_transitions") or "—"))
            # City targeting is THE field a whole-campaign PUT silently destroys (docs
            # §8.2b), so the read-back check has to show it — this command's whole purpose
            # is comparing a campaign either side of a write, and it used to omit the one
            # thing most worth comparing. Shown as Blinkit reports it, not as we'd send it.
            region_type = detail.get("region_type") or "—"
            region_ids = detail.get("region_ids")
            t.add_row("targeting", f"{region_type}"
                                   + (f" · {region_ids}" if region_ids else ""))
            t.add_row("pids", restart_mod.extract_pids(detail) or "—")
            t.add_row("start / end", f"{detail.get('start_ts')} → {detail.get('end_ts')}")
            t.add_row("infinite", str(detail.get("infinite_campaign")))
        else:
            cfg = detail.get("campaign_configs") or {}
            pids = [a.get("product_variant_id")
                    for a in (detail.get("ad_assets_pla") or [])]
            t.add_row("products", ", ".join(p for p in pids if p) or "—")
            t.add_row("targeting", f"city={cfg.get('city_targeting')} "
                                   f"bid={cfg.get('bid_targeting')} "
                                   f"product={cfg.get('product_targeting')}")
            t.add_row("start / end", f"{detail.get('start_date')} → "
                                     f"{detail.get('end_date') or '—'}")
        console.print(t)

    asyncio.run(_run())


@app.command("sync-campaigns")
def sync_campaigns(
    tenant: str = _TENANT,
    marketplace: str = _MARKETPLACE,
    days: int = typer.Option(
        None, "--days",
        help="Look-back window for the campaign list (default 90, floored at 30 — a "
        "narrow window would hide campaigns it didn't return from the pickers).",
    ),
):
    """Refresh the campaign catalogue (ids, names, statuses) from the live account.

    A READ — no --live flag, because it never writes to Blinkit. Cheap: one list call, not
    the full marketing scrape. Run it to pick up campaigns created since last night's
    scrape, or to see current statuses before starting / stopping something.
    """
    from campaign_manager import sync_campaigns as sync
    r = asyncio.run(sync.run(uuid.UUID(tenant), platform=marketplace,
                             days=days if days is not None else sync.DEFAULT_DAYS))
    if r["errors"]:
        console.print("[red]Sync failed — catalogue left unchanged. See the log above.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Catalogue refreshed — {r['applied']} campaigns.[/green]")


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
    campaign: int = typer.Option(..., "--campaign", help="Campaign id on the --marketplace given"),
    default_budget: float = typer.Option(..., "--default-budget", help="Fallback budget when no rule matches (₹)"),
    name: str = typer.Option(None, "--name", help="Human label"),
    campaign_name: str = typer.Option("", "--campaign-name", help="Campaign name (for logs/UI)"),
    platform: str = _MARKETPLACE,
    stop_after_window: bool = typer.Option(
        False, "--stop-after-window",
        help="Also STOP the campaign when a window ends (and restart it at the next "
        "window start). Off = budget only, campaign status never touched.",
    ),
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
        try:
            s = await repo.create_budget_schedule(
                uuid.UUID(tenant), platform, campaign, campaign_name or f"campaign {campaign}",
                default_budget, name, stop_after_window=stop_after_window,
            )
        except (repo.NotAutomatable, repo.DuplicateBidRule) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        except repo.DuplicateSchedule as e:
            console.print(f"[red]{e}[/red]")
            if e.schedule_id:
                console.print(f"  [bold]cm rules add-budget-rule --schedule {e.schedule_id} "
                              f"--budget <₹> --start-time HH:MM --end-time HH:MM[/bold]")
                console.print(f"  [dim]or replace it: cm rules remove-budget --schedule {e.schedule_id}[/dim]")
            raise typer.Exit(1)
        console.print(f"[green]Budget schedule #{s.id} created[/green] (campaign {campaign}, "
                      f"default ₹{default_budget:g}"
                      + (", stops after each window" if stop_after_window else "") + ")")
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
    campaign: int = typer.Option(..., "--campaign", help="Campaign id on the --marketplace given"),
    keyword: str = typer.Option(..., "--keyword", help="Search keyword to chase"),
    target: int = typer.Option(..., "--target", help="Target sponsored position (e.g. 3)"),
    min_bid: int = typer.Option(..., "--min-bid", help="Floor CPM (₹)"),
    max_bid: int = typer.Option(
        None, "--max-bid",
        help="Ceiling CPM (₹). Omit to chase the target position with no per-rule ceiling "
             "— the absolute backstop (CM_BID_MAX_ABSOLUTE) still applies."),
    campaign_name: str = typer.Option("", "--campaign-name"),
    match_type: str = typer.Option("EXACT", "--match-type", help="EXACT | BROAD"),
    start_time: str = typer.Option(None, "--start-time", help="Active-window start 'HH:MM' (IST; may cross midnight)"),
    stop_time: str = typer.Option(None, "--stop-time", help="Active-window end 'HH:MM' (IST; ≤ start = overnight)"),
    once: bool = typer.Option(False, "--once", help="Single-date span instead of a daily window (needs --date)"),
    date: str = typer.Option(None, "--date", help="'YYYY-MM-DD' for a --once span"),
    days: str = typer.Option(None, "--days", help="Recurring weekday filter, e.g. 'friday,saturday,sunday' (empty = every day)"),
    start_date: str = typer.Option(None, "--start-date", help="Recurring: first active day"),
    stop_date: str = typer.Option(None, "--stop-date", help="Recurring: last active day"),
    city: str = typer.Option(None, "--city", help="Measure in this city — at its frozen store (`cm stores`), which the rule keeps following; else the city's lowest merchant_id"),
    location_id: str = typer.Option(None, "--location-id", help="Pin to one specific store (merchant_id from `cli locations list`); ignores the city's frozen store"),
    lat: float = typer.Option(None, "--lat", help="Store latitude — manual override of --city/--location-id"),
    lon: float = typer.Option(None, "--lon", help="Store longitude — manual override"),
    location: str = typer.Option(None, "--location", help="Store label (for logs/UI)"),
    brand: str = typer.Option(None, "--brand", help="Brand name — fallback product match"),
    platform: str = _MARKETPLACE,
):
    """Create a keyword bid rule (recurring daily window, or a --once single-date span).

    Location (where position is measured) comes from `--lat/--lon`, or `--location-id`
    (a specific store), or `--city` (a representative store, auto-resolved from the
    darkstore catalog). Explicit `--lat/--lon` wins.
    """
    if once and not date:
        console.print("[red]--once needs --date[/red]"); raise typer.Exit(1)

    async def _run():
        rlat, rlon, rloc, rcity = lat, lon, location, None
        if (lat is None or lon is None) and (city or location_id):
            store = await repo.resolve_store(platform, city=city, location_id=location_id,
                                             tenant_id=uuid.UUID(tenant))
            if not store:
                what = f"location-id {location_id}" if location_id else f"city {city!r}"
                console.print(f"[red]no active {platform} store found for {what} "
                              f"(try `cli locations list --city …`)[/red]")
                raise typer.Exit(1)
            rlat, rlon = store.lat, store.lon
            rloc = location or store.label
            # --city → the rule follows the city's frozen store (`cm stores`) from now on;
            # --location-id → pinned to that one store.
            rcity = None if location_id else store.city_id
            follows = " · follows the city's frozen store" if rcity else " · pinned"
            console.print(f"[dim]measuring at {rloc} ({rlat}, {rlon}) — {store.source}"
                          f"{follows}[/dim]")

        try:
            r = await repo.create_bid_rule(
                uuid.UUID(tenant), platform, campaign, campaign_name or f"campaign {campaign}",
                keyword, target, min_bid, max_bid, match_type=match_type,
                type="once" if once else "recurring", date=date, days=_days(days),
                start_time=start_time, stop_time=stop_time, start_date=start_date,
                stop_date=stop_date, lat=rlat, lon=rlon, location_name=rloc, brand_name=brand,
                city_id=rcity,
            )
        except (repo.NotAutomatable, repo.DuplicateBidRule) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        if rlat is None and r.lat is not None:
            # The marketplace needs a store and none was given, so it was chosen from the
            # campaign's own targeting (ZC-C14) — say where, and never silently.
            console.print(f"[dim]no --city given → measuring at "
                          f"{r.location_name or 'the chosen store'} ({r.lat}, {r.lon}) "
                          f"· follows that city's frozen store[/dim]")
        shape = f"once {date}" if once else "recurring"
        band = f"{min_bid}–{max_bid}" if max_bid else f"{min_bid}+ (no ceiling)"
        console.print(f"[green]Bid rule {r.id} created[/green] — {keyword!r} → pos {target} "
                      f"[{band}] on campaign {campaign} ({shape})")
        console.print(_RECONCILE_HINT.format(t=tenant))

    asyncio.run(_run())


@rules_app.command("set-stop-after-window")
def set_stop_after_window(
    schedule: int = typer.Option(..., "--schedule", help="Budget schedule id (from `cm rules list`)"),
    on: bool = typer.Option(..., "--on/--off", help="Stop the campaign when a window ends?"),
):
    """Turn the stop-after-window behaviour on or off for an existing budget schedule.

    ON: at each window end the budget reverts to the default and the campaign is stopped;
    it restarts at the next window start. OFF: budget only — the campaign's status is
    never written (except that a stopped campaign is still restarted at a window start,
    which is unconditional).
    """
    async def _run():
        s = await repo.update_budget_schedule(schedule, {"stop_after_window": on})
        if not s:
            console.print(f"[red]No budget schedule #{schedule}[/red]"); raise typer.Exit(1)
        console.print(f"[green]Schedule #{schedule}[/green] stop_after_window = "
                      f"[bold]{'ON' if on else 'OFF'}[/bold]")
        console.print(_RECONCILE_HINT.format(t=s.tenant_id))

    asyncio.run(_run())


@rules_app.command("list")
def list_rules(tenant: str = _TENANT, platform: str = _MARKETPLACE):
    """List a tenant's budget schedules (+ rules) and bid rules."""
    async def _run():
        tid = uuid.UUID(tenant)
        # A listing shows everything — stopped, paused and ended included.
        schedules = await repo.get_budget_schedules(
            tid, platform, state=repo.ANY_STATE, calendar=repo.ANY_CALENDAR)
        bids = await repo.get_bid_rules(
            tid, platform, state=repo.ANY_STATE, calendar=repo.ANY_CALENDAR)

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
                          str(r.min_bid), str(r.max_bid) if r.max_bid else "none", win,
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


# ── Measurement stores ───────────────────────────────────────────────────────
# Which dark store each city's bid automations measure at: a GLOBAL default per city, and a
# per-client override. The engine resolves it on every run, so a change lands on the next
# tick. The global layer is CLI-only — it applies to every client.

stores_app = typer.Typer(help="Which dark store each city's bid automations measure at "
                              "(a global default per city, overridable per client).")
app.add_typer(stores_app, name="stores")

_CITY = typer.Option(..., "--city", help="City — canonical name/slug, the marketplace's name, "
                                         "or our catalog's city")
_STORE_TENANT = typer.Option(None, "--tenant", "-t", help="Client UUID — THIS client's override")
_GLOBAL = typer.Option(False, "--global",
                       help="The GLOBAL default, used by every client without an override")
_SOURCE_WORDS = {"tenant": "this client's override", "global": "the global default",
                 "catalog": "nothing frozen — the city's lowest merchant_id"}


def _scope(tenant: str | None, global_: bool) -> uuid.UUID | None:
    """Whose store this is. Deliberately no default: a forgotten `-t` must not silently move
    the store for every client."""
    if bool(tenant) == bool(global_):
        console.print("[red]Say whose store this is: --tenant <uuid> for one client, or "
                      "--global for every client without an override.[/red]")
        raise typer.Exit(1)
    return uuid.UUID(tenant) if tenant else None


async def _city_or_exit(platform: str, city: str):
    city_id = await repo.resolve_city_id(platform, city)
    if city_id is None:
        console.print(f"[red]No city {escape(city)!r} for {platform}[/red] — try a canonical "
                      f"name (`cli cities status`) or a catalog city (`cli locations list`).")
        raise typer.Exit(1)
    return await repo.get_city(city_id)


def _moved(n: int) -> str:
    return (f"{n} saved automation{'s' if n != 1 else ''} reset onto the new set" if n
            else "no saved automation affected")


@stores_app.command("list")
def stores_list(
    platform: str = _MARKETPLACE,
    tenant: str = typer.Option(None, "--tenant", "-t",
                               help="Only the global defaults + this client's overrides"),
):
    """Every frozen store: global defaults and client overrides."""
    async def _run():
        rows = await repo.list_city_stores(
            platform, tenant_ids=[uuid.UUID(tenant)] if tenant else None)
        if not rows:
            console.print(f"[dim]No frozen {platform} stores — every city measures at its "
                          f"lowest merchant_id, or wherever its automations were saved.[/dim]")
            return
        table = Table(show_header=True, header_style="bold", title=f"{platform} measurement stores")
        for col in ("city", "scope", "store", "merchant_id", "rank"):
            table.add_column(col)
        for cs, loc, city in rows:
            label = (escape(repo.store_label(loc)) if loc else "[red]not in catalog[/red]")
            if loc is not None and not loc.is_active:
                label += " [red](inactive — skipped)[/red]"
            table.add_row(city.name if city else str(cs.city_id),
                          "global" if cs.tenant_id is None else str(cs.tenant_id),
                          label, cs.merchant_id, str(cs.rank))
        console.print(table)

    asyncio.run(_run())


@stores_app.command("show")
def stores_show(
    city: str = _CITY,
    platform: str = _MARKETPLACE,
    tenant: str = typer.Option(None, "--tenant", "-t",
                               help="Resolve as this client, so its override applies"),
):
    """The stores a city measures at right now, and every store they could be."""
    async def _run():
        c = await _city_or_exit(platform, city)
        tid = uuid.UUID(tenant) if tenant else None
        current = (await repo.city_stores_for(platform, tid, [c.id])).get(c.id)
        frozen = {(cs.tenant_id, cs.merchant_id): cs.rank
                  for cs, _, _ in await repo.list_city_stores(
                      platform, tenant_ids=[tid] if tid else [], city_id=c.id)}
        if current:
            console.print(f"[bold]{c.name}[/bold] measures at {len(current)} "
                          f"store{'s' if len(current) != 1 else ''} — "
                          f"{_SOURCE_WORDS[current[0].source]}:")
            for s in current:
                role = "anchor" if s is current[0] else "validation"
                console.print(f"  rank {s.rank}  {escape(s.label)} ({s.merchant_id})  "
                              f"[dim]{role}[/dim]")
        else:
            fallback = await repo.resolve_store(platform, city=c.name, tenant_id=tid)
            if fallback:
                console.print(f"[bold]{c.name}[/bold] has no frozen stores — new automations are "
                              f"saved at {escape(fallback.label)} ({fallback.merchant_id}), "
                              f"{_SOURCE_WORDS['catalog']}")
            else:
                console.print(f"[yellow]{c.name} has no active {platform} store in the catalog.[/yellow]")
        table = Table(show_header=True, header_style="bold", title=f"{c.name} stores")
        for col in ("merchant_id", "store", "pincode", "frozen as"):
            table.add_column(col)
        for loc in await repo.city_store_candidates(platform, c.id):
            marks = []
            if (None, loc.merchant_id) in frozen:
                marks.append(f"global rank {frozen[(None, loc.merchant_id)]}")
            if tid and (tid, loc.merchant_id) in frozen:
                marks.append(f"client rank {frozen[(tid, loc.merchant_id)]}")
            table.add_row(loc.merchant_id, escape(repo.store_label(loc)), loc.pincode or "",
                          ", ".join(marks))
        console.print(table)

    asyncio.run(_run())


@stores_app.command("set")
def stores_set(
    city: str = _CITY,
    store: str = typer.Option(..., "--store", help="merchant_id (from `cm stores show --city …`)"),
    rank: int = typer.Option(1, "--rank",
                             help="1 = the anchor store; 2-3 = more stores. Blinkit aims for "
                                  "target at every ranked store where the campaign is in stock; "
                                  "Zepto measures at one at a time and moves down the ranks when "
                                  "that one can't sell it"),
    platform: str = _MARKETPLACE,
    tenant: str = _STORE_TENANT,
    global_: bool = _GLOBAL,
):
    """Put a store in a city's measurement set at a rank (next run onwards).

    A client's set replaces the global set as a whole, so a client with only rank 1 set
    measures at that one store — not at the global ranks 2-3."""
    scope = _scope(tenant, global_)

    async def _run():
        c = await _city_or_exit(platform, city)
        try:
            s, moved = await repo.set_city_store(platform, c.id, store, tenant_id=scope, rank=rank)
        except repo.StoreSetError as e:
            console.print(f"[red]{escape(str(e))}[/red]")
            raise typer.Exit(1)
        who = "every client without its own set" if scope is None else f"client {scope}"
        console.print(f"[green]{c.name}[/green] rank {rank} → {escape(s.label)} ({s.merchant_id}) "
                      f"for {who} · {_moved(moved)}")

    asyncio.run(_run())


@stores_app.command("clear")
def stores_clear(
    city: str = _CITY,
    rank: int = typer.Option(None, "--rank", help="Clear one rank; omit to clear the whole set"),
    platform: str = _MARKETPLACE,
    tenant: str = _STORE_TENANT,
    global_: bool = _GLOBAL,
):
    """Remove stores from a city's set — one rank, or the whole set. Clearing a client's whole
    set moves it onto the global set; clearing the global set leaves automations at the store
    they were last saved at."""
    scope = _scope(tenant, global_)

    async def _run():
        c = await _city_or_exit(platform, city)
        removed, moved = await repo.clear_city_store(platform, c.id, tenant_id=scope, rank=rank)
        who = "global set" if scope is None else f"set for client {scope}"
        what = f"rank {rank} of the {who}" if rank is not None else f"the {who}"
        if not removed:
            console.print(f"[yellow]Nothing to clear — no {what} for {c.name}.[/yellow]")
            return
        console.print(f"[green]Cleared {what} for {c.name}[/green] "
                      f"({removed} store{'s' if removed != 1 else ''}) · {_moved(moved)}")

    asyncio.run(_run())


@stores_app.command("stock")
def stores_stock(
    tenant: str = _TENANT,
    platform: str = _MARKETPLACE,
    products: bool = typer.Option(False, "--products", help="List every product and whether it is available"),
):
    """What the bid engine last learned about stock at each measurement store (read-only).

    The engine refreshes a store's stock at the start of a run when the cached read is older
    than CM_STOCK_MAX_AGE_MINUTES; this only shows the cache."""
    from app.utils.time import now_ist

    async def _run():
        rows = await repo.list_store_stock(uuid.UUID(tenant), platform)
        if not rows:
            console.print("[dim]No stock checked yet — the bid engine reads it per measurement "
                          "store at the start of a run, at most hourly.[/dim]")
            return
        now = now_ist()
        table = Table(show_header=True, header_style="bold", title=f"{platform} stock by store")
        for col in ("store", "checked", "age", "read", "available / listed"):
            table.add_column(col)
        for r in rows:
            items = r.products or []
            available = sum(1 for p in items if p.get("in_stock"))
            age = int((now - r.checked_at).total_seconds() // 60)
            table.add_row(r.merchant_id, r.checked_at.strftime("%d %b %H:%M"), f"{age} min",
                          "complete" if r.complete else "[yellow]partial[/yellow]",
                          f"{available} / {len(items)}")
        console.print(table)
        if products:
            for r in rows:
                console.print(f"\n[bold]{r.merchant_id}[/bold]")
                for p in sorted(r.products or [], key=lambda p: (not p.get("in_stock"), p.get("name") or "")):
                    mark = "[green]in stock[/green]" if p.get("in_stock") else "[red]sold out[/red]"
                    console.print(f"  {p.get('pid')}  {mark}  {escape(p.get('name') or '')}")

    asyncio.run(_run())
