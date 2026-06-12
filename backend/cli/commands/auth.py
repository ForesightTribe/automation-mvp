import asyncio
import typer
from rich.console import Console
from app.core.database import connect_db, close_db, get_db
from scraper.utils.session import save_session, session_exists
from scraper.platforms.blinkit.auth import login
from scraper.platforms.blinkit.dashboard_data.marketing.endpoints import BASE_URL as BLINKIT_MARKETING_URL
from scraper.platforms.blinkit.dashboard_data.seller.auth import login as seller_login

app = typer.Typer(help="Manage platform login sessions.")
console = Console()


@app.command("blinkit")
def blinkit_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Log in to Blinkit and save the session to MongoDB."""
    asyncio.run(_blinkit_login(tenant_id))


async def _blinkit_login(tenant_id: str) -> None:
    await connect_db()
    db = get_db()
    try:
        if await session_exists(db, tenant_id, "blinkit"):
            overwrite = typer.confirm("A session already exists for this tenant. Overwrite?")
            if not overwrite:
                raise typer.Exit()

        email = typer.prompt("Blinkit email")
        console.print("\n[yellow]Browser opening — enter your email, then paste the magic link when prompted.[/yellow]\n")
        storage_state = await login(email, BLINKIT_MARKETING_URL)

        await save_session(db, tenant_id, "blinkit", storage_state)
        console.print("[green]Login successful. Session saved.[/green]")
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        raise typer.Exit(1)
    finally:
        await close_db()


@app.command("blinkit-seller")
def blinkit_seller_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Log in to Blinkit Seller (partnersbiz.com) via OTP and save the session."""
    asyncio.run(_blinkit_seller_login(tenant_id))


async def _blinkit_seller_login(tenant_id: str) -> None:
    await connect_db()
    db = get_db()
    try:
        if await session_exists(db, tenant_id, "blinkit_seller"):
            overwrite = typer.confirm("A session already exists for this tenant. Overwrite?")
            if not overwrite:
                raise typer.Exit()

        email = typer.prompt("Seller dashboard email")
        console.print("\n[yellow]Browser opening — enter your email, then enter the OTP when prompted.[/yellow]\n")
        storage_state = await seller_login(email)

        await save_session(db, tenant_id, "blinkit_seller", storage_state)
        console.print("[green]Login successful. Session saved.[/green]")
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        raise typer.Exit(1)
    finally:
        await close_db()


@app.command("status")
def auth_status(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Check whether a saved session exists for a tenant."""
    asyncio.run(_auth_status(tenant_id))


async def _auth_status(tenant_id: str) -> None:
    await connect_db()
    db = get_db()
    try:
        exists = await session_exists(db, tenant_id, "blinkit")
        if exists:
            console.print(f"[green]Session exists[/green]: tenant={tenant_id} platform=blinkit")
        else:
            console.print(f"[yellow]No session found[/yellow]: tenant={tenant_id} platform=blinkit")
    finally:
        await close_db()
