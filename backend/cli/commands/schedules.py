import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.job import JobSchedule
from jobs.scheduler import initial_next_run, validate_cron
from jobs.types import parse_params, spec_for

app = typer.Typer(help="Recurring job schedules (cron → queue). See docs/jobs.md.")
console = Console()


@app.command("add")
def add_schedule(
    params: list[str] = typer.Argument(
        None,
        help='key=value pairs, e.g. workers=5. Quote values with spaces: "city=delhi ncr"',
    ),
    name: str = typer.Option(..., "--name", "-n", help="Human label, e.g. 'Dobra public weekly'"),
    job_type: str = typer.Option(..., "--type", help="e.g. scrape.public_keyword (see `cli jobs types`)"),
    cron: str = typer.Option(..., "--cron", help="5-field crontab in IST, e.g. '0 3 * * *' (daily 03:00)"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID"),
    priority: int = typer.Option(100, "--priority", help="Lower runs first, within a lane"),
    catchup: bool = typer.Option(False, "--catchup", help="Run a missed occurrence once on recovery"),
    disabled: bool = typer.Option(False, "--disabled", help="Create it disabled"),
):
    """Create a recurring schedule. Validates the job type, params, and cron up front.

    Params are trailing key=value pairs:
      cli schedules add -n "Dobra weekly" --type scrape.public_keyword -t <uuid> \\
          --cron "0 1 * * 0" workers=5
    """
    try:
        spec = spec_for(job_type)
        validate_cron(cron)
        parsed = parse_params(params, spec)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if spec.needs_tenant and not tenant_id:
        console.print(f"[red]{job_type} requires --tenant[/red]")
        raise typer.Exit(1)
    asyncio.run(_add(name, job_type, cron, tenant_id, parsed, priority, catchup, not disabled))


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


@app.command("show")
def show_schedule(schedule_id: int = typer.Argument(..., help="Schedule id from `schedules list`")):
    """Show one schedule in full — including its params, tenant, catchup and priority."""
    async def _run():
        async with AsyncSessionLocal() as db:
            s = await db.get(JobSchedule, schedule_id)
        if not s:
            console.print(f"[red]No schedule #{schedule_id}[/red]")
            raise typer.Exit(1)
        spec = spec_for(s.job_type)
        params = " ".join(f"{k}={v}" for k, v in (s.params or {}).items()) or "—"
        rows = [
            ("id", str(s.id)),
            ("name", s.name),
            ("job_type", f"{s.job_type}  [dim](lane: {spec.lane.value})[/dim]"),
            ("tenant", str(s.tenant_id) if s.tenant_id else "—"),
            ("cron", f"{s.cron}  [dim](IST)[/dim]"),
            ("params", params),
            ("priority", str(s.priority)),
            ("enabled", "[green]yes[/green]" if s.enabled else "[red]no[/red]"),
            ("catchup", "yes — a missed run fires once on recovery" if s.catchup
                        else "no — a missed run is skipped"),
            ("next run", s.next_run_at.strftime("%Y-%m-%d %H:%M IST") if s.next_run_at else "—"),
            ("last run", s.last_enqueued_at.strftime("%Y-%m-%d %H:%M IST") if s.last_enqueued_at else "—"),
            ("created", s.created_at.strftime("%Y-%m-%d %H:%M IST")),
        ]
        for k, v in rows:
            console.print(f"  [dim]{k:<9}[/dim] {v}")
        # The command this schedule will actually run.
        argv = " ".join(["python", "-m", "cli"] + spec.build_args(s.tenant_id, s.params or {}))
        console.print(f"\n  [dim]runs[/dim]      {argv}")
    asyncio.run(_run())


@app.command("update")
def update_schedule(
    schedule_id: int = typer.Argument(..., help="Schedule id from `schedules list`"),
    params: list[str] = typer.Argument(
        None, help="key=value pairs — REPLACES all existing params. Omit to leave params unchanged"
    ),
    name: str = typer.Option(None, "--name", "-n", help="New label"),
    cron: str = typer.Option(None, "--cron", help="New cron (re-arms the next run)"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="New tenant UUID"),
    priority: int = typer.Option(None, "--priority", help="New priority"),
    catchup: bool = typer.Option(None, "--catchup/--no-catchup", help="Toggle catchup"),
    clear_params: bool = typer.Option(False, "--clear-params", help="Remove all params"),
):
    """Change a schedule in place, keeping its id and history.

    Only what you pass changes. Params REPLACE the existing set (see `schedules show`
    first). To change job_type, remove and re-add — params are tied to the type.
    """
    async def _run():
        async with AsyncSessionLocal() as db:
            s = await db.get(JobSchedule, schedule_id)
            if not s:
                console.print(f"[red]No schedule #{schedule_id}[/red]")
                raise typer.Exit(1)
            spec = spec_for(s.job_type)
            changed = []

            if cron is not None:
                try:
                    validate_cron(cron)
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
                    raise typer.Exit(1)
                s.cron = cron
                # Re-arm from the new cron so the change takes effect immediately.
                s.next_run_at = initial_next_run(cron) if s.enabled else None
                changed.append("cron")
            if name is not None:
                s.name = name
                changed.append("name")
            if tenant_id is not None:
                s.tenant_id = uuid.UUID(tenant_id)
                changed.append("tenant")
            if priority is not None:
                s.priority = priority
                changed.append("priority")
            if catchup is not None:
                s.catchup = catchup
                changed.append("catchup")
            if clear_params:
                s.params = {}
                changed.append("params")
            elif params:
                try:
                    s.params = parse_params(params, spec)
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
                    raise typer.Exit(1)
                changed.append("params")

            if not changed:
                console.print("[yellow]Nothing to change. Pass --cron/--name/params/… "
                              "(see `schedules update --help`).[/yellow]")
                raise typer.Exit(1)
            await db.commit()
            await db.refresh(s)
            nxt = s.next_run_at.strftime("%Y-%m-%d %H:%M IST") if s.next_run_at else "—"
        console.print(f"[green]Schedule #{schedule_id} updated[/green] ({', '.join(changed)}) — next run {nxt}")
    asyncio.run(_run())


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
