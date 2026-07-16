import asyncio

import typer
from rich.console import Console

from jobs.maintenance import prune_logs

app = typer.Typer(help="Maintenance tasks (log hygiene). See docs/jobs.md.")
console = Console()


@app.command("log-cleanup")
def log_cleanup(
    days: int = typer.Option(14, "--days", help="Delete per-run job logs older than this"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be deleted, delete nothing"),
):
    """Prune old per-run job logs under logs/jobs/. Runs as the maint.log_cleanup job."""
    files, freed = prune_logs(days, dry_run)
    verb = "would delete" if dry_run else "deleted"
    console.print(f"{verb} {files} log file(s), {freed / 1024:.0f} KB, older than {days} days")
