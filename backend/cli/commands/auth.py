import asyncio
import typer
from rich.console import Console
from sqlmodel import select
from app.core.database import AsyncSessionLocal
from app.models.job import PlatformSession
from scraper.utils.session import save_session, session_exists, load_session, record_validation
from scraper.platforms.blinkit.auth import login
from scraper.platforms.blinkit.dashboard_data.marketing.endpoints import BASE_URL as BLINKIT_MARKETING_URL
from scraper.platforms.blinkit.dashboard_data.seller.auth import login as seller_login
from scraper.platforms.zepto.dashboard_data.seller.auth import login as zepto_seller_login
from scraper.platforms.zepto.dashboard_data.seller.scraper import validate as zepto_seller_validate

# Platforms with a browser-free health-check implemented. Others (e.g.
# blinkit_seller) don't have one yet — add here as they're built.
_VALIDATORS = {
    "zepto_seller": zepto_seller_validate,
}

app = typer.Typer(help="Manage platform login sessions.")
console = Console()


@app.command("blinkit")
def blinkit_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Log in to Blinkit and save the session."""
    asyncio.run(_blinkit_login(tenant_id))


async def _blinkit_login(tenant_id: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            if await session_exists(session, tenant_id, "blinkit"):
                overwrite = typer.confirm("A session already exists for this tenant. Overwrite?")
                if not overwrite:
                    raise typer.Exit()

            email = typer.prompt("Blinkit email")
            console.print("\n[yellow]Browser opening — enter your email, then paste the magic link when prompted.[/yellow]\n")
            storage_state = await login(email, BLINKIT_MARKETING_URL)

            await save_session(session, tenant_id, "blinkit", storage_state)
            console.print("[green]Login successful. Session saved.[/green]")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@app.command("blinkit-seller")
def blinkit_seller_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Log in to Blinkit Seller (partnersbiz.com) via OTP and save the session."""
    asyncio.run(_blinkit_seller_login(tenant_id))


async def _blinkit_seller_login(tenant_id: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            if await session_exists(session, tenant_id, "blinkit_seller"):
                overwrite = typer.confirm("A session already exists for this tenant. Overwrite?")
                if not overwrite:
                    raise typer.Exit()

            email = typer.prompt("Seller dashboard email")
            console.print("\n[yellow]Browser opening — enter your email, then enter the OTP when prompted.[/yellow]\n")
            storage_state = await seller_login(email)

            await save_session(session, tenant_id, "blinkit_seller", storage_state)
            console.print("[green]Login successful. Session saved.[/green]")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@app.command("zepto-seller")
def zepto_seller_login_cmd(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Log in to Zepto Seller via email + password + OTP and save the session."""
    asyncio.run(_zepto_seller_login(tenant_id))


async def _zepto_seller_login(tenant_id: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            if await session_exists(session, tenant_id, "zepto_seller"):
                overwrite = typer.confirm("A session already exists for this tenant. Overwrite?")
                if not overwrite:
                    raise typer.Exit()

            email = typer.prompt("Zepto seller email")
            password = typer.prompt("Zepto seller password", hide_input=True)
            console.print("\n[yellow]Browser opening — enter your OTP when prompted.[/yellow]\n")
            storage_state = await zepto_seller_login(email, password)

            await save_session(session, tenant_id, "zepto_seller", storage_state)
            console.print("[green]Login successful. Session saved.[/green]")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@app.command("status")
def auth_status(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
):
    """Check whether a saved session exists for a tenant, and its last-known health."""
    asyncio.run(_auth_status(tenant_id))


_STATUS_COLOR = {"healthy": "green", "degraded": "yellow", "dead": "red", "unknown": "dim"}


async def _auth_status(tenant_id: str) -> None:
    async with AsyncSessionLocal() as session:
        for platform in ("blinkit", "blinkit_seller", "zepto_seller"):
            record = (
                await session.execute(
                    select(PlatformSession).where(
                        PlatformSession.tenant_id == tenant_id, PlatformSession.platform == platform
                    )
                )
            ).scalars().first()

            if not record:
                console.print(f"[yellow]No session[/yellow]: tenant={tenant_id} platform={platform}")
                continue

            color = _STATUS_COLOR.get(record.status, "white")
            console.print(
                f"[green]Session exists[/green]: tenant={tenant_id} platform={platform} "
                f"status=[{color}]{record.status}[/{color}] "
                f"last_validated={record.last_validated_at or 'never'} "
                f"consecutive_failures={record.consecutive_failures}"
            )


@app.command("validate")
def auth_validate(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    platform: str = typer.Option(..., "--platform", "-p", help="Platform, e.g. zepto_seller"),
):
    """Check whether a saved session is still accepted by the platform — a single,
    browser-free HTTP request, safe to run before a real scrape without adding
    extra bot-detection exposure."""
    asyncio.run(_auth_validate(tenant_id, platform))


async def _auth_validate(tenant_id: str, platform: str) -> None:
    validator = _VALIDATORS.get(platform)
    if not validator:
        console.print(
            f"[red]No validator implemented for platform={platform}[/red] "
            f"(available: {', '.join(_VALIDATORS)})"
        )
        raise typer.Exit(1)

    async with AsyncSessionLocal() as session:
        storage_state = await load_session(session, tenant_id, platform)
        if not storage_state:
            console.print(f"[red]No saved session[/red]: tenant={tenant_id} platform={platform}")
            raise typer.Exit(1)

        ok, error = await validator(storage_state)
        status = await record_validation(session, tenant_id, platform, ok, error)

    color = _STATUS_COLOR.get(status, "white")
    if ok:
        console.print(f"[green]Valid[/green]: tenant={tenant_id} platform={platform} status=[{color}]{status}[/{color}]")
    else:
        console.print(f"[red]Invalid[/red]: tenant={tenant_id} platform={platform} status=[{color}]{status}[/{color}] error={error}")
