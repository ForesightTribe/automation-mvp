import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table

from app.core.database import AsyncSessionLocal
from app.services import ad_automation_service

app = typer.Typer(help="Ad automation: rule engine + recommendation queue (Phase 1 — no live Blinkit writes).")
console = Console()


@app.command("rules")
def list_rules(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant (client) UUID"),
):
    """List a tenant's ad-automation rules."""
    asyncio.run(_list_rules(tenant_id))


async def _list_rules(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        rules = await ad_automation_service.list_rules(db, uuid.UUID(tenant_id))

    if not rules:
        console.print("[dim]No rules yet. Create one via the API or the Ad Automation page.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Active")
    table.add_column("Scope")
    table.add_column("Condition")
    table.add_column("Action")
    for r in rules:
        table.add_row(
            str(r.id),
            r.name,
            "yes" if r.is_active else "no",
            f"{r.scope_type}" + (f"={r.scope_value}" if r.scope_value else ""),
            f"{r.metric} {r.operator} {r.threshold} / {r.window_days}d",
            f"{r.action_type}" + (f" ({r.action_value})" if r.action_value is not None else ""),
        )
    console.print(table)


@app.command("evaluate")
def evaluate(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant (client) UUID"),
):
    """Run every active rule against current ad data and print new recommendations."""
    asyncio.run(_evaluate(tenant_id))


async def _evaluate(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        created = await ad_automation_service.evaluate_rules(db, uuid.UUID(tenant_id))
    console.print(f"[green]{created} new recommended action(s) created.[/green]")


@app.command("actions")
def list_actions(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant (client) UUID"),
    status: str = typer.Option(None, "--status", help="Filter: pending|approved|rejected|completed"),
):
    """List recommended actions for a tenant."""
    asyncio.run(_list_actions(tenant_id, status))


async def _list_actions(tenant_id: str, status: str | None) -> None:
    from app.dependencies import Pagination

    async with AsyncSessionLocal() as db:
        page = await ad_automation_service.list_actions(
            db,
            tenant_id=uuid.UUID(tenant_id),
            pagination=Pagination(page=1, limit=100),
            status=status,
        )

    if not page.items:
        console.print("[dim]No actions found.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Campaign")
    table.add_column("Status")
    table.add_column("Reasoning")
    table.add_column("Detected")
    for a in page.items:
        table.add_row(
            str(a.id),
            a.campaign_name or str(a.campaign_id),
            a.status,
            a.reasoning,
            a.detected_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
