import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.job import JobSchedule
from jobs.scheduler import initial_next_run, validate_cron
from jobs.types import JOB_TYPES, spec_for

app = typer.Typer(help="Recurring job schedules (cron → queue). See docs/jobs.md.")
console = Console()


@app.command("add")
def add_schedule(
    name: str = typer.Option(..., "--name", "-n", help="Human label, e.g. 'Dobra public weekly'"),
    job_type: str = typer.Option(..., "--type", help="e.g. scrape.public_keyword (see `cli jobs types`)"),
    cron: str = typer.Option(..., "--cron", help="5-field crontab in IST, e.g. '0 3 * * *' (daily 03:00)"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID"),
    param: list[str] = typer.Option(None, "--param", "-p", help="Job param key=value (repeatable)"),
    priority: int = typer.Option(100, "--priority", help="Lower runs first, within a lane"),
    catchup: bool = typer.Option(False, "--catchup", help="Run a missed occurrence once on recovery"),
    disabled: bool = typer.Option(False, "--disabled", help="Create it disabled"),
):
    """Create a recurring schedule. Validates the job type and the cron expression."""
    try:
        spec_for(job_type)
        validate_cron(cron)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if spec_for(job_type).needs_tenant and not tenant_id:
        console.print(f"[red]{job_type} requires --tenant[/red]")
        raise typer.Exit(1)
    params = {}
    for kv in param or []:
        if "=" not in kv:
            console.print(f"[red]--param must be key=value, got {kv!r}[/red]")
            raise typer.Exit(1)
        k, v = kv.split("=", 1)
        params[k] = v
    asyncio.run(_add(name, job_type, cron, tenant_id, params, priority, catchup, not disabled))


async def _add(name, job_type, cron, tenant_id, params, priority, catchup, enabled) -> None:
    async with AsyncSessionLocal() as db:
        sched = JobSchedule(
            name=name, job_type=job_type, cron=cron,
            tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
            params=params, priority=priority, catchup=catchup, enabled=enabled,
            next_run_at=initial_next_run(cron) if enabled else None,
        )
        db.add(sched)
        await db.commit()
        await db.refresh(sched)
    state = "enabled" if enabled else "[dim]disabled[/dim]"
    nxt = sched.next_run_at.strftime("%Y-%m-%d %H:%M IST") if sched.next_run_at else "—"
    console.print(f"[green]Schedule #{sched.id} created[/green] ({state}) — next run {nxt}")


@app.command("list")
def list_schedules():
    """List all schedules."""
    asyncio.run(_list())


async def _list() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(JobSchedule).order_by(JobSchedule.id))).scalars().all()
    if not rows:
        console.print("[dim]No schedules. Add one with `cli schedules add`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "name", "type", "cron", "enabled", "next run", "last run"):
        table.add_column(col)
    for s in rows:
        table.add_row(
            str(s.id),
            s.name,
            s.job_type.replace("scrape.", ""),
            s.cron,
            "[green]yes[/green]" if s.enabled else "[red]no[/red]",
            s.next_run_at.strftime("%m-%d %H:%M") if s.next_run_at else "—",
            s.last_enqueued_at.strftime("%m-%d %H:%M") if s.last_enqueued_at else "—",
        )
    console.print(table)


def _set_enabled(schedule_id: int, enabled: bool) -> None:
    async def _run():
        async with AsyncSessionLocal() as db:
            s = await db.get(JobSchedule, schedule_id)
            if not s:
                console.print(f"[red]No schedule #{schedule_id}[/red]")
                raise typer.Exit(1)
            s.enabled = enabled
            # Re-arm next_run_at on enable; clear it on disable so it can't fire.
            s.next_run_at = initial_next_run(s.cron) if enabled else None
            await db.commit()
        console.print(f"[green]Schedule #{schedule_id} {'enabled' if enabled else 'disabled'}[/green]")
    asyncio.run(_run())


@app.command("enable")
def enable(schedule_id: int = typer.Argument(...)):
    """Enable a schedule (re-arms its next run)."""
    _set_enabled(schedule_id, True)


@app.command("disable")
def disable(schedule_id: int = typer.Argument(...)):
    """Disable a schedule (stops it firing; keeps the row)."""
    _set_enabled(schedule_id, False)


@app.command("remove")
def remove(schedule_id: int = typer.Argument(...)):
    """Delete a schedule."""
    async def _run():
        async with AsyncSessionLocal() as db:
            s = await db.get(JobSchedule, schedule_id)
            if not s:
                console.print(f"[red]No schedule #{schedule_id}[/red]")
                raise typer.Exit(1)
            await db.delete(s)
            await db.commit()
        console.print(f"[green]Schedule #{schedule_id} removed[/green]")
    asyncio.run(_run())
