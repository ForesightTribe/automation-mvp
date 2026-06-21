import asyncio

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.account import Account
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
