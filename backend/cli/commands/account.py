import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.models.tenant import Tenant, User, UserClient
from app.services import auth_service

app = typer.Typer(help="Manage accounts (subscriber orgs) and their users.")
console = Console()


@app.command("create")
def create_account(
    name: str = typer.Option(..., "--name", "-n", help="Account / org name"),
    type_: str = typer.Option("agency", "--type", help="agency | direct"),
    email: str = typer.Option(..., "--admin-email", help="First admin user's email"),
    full_name: str = typer.Option("Admin", "--admin-name", help="Admin full name"),
):
    """Create an account and its first admin user (login)."""
    if type_ not in ("agency", "direct"):
        console.print("[red]--type must be 'agency' or 'direct'[/red]")
        raise typer.Exit(1)
    password = typer.prompt("Admin password", hide_input=True, confirmation_prompt=True)
    asyncio.run(_create_account(name, type_, email, full_name, password))


async def _create_account(name, type_, email, full_name, password) -> None:
    async with AsyncSessionLocal() as db:
        try:
            account = await auth_service.create_account(db, name=name, type=type_)
            user = await auth_service.create_user(
                db,
                account_id=account.id,
                email=email,
                password=password,
                full_name=full_name,
                role="admin",  # the first user of an account is its admin
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            console.print(f"[red]A user with email {email} already exists.[/red]")
            raise typer.Exit(1)

    console.print("\n[green]Account created.[/green]")
    console.print(f"  [dim]account[/dim]  {account.name}  ([cyan]{account.type}[/cyan])")
    console.print(f"  [dim]id[/dim]       [bold]{account.id}[/bold]")
    console.print(f"  [dim]admin[/dim]    {user.email}")
    console.print(f"\n[dim]Log in at POST /api/auth/login with this email + password.[/dim]\n")


@app.command("add-user")
def add_user(
    account_id: uuid.UUID = typer.Option(..., "--account", help="Existing account UUID"),
    email: str = typer.Option(..., "--email", help="New user's login email"),
    full_name: str = typer.Option("Member", "--name", help="User's full name"),
    admin: bool = typer.Option(
        False, "--admin", help="Grant admin role (default: member)"
    ),
):
    """Add a user (login) to an existing account.

    The user belongs to the account and can see all of its clients' data. Members
    see the dashboards; admins also get Settings/admin access.
    """
    password = typer.prompt("User password", hide_input=True, confirmation_prompt=True)
    asyncio.run(_add_user(account_id, email, full_name, "admin" if admin else "member", password))


async def _add_user(account_id, email, full_name, role, password) -> None:
    async with AsyncSessionLocal() as db:
        account = await db.get(Account, account_id)
        if not account:
            console.print(f"[red]No account with id {account_id}.[/red]")
            raise typer.Exit(1)
        try:
            user = await auth_service.create_user(
                db,
                account_id=account_id,
                email=email,
                password=password,
                full_name=full_name,
                role=role,
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            console.print(f"[red]A user with email {email} already exists.[/red]")
            raise typer.Exit(1)

    console.print("\n[green]User added.[/green]")
    console.print(f"  [dim]account[/dim]  {account.name}")
    console.print(f"  [dim]email[/dim]    {user.email}")
    console.print(f"  [dim]role[/dim]     [cyan]{user.role}[/cyan]")
    console.print(f"\n[dim]They can log in at POST /api/auth/login with this email + password.[/dim]\n")


@app.command("list")
def list_accounts():
    """List all accounts."""
    asyncio.run(_list_accounts())


async def _list_accounts() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Account).order_by(Account.created_at))).scalars().all()

    if not rows:
        console.print("[dim]No accounts yet. Run `cli account create` to add one.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Active")
    table.add_column("Created")
    for a in rows:
        table.add_row(
            str(a.id),
            a.name,
            a.type,
            "[green]yes[/green]" if a.is_active else "[red]no[/red]",
            a.created_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@app.command("scope")
def set_scope(
    email: str = typer.Option(..., "--email", help="The user to re-scope"),
    clients: str = typer.Option(
        None, "--clients", help="Comma-separated Client UUIDs this user may see"
    ),
    all_clients: bool = typer.Option(
        False, "--all", help="Give this user every Client in their account"
    ),
):
    """Set which Clients a user may see.

        cli account scope --email brand@acme.com --clients <uuid>,<uuid>
        cli account scope --email staff@agency.com --all

    Replaces the user's grants outright, so the output is their complete access.
    """
    if all_clients == bool(clients):
        console.print("[red]Pass exactly one of --clients or --all.[/red]")
        raise typer.Exit(1)
    ids = []
    if clients:
        try:
            ids = [uuid.UUID(c.strip()) for c in clients.split(",") if c.strip()]
        except ValueError:
            console.print("[red]--clients must be comma-separated UUIDs.[/red]")
            raise typer.Exit(1)
        if not ids:
            console.print("[red]--clients was empty. Use --all to lift the restriction.[/red]")
            raise typer.Exit(1)
    asyncio.run(_set_scope(email, ids, all_clients))


async def _set_scope(email, client_ids, all_clients) -> None:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()
        if not user:
            console.print(f"[red]No user with email {email}.[/red]")
            raise typer.Exit(1)

        # A named Client must belong to this user's own account, or the grant
        # would punch through the account wall.
        named = []
        for cid in client_ids:
            client = await db.get(Tenant, cid)
            if not client or client.account_id != user.account_id:
                console.print(
                    f"[red]{cid} is not a Client of this user's account.[/red]"
                )
                raise typer.Exit(1)
            named.append(client)

        await db.execute(delete(UserClient).where(UserClient.user_id == user.id))
        user.client_scope = "all" if all_clients else "listed"
        for client in named:
            db.add(UserClient(user_id=user.id, tenant_id=client.id))
        db.add(user)
        await db.commit()

    console.print("\n[green]Scope updated.[/green]")
    console.print(f"  [dim]user[/dim]   {email}")
    console.print(f"  [dim]scope[/dim]  [cyan]{'all' if all_clients else 'listed'}[/cyan]")
    if all_clients:
        console.print("  [dim]sees[/dim]   every Client in the account")
    else:
        for client in named:
            console.print(f"  [dim]sees[/dim]   {client.name} [dim]{client.id}[/dim]")
    console.print(
        "\n[dim]Takes up to 60s to bite on a running API "
        "(dependencies.CLIENT_CHECK_TTL_S).[/dim]\n"
    )


@app.command("users")
def list_users(
    account_id: uuid.UUID = typer.Option(..., "--account", help="Account UUID"),
):
    """List an account's users with their role and client scope."""
    asyncio.run(_list_users(account_id))


async def _list_users(account_id) -> None:
    async with AsyncSessionLocal() as db:
        users = (
            await db.execute(
                select(User).where(User.account_id == account_id).order_by(User.created_at)
            )
        ).scalars().all()
        if not users:
            console.print("[dim]No users on that account.[/dim]")
            return
        names = dict(
            (
                await db.execute(
                    select(Tenant.id, Tenant.name).where(Tenant.account_id == account_id)
                )
            ).all()
        )
        grants: dict[uuid.UUID, list[str]] = {}
        for u in users:
            if u.client_scope != "listed":
                continue
            rows = (
                await db.execute(
                    select(UserClient.tenant_id).where(UserClient.user_id == u.id)
                )
            ).scalars().all()
            grants[u.id] = [names.get(r, str(r)) for r in rows]

    table = Table(show_header=True, header_style="bold")
    table.add_column("Email")
    table.add_column("Role")
    table.add_column("Scope")
    table.add_column("Clients")
    for u in users:
        if u.client_scope == "listed":
            seen = grants.get(u.id) or []
            # Nothing granted is a real state: this user can open no client.
            shown = ", ".join(seen) if seen else "[red]none[/red]"
        else:
            shown = "[dim]all[/dim]"
        table.add_row(u.email, u.role, u.client_scope, shown)
    console.print(table)
