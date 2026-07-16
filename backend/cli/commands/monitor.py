import asyncio

import typer
from rich.console import Console

from jobs.monitor import heartbeat

app = typer.Typer(help="Monitoring / deadman checks. See docs/jobs.md.")
console = Console()


@app.command("heartbeat")
def run_heartbeat(
    disk_pct: int = typer.Option(80, "--disk-pct", help="Alert when the log disk is at/over this %"),
):
    """Assert every enabled schedule has succeeded within its window, and the disk
    isn't filling. Logs ERROR per problem (→ Cloud Logging alert) and exits non-zero
    if anything is wrong. Runs as the monitor.heartbeat job."""
    issues = asyncio.run(heartbeat(disk_pct))
    if issues:
        for i in issues:
            console.print(f"[red]✗ {i}[/red]")
        raise typer.Exit(1)
    console.print("[green]✓ all healthy[/green]")
