"""CLI for Campaign Manager v2 — the `cm` group.

Every command is **DRY-RUN by default**; pass `--live` to actually touch Blinkit.
These are the same commands the scheduler runs via `jobs run cm.<type>` (the job's
`live` param maps to `--live`). Direct = dev/manual/debug; scheduler = production.
"""
import asyncio
import uuid

import typer

from campaign_manager import config

app = typer.Typer(
    help="Campaign Manager v2 — budget scheduler, bid optimizer, reconciler (dry-run by default)."
)


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
