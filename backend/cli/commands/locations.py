import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.search import MarketplaceLocation, TenantLocation

app = typer.Typer(help="Inspect the Blinkit location catalog and tenant coverage. (Edit via `cli sync`.)")
console = Console()
MP = "blinkit"


@app.command("list")
def list_locations(
    city: str = typer.Option(None, "--city", "-c", help="Filter catalog by city slug"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Show this tenant's covered locations instead"),
):
    """List catalog locations, or a tenant's covered locations with --tenant."""
    asyncio.run(_list(city, tenant_id))


async def _list(city: str | None, tenant_id: str | None) -> None:
    async with AsyncSessionLocal() as db:
        if tenant_id:
            q = (
                select(MarketplaceLocation)
                .join(TenantLocation, TenantLocation.location_id == MarketplaceLocation.id)
                .where(TenantLocation.tenant_id == uuid.UUID(tenant_id),
                       MarketplaceLocation.mp_slug == MP)
            )
        else:
            q = select(MarketplaceLocation).where(MarketplaceLocation.mp_slug == MP)
            if city:
                q = q.where(MarketplaceLocation.city == city)
        rows = (await db.execute(
            q.order_by(MarketplaceLocation.city, MarketplaceLocation.zone)
        )).scalars().all()

    if not rows:
        hint = "this tenant has no coverage" if tenant_id else "catalog empty"
        console.print(f"[dim]No locations ({hint}). Populate via `cli sync`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold",
                  title=f"{'Tenant coverage' if tenant_id else 'Catalog'} — {len(rows)} locations")
    table.add_column("ID")
    table.add_column("City")
    table.add_column("Zone")
    table.add_column("Pincode")
    table.add_column("Active")
    for r in rows:
        table.add_row(str(r.id), r.city, r.zone, r.pincode,
                      "[green]yes[/green]" if r.is_active else "[red]no[/red]")
    console.print(table)
