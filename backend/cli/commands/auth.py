"""Platform login commands.

Generic over the registry rather than one command per dashboard — adding Zepto
adds no code here. The old `auth blinkit` / `auth blinkit-seller` commands are
kept as aliases so existing runbooks and muscle memory still work.
"""
import asyncio

import typer
from rich.console import Console
from rich.table import Table

from app.core.database import AsyncSessionLocal
from platform_auth import mail_rules, service, store
from platform_auth.registry import AUTHENTICATORS, get as get_authenticator, wired_slugs
from platform_auth.types import Credentials

# Zepto is deliberately outside platform_auth for now (registry lists it
# wired=False): its sign-in is a browser flow, not the HTTP flows that package
# models. So its login and probe are wired up separately, below.
from scraper.utils.session import save_session, session_exists, load_session
from scraper.platforms.zepto.dashboard_data.seller.auth import login as zepto_seller_login
from scraper.platforms.zepto.dashboard_data.seller.scraper import validate as zepto_seller_validate

# Platforms with a browser-free health check that aren't in the registry yet.
# Registry-wired platforms use `auth probe` instead.
_VALIDATORS = {
    "zepto_seller": zepto_seller_validate,
}

app = typer.Typer(help="Manage marketplace platform sessions (not Foresight logins).")
credentials_app = typer.Typer(help="Per-tenant login credentials.")
app.add_typer(credentials_app, name="credentials")
console = Console()


@credentials_app.command("set")
def credentials_set(
    platform: str = typer.Argument(..., help=f"One of: {', '.join(AUTHENTICATORS)}"),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    email: str = typer.Option(..., "--email", help="Login address for this platform"),
    password: bool = typer.Option(
        False, "--password", help="Prompt for a password (hidden input)"
    ),
) -> None:
    """Store a tenant's login credentials for a platform.

    The password is encrypted at rest with the same Fernet key as sessions, and
    is never echoed or logged. Platforms that log in by magic link or OTP
    (both Blinkit dashboards) need no password at all.
    """
    secret = typer.prompt("Password", hide_input=True, confirmation_prompt=True) if password else None
    asyncio.run(_credentials_set(platform, tenant_id, email, secret))


async def _credentials_set(
    platform: str, tenant_id: str, email: str, password: str | None
) -> None:
    auth = AUTHENTICATORS.get(platform)
    if auth is None:
        console.print(f"[red]Unknown platform {platform!r}.[/red]")
        raise typer.Exit(1)
    if auth.needs_password and not password:
        console.print(
            f"[yellow]{auth.name} logs in with a password — re-run with --password.[/yellow]"
        )
        raise typer.Exit(1)
    if password and not auth.needs_password:
        console.print(
            f"[yellow]Note: {auth.name} is passwordless "
            f"({auth.secret_kind.value}); storing it anyway.[/yellow]"
        )

    async with AsyncSessionLocal() as db:
        await store.save_credentials(
            db, tenant_id, platform, Credentials(email=email, password=password)
        )
    console.print(f"[green]Credentials saved for {platform}.[/green]")


