"""CLI commands for ad automation: budget scheduler and bid optimizer."""
import asyncio
from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console

app = typer.Typer(help="Ad automation commands (budget scheduler, bid optimizer).")
console = Console()

_IST = timezone(timedelta(hours=5, minutes=30))


@app.command("budget-scheduler")
def budget_scheduler(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant UUID"),
):
    """Apply budget rules for the current IST time slot (runs as ads.budget_scheduler job)."""
    asyncio.run(_run_budget(tenant_id))


async def _run_budget(tenant_id: str) -> None:
    from ad_campaigns.client import setup
    from ad_campaigns.scheduler import _run_core

    now = datetime.now(_IST)
    pw, browser, client = await setup(tenant_id)
    try:
        await _run_core(client, now)
    finally:
        await browser.close()
        await pw.stop()


@app.command("bid-optimizer")
def bid_optimizer(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant UUID"),
):
    """Run one pass of the bid optimizer (runs as ads.bid_optimizer job)."""
    asyncio.run(_run_optimizer(tenant_id))


async def _run_optimizer(tenant_id: str) -> None:
    from ad_campaigns.bid_optimizer import run as _optimize
    from ad_campaigns.client import setup

    pw, browser, client = await setup(tenant_id)
    try:
        await _optimize(client)
    finally:
        await browser.close()
        await pw.stop()
