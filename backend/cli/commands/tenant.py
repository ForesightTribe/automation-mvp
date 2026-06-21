import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.tenant import Tenant

app = typer.Typer(help="Manage tenants (clients).")
console = Console()


@app.command("create")
def create_tenant(
    name: str = typer.Option(..., "--name", "-n", help="Display name for the client"),
    account_id: str = typer.Option(..., "--account", "-a", help="Account UUID this client belongs to"),
):
    """Create a new client (tenant) under an account and print its UUID."""
    asyncio.run(_create_tenant(name, account_id))


async def _create_tenant(name: str, account_id: str) -> None:
    async with AsyncSessionLocal() as db:
        tenant = Tenant(name=name, account_id=uuid.UUID(account_id))
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        console.print(f"\n[green]Client created.[/green]")
        console.print(f"  [dim]name[/dim]     {tenant.name}")
        console.print(f"  [dim]account[/dim]  {tenant.account_id}")
        console.print(f"  [dim]id[/dim]       [bold]{tenant.id}[/bold]")
        console.print(f"\n[dim]Use this UUID with --tenant in all scrape and auth commands.[/dim]\n")


@app.command("list")
def list_tenants():
    """List all tenants."""
    asyncio.run(_list_tenants())


async def _list_tenants() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()

    if not rows:
        console.print("[dim]No tenants found. Run `cli tenant create` to add one.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Active")
    table.add_column("Created")
    for t in rows:
        table.add_row(
            str(t.id),
            t.name,
            "[green]yes[/green]" if t.is_active else "[red]no[/red]",
            t.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)