@credentials_app.command("list")
def credentials_list(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Show stored credentials for a tenant. Passwords are never displayed."""
    asyncio.run(_credentials_list(tenant_id))


async def _credentials_list(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        rows = await store.credentials_for_tenant(db, tenant_id)
    if not rows:
        console.print(f"[yellow]No credentials stored for tenant {tenant_id}.[/yellow]")
        return
    table = Table(title=f"Platform credentials — tenant {tenant_id}")
    for col in ("platform", "email", "password", "updated"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["platform"],
            r["login_email"],
            "[green]stored[/green]" if r["has_password"] else "—",
            str(r["updated_at"] or "—")[:19],
        )
    console.print(table)


@credentials_app.command("remove")
def credentials_remove(
    platform: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Delete a tenant's stored credentials for a platform."""
    if not typer.confirm(f"Delete {platform} credentials for tenant {tenant_id}?"):
        raise typer.Exit()
    asyncio.run(_credentials_remove(platform, tenant_id))


async def _credentials_remove(platform: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        removed = await store.delete_credentials(db, tenant_id, platform)
    console.print(
        "[green]Removed.[/green]" if removed else "[yellow]Nothing stored.[/yellow]"
    )


@app.command("platforms")
def platforms() -> None:
    """List every platform the auth registry knows about."""
    table = Table(title="Platform authenticators")
    for col in ("slug", "marketplace", "secret", "password", "refresh", "mail rule", "status"):
        table.add_column(col)
    for slug, a in sorted(AUTHENTICATORS.items()):
        try:
            verified = mail_rules.for_platform(slug).verified
            rule = "[green]verified[/green]" if verified else "[yellow]unverified[/yellow]"
        except KeyError:
            rule = "[red]missing[/red]"
        table.add_row(
            slug,
            a.marketplace,
            a.secret_kind.value,
            "required" if a.needs_password else "—",
            "yes" if a.refreshable else "no",
            rule,
            "[green]wired[/green]" if a.wired else "[yellow]planned[/yellow]",
        )
    console.print(table)
    unverified = mail_rules.unverified()
    if unverified:
        console.print(
            f"\n[yellow]Mail rules never checked against a real message: "
            f"{', '.join(unverified)}[/yellow]\n"
            "[dim]Run `python -m scripts.inbox_scan` to pin them.[/dim]"
        )


@app.command("login")
def login(
    platform: str = typer.Argument(..., help=f"One of: {', '.join(wired_slugs())}"),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    email: str = typer.Option(None, "--email", help="Login address (required on first login)"),
    auto: bool = typer.Option(
        True, "--auto/--manual",
        help="Read the OTP/magic link from the auth inbox, or prompt for it",
    ),
) -> None:
    """Log in to a marketplace dashboard and store the session.

    No browser is launched for either Blinkit dashboard — login is HTTP only.
    """
    asyncio.run(_login(platform, tenant_id, email, auto))


async def _login(platform: str, tenant_id: str, email: str | None, auto: bool) -> None:
    async with AsyncSessionLocal() as db:
        try:
            auth = get_authenticator(platform)
            password = None
            if not email and not await store.login_email(db, tenant_id, platform):
                email = typer.prompt(f"{auth.name} login email")
                if auth.needs_password:
                    password = typer.prompt(
                        "Password", hide_input=True, confirmation_prompt=True
                    )
            if auto:
                console.print("[cyan]Requesting the secret and reading the auth inbox…[/cyan]")
            await service.login(
                db, tenant_id, platform, email=email, password=password, auto=auto
            )
            console.print(f"[green]{auth.name}: session saved.[/green]")
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@app.command("refresh")
def refresh(
    platform: str = typer.Argument(..., help=f"One of: {', '.join(wired_slugs())}"),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Extend a stored session without any email — the normal upkeep path."""
    asyncio.run(_refresh(platform, tenant_id))


async def _refresh(platform: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            session = await service.refresh_if_possible(db, tenant_id, platform)
        except Exception as e:
            console.print(f"[red]Refresh failed: {e}[/red]")
            raise typer.Exit(1)
    if session:
        console.print("[green]Session refreshed — no login needed.[/green]")
    else:
        console.print("[yellow]Could not refresh; a full login is required.[/yellow]")
        raise typer.Exit(1)


@app.command("refresh-all")
def refresh_all(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Refresh every stored session for a tenant — the scheduled upkeep path.

    Costs one API call per platform, consumes no secret and sends no email, so
    sessions never reach their expiry and full logins stay rare. Skips entirely
    if any other job is active for this tenant: a seller token rotation kills the
    previous token and would break a scrape already using it.
    """
    asyncio.run(_refresh_all(tenant_id))


async def _refresh_all(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        results = await service.refresh_all(db, tenant_id)
    for platform, outcome in sorted(results.items()):
        colour = {
            "refreshed": "green",
            "skipped_busy": "yellow",
            "failed": "red",
        }.get(outcome, "dim")
        console.print(f"  {platform:16} [{colour}]{outcome}[/{colour}]")
    # Deliberately exits 0 even on failure: a session that could not be refreshed
    # is usually still valid, and ensure() repairs it on next use. Failing here
    # would page a human for something that self-heals.


@app.command("probe")
def probe(
    platform: str = typer.Argument(..., help=f"One of: {', '.join(wired_slugs())}"),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Check whether a stored session actually still works."""
    asyncio.run(_probe(platform, tenant_id))


async def _probe(platform: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            alive = await service.probe(db, tenant_id, platform)
        except Exception as e:
            console.print(f"[red]Probe failed: {e}[/red]")
            raise typer.Exit(1)
    if alive:
        console.print(f"[green]{platform}: session is alive.[/green]")
    else:
        console.print(f"[red]{platform}: session is dead — run `cli auth login {platform}`.[/red]")
        raise typer.Exit(1)


@app.command("reset")
def reset(
    platform: str = typer.Argument(..., help=f"One of: {', '.join(wired_slugs())}"),
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Clear the failure count after fixing whatever broke auto-login.

    Auto-login suspends itself after repeated failures. Once the cause is fixed,
    this re-arms it without needing a successful manual login first.
    """
    asyncio.run(_reset(platform, tenant_id))


async def _reset(platform: str, tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        cleared = await store.clear_failures(db, tenant_id, platform)
    console.print(
        f"[green]{platform}: failure count reset — auto-login re-armed.[/green]"
        if cleared
        else f"[yellow]No session stored for {platform}.[/yellow]"
    )


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
) -> None:
    """Show stored sessions and how healthy they are."""
    asyncio.run(_auth_status(tenant_id))


async def _auth_status(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        rows = await store.all_for_tenant(db, tenant_id)

    if not rows:
        console.print(f"[yellow]No sessions stored for tenant {tenant_id}.[/yellow]")
        return

    colours = {"active": "green", "expired": "red", "unknown": "yellow"}
    table = Table(title=f"Platform sessions — tenant {tenant_id}")
    for col in ("platform", "email", "status", "last login", "last verified", "fails"):
        table.add_column(col)
    for r in rows:
        colour = colours.get(r["status"], "yellow")
        table.add_row(
            r["platform"],
            r["login_email"] or "—",
            f"[{colour}]{r['status']}[/{colour}]",
            str(r["last_login_at"] or "—")[:19],
            str(r["last_validated_at"] or "—")[:19],
            str(r["consecutive_failures"]),
        )
    console.print(table)
    for r in rows:
        if r["last_error"]:
            console.print(f"[dim]{r['platform']}: {r['last_error']}[/dim]")
    console.print(
        "\n[dim]'status' is only as fresh as the last check — run "
        "`cli auth probe <platform> -t <id>` to verify now.[/dim]"
    )


# ── Aliases for the pre-platform_auth command names ──────────────────────────

@app.command("blinkit")
def blinkit_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    email: str = typer.Option(None, "--email"),
    auto: bool = typer.Option(True, "--auto/--manual"),
) -> None:
    """Alias for `auth login blinkit`."""
    asyncio.run(_login("blinkit", tenant_id, email, auto))


@app.command("blinkit-seller")
def blinkit_seller_login(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    email: str = typer.Option(None, "--email"),
    auto: bool = typer.Option(True, "--auto/--manual"),
) -> None:
    """Alias for `auth login blinkit_seller`."""
    asyncio.run(_login("blinkit_seller", tenant_id, email, auto))


# ── Zepto — outside platform_auth for now (registry: wired=False) ─────────────
# Zepto's sign-in rejects headless browsers (401 before the OTP screen, in
# Chromium, Firefox and WebKit alike), so it is a headful Playwright flow rather
# than the HTTP flows platform_auth models. On a display-less box it runs under
# `xvfb-run`. Verified end to end on foresight-vm.

@app.command("zepto-seller")
def zepto_seller_login_cmd(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
) -> None:
    """Log in to Zepto Seller via email + password + OTP and save the session."""
    asyncio.run(_zepto_seller_login(tenant_id))


async def _zepto_seller_login(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            if await session_exists(db, tenant_id, "zepto_seller"):
                if not typer.confirm("A session already exists for this tenant. Overwrite?"):
                    raise typer.Exit()

            email = typer.prompt("Zepto seller email")
            password = typer.prompt("Zepto seller password", hide_input=True)
            console.print("\n[yellow]Browser opening — enter your OTP when prompted.[/yellow]\n")
            storage_state = await zepto_seller_login(email, password)

            await save_session(db, tenant_id, "zepto_seller", storage_state)
            console.print("[green]Login successful. Session saved.[/green]")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Login failed: {e}[/red]")
            raise typer.Exit(1)


@app.command("validate")
def auth_validate(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    platform: str = typer.Option(..., "--platform", "-p", help="Platform, e.g. zepto_seller"),
) -> None:
    """Check whether a saved session is still accepted, for platforms not yet in
    the auth registry. Registry-wired platforms use `auth probe` instead."""
    asyncio.run(_auth_validate(tenant_id, platform))


async def _auth_validate(tenant_id: str, platform: str) -> None:
    validator = _VALIDATORS.get(platform)
    if not validator:
        console.print(
            f"[red]No validator for platform={platform}[/red] "
            f"(available here: {', '.join(_VALIDATORS)}; registry platforms use `auth probe`)"
        )
        raise typer.Exit(1)

    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, tenant_id, platform)
        if not storage_state:
            console.print(f"[red]No saved session[/red]: tenant={tenant_id} platform={platform}")
            raise typer.Exit(1)

        ok, error = await validator(storage_state)
        if ok:
            await store.mark_validated(db, tenant_id, platform)
        else:
            # login_attempt=False — a probe finding an expired session is normal,
            # not a broken login. See store.mark_failed.
            await store.mark_failed(db, tenant_id, platform, error or "validation failed", login_attempt=False)

    if ok:
        console.print(f"[green]Valid[/green]: tenant={tenant_id} platform={platform}")
    else:
        console.print(f"[red]Invalid[/red]: tenant={tenant_id} platform={platform} — {error}")
