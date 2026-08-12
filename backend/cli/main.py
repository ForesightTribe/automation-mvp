import sys
import asyncio
import typer
import app.utils.logger  # noqa: F401 — install the unified logging pipeline before command imports
from app.utils.logger import logger
from cli.commands import account, ads, auth, scrape, tenant, watchlist, locations, sync, sku_map, explore, export, jobs, runner, schedules, maint, monitor
from cli.commands import campaign_manager as cm
from platform_auth.errors import AUTH_EXPIRED_EXIT_CODE, AuthError

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
app.add_typer(cm.app, name="cm")
app.add_typer(auth.app, name="auth")
app.add_typer(scrape.app, name="scrape")
app.add_typer(tenant.app, name="tenant")
app.add_typer(watchlist.app, name="watchlist")
app.add_typer(locations.app, name="locations")
app.add_typer(sku_map.app, name="sku-map")
app.add_typer(export.app, name="export")
app.add_typer(jobs.app, name="jobs")
app.add_typer(runner.app, name="runner")
app.add_typer(schedules.app, name="schedules")
app.add_typer(maint.app, name="maint")
app.add_typer(monitor.app, name="monitor")
app.command("sync")(sync.run_sync)
app.command("explore")(explore.explore)

if __name__ == "__main__":
    # Auth failures exit with a distinct code so the job runner can record them
    # as `auth_expired` rather than an anonymous exit_1. Jobs are subprocesses,
    # so the exit code is the ONLY channel a typed exception has to reach the
    # runner. Catching it here means every command gets the behaviour for free.
    try:
        app()
    except AuthError as e:
        # Banner rather than a single line: this lands in the per-lane job log,
        # which is plain text read by a human, not a queried stream. When someone
        # opens a failed run's log they should see the cause and the fix without
        # scrolling or knowing what to search for.
        logger.error(
            "AUTH FAILURE — the run could not authenticate to the platform.\n"
            f"    {type(e).__name__}: {e}\n"
            "    Check: python -m cli auth status -t <tenant>\n"
            "    Fix:   python -m cli auth login <platform> -t <tenant> --manual"
        )
        raise SystemExit(AUTH_EXPIRED_EXIT_CODE)
