import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from jobs import queue as job_queue
from jobs.types import JOB_TYPES

app = typer.Typer(help="Queue and inspect runner jobs (see docs/jobs.md).")
console = Console()

_STATUS_COLOR = {
    JobStatus.pending: "yellow",
    JobStatus.running: "cyan",
    JobStatus.success: "green",
    JobStatus.failed: "red",
}


@app.command("types")
def list_types():
    """List the known job types, their lane, and timeout."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("job_type")
    table.add_column("lane")
    table.add_column("timeout")
    for name, spec in sorted(JOB_TYPES.items()):
        table.add_row(name, spec.lane.value, f"{spec.timeout_s // 60} min")
    console.print(table)


@app.command("run")
def run_job(
    job_type: str = typer.Argument(..., help="e.g. scrape.public_keyword (see `jobs types`)"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID"),
    param: list[str] = typer.Option(
        None, "--param", "-p", help="Job param as key=value (repeatable), e.g. -p city=bengaluru"
    ),
    priority: int = typer.Option(100, "--priority", help="Lower runs first, within a lane"),
):
    """Enqueue a job. The runner picks it up — it does not run inline here."""
    params = {}
    for kv in param or []:
        if "=" not in kv:
            console.print(f"[red]--param must be key=value, got {kv!r}[/red]")
            raise typer.Exit(1)
        k, v = kv.split("=", 1)
        params[k] = v
    asyncio.run(_run_job(job_type, tenant_id, params, priority))


async def _run_job(job_type, tenant_id, params, priority) -> None:
    async with AsyncSessionLocal() as db:
        try:
            job = await job_queue.enqueue(
                db,
                job_type=job_type,
                tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                params=params,
                priority=priority,
            )
        except job_queue.DuplicateActiveJob as e:
            console.print(f"[yellow]Not queued:[/yellow] {e}")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    console.print(f"[green]Queued[/green] {job.job_type} [{job.lane.value}]  id [bold]{job.id}[/bold]")
    console.print(f"[dim]The runner will pick it up. Watch: cli jobs logs {str(job.id)[:8]}[/dim]")


@app.command("list")
def list_jobs(limit: int = typer.Option(20, "--limit", "-n", help="How many recent jobs")):
    """Show recent jobs, newest first."""
    asyncio.run(_list_jobs(limit))


async def _list_jobs(limit) -> None:
    async with AsyncSessionLocal() as db:
        rows = await job_queue.recent(db, limit=limit)
    if not rows:
        console.print("[dim]No jobs yet. Queue one with `cli jobs run`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "type", "lane", "status", "started", "dur", "peak", "error"):
        table.add_column(col)
    for j in rows:
        dur = ""
        if j.started_at and j.completed_at:
            dur = f"{(j.completed_at - j.started_at).total_seconds():.0f}s"
        color = _STATUS_COLOR.get(j.status, "white")
        table.add_row(
            str(j.id)[:8],
            j.job_type.replace("scrape.", ""),
            j.lane.value,
            f"[{color}]{j.status.value}[/{color}]",
            j.started_at.strftime("%m-%d %H:%M") if j.started_at else "—",
            dur or "—",
            f"{j.peak_rss_mb}MB" if j.peak_rss_mb else "—",
            j.error or "",
        )
    console.print(table)


@app.command("logs")
def show_logs(
    job_id: str = typer.Argument(..., help="Full or 8-char job id prefix"),
    tail: int = typer.Option(0, "--tail", "-n", help="Only the last N lines (0 = all)"),
):
    """Print a job's log file."""
    asyncio.run(_show_logs(job_id, tail))


async def _show_logs(job_id, tail) -> None:
    async with AsyncSessionLocal() as db:
        rows = await job_queue.recent(db, limit=200)
    match = next((j for j in rows if str(j.id) == job_id or str(j.id).startswith(job_id)), None)
    if match is None:
        console.print(f"[red]No job matching {job_id!r} in the recent set.[/red]")
        raise typer.Exit(1)
    if not match.log_path:
        console.print(f"[yellow]Job {str(match.id)[:8]} has no log yet (status {match.status.value}).[/yellow]")
        raise typer.Exit(1)
    try:
        with open(match.log_path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        console.print(f"[red]Log file missing: {match.log_path}[/red]")
        raise typer.Exit(1)
    if tail > 0:
        lines = lines[-tail:]
    console.print("".join(lines), end="")
