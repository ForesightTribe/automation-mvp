import sys
import asyncio
import typer
from cli.commands import account, ads, auth, scrape, tenant, watchlist, locations, sync, sku_map, explore, jobs, runner, schedules, maint, monitor

# Windows requires ProactorEventLoop for Playwright subprocess spawning
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Harden console output: the legacy Windows console encodes as cp1252, which
# can't represent characters that show up in scraped data (₹, →, accents) and
# would otherwise crash a print. Fall back to replacement instead of raising.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

app = typer.Typer(
    name="cli",
    help="Foresight automation CLI — scrape platform dashboards from the terminal.",
    no_args_is_help=True,
)

app.add_typer(account.app, name="account")
app.add_typer(ads.app, name="ads")
app.add_typer(auth.app, name="auth")
app.add_typer(scrape.app, name="scrape")
app.add_typer(tenant.app, name="tenant")
app.add_typer(watchlist.app, name="watchlist")
app.add_typer(locations.app, name="locations")
app.add_typer(sku_map.app, name="sku-map")
app.add_typer(jobs.app, name="jobs")
app.add_typer(runner.app, name="runner")
app.add_typer(schedules.app, name="schedules")
app.add_typer(maint.app, name="maint")
app.add_typer(monitor.app, name="monitor")
app.command("sync")(sync.run_sync)
app.command("explore")(explore.explore)

if __name__ == "__main__":
    app()
