import sys
import asyncio
import typer
from cli.commands import account, auth, scrape, tenant, watchlist, locations, sync, sku_map

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
app.add_typer(watchlist.app, name="watchlist")
app.add_typer(locations.app, name="locations")
app.add_typer(sku_map.app, name="sku-map")
app.command("sync")(sync.run_sync)

if __name__ == "__main__":
    app()
