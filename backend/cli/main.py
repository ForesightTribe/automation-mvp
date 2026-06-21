import sys
import asyncio
import typer
from cli.commands import account, auth, scrape, tenant

# Windows requires ProactorEventLoop for Playwright subprocess spawning
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = typer.Typer(
    name="cli",
    help="Foresight automation CLI — scrape platform dashboards from the terminal.",
    no_args_is_help=True,
)

app.add_typer(account.app, name="account")
app.add_typer(auth.app, name="auth")
app.add_typer(scrape.app, name="scrape")
app.add_typer(tenant.app, name="tenant")

if __name__ == "__main__":
    app()
