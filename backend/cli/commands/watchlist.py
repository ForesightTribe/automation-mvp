import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.tenant import TenantWatchlist

app = typer.Typer(help="Inspect per-tenant watchlists (brands + keywords). (Edit via `cli sync`.)")
console = Console()


@app.command("list")
def list_watchlist(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant (client) UUID"),
):
    """List a tenant's watchlist entries."""
    asyncio.run(_list(tenant_id))


async def _list(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(TenantWatchlist)
            .where(TenantWatchlist.tenant_id == uuid.UUID(tenant_id))
            .order_by(TenantWatchlist.relationship, TenantWatchlist.brand_slug)
        )).scalars().all()

    if not rows:
        console.print("[dim]No watchlist entries. Populate via `cli sync`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Brand")
    table.add_column("Rel")
    table.add_column("Keywords")
    table.add_column("Aliases")
    for r in rows:
        table.add_row(r.brand_slug, r.relationship, ", ".join(r.keywords), ", ".join(r.aliases))
    console.print(table)
