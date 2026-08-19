"""`cli status` — one screen that answers "is everything OK?".

Everything here already existed; nothing read it back to you. Answering that question
used to mean the Supabase console, GCP Logs Explorer and an SSH session — three tools
that don't agree with each other. This reads the shared `jobs` / `job_schedules`
tables, so it works **from a laptop with no VM access at all** (which is how the
2026-08-18 logging blackout was diagnosed).

Strictly read-only: SELECTs only, safe to run any time, against the shared DB.

Deliberately NOT shown: disk usage. `monitor.heartbeat` checks the disk of whichever
machine it runs on, and reporting *this* machine's disk in a screen about the VM would
be actively misleading. Disk lives in the heartbeat, on the box.
"""

import asyncio
from collections import defaultdict
from datetime import timedelta

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.utils.time import now_ist
from jobs.monitor import check_deadman
from jobs.runner import _duration, _plain_reason
from jobs.types import label_for

app = typer.Typer(help="System health at a glance (see docs/jobs.md).")
console = Console()

# The runner is considered quiet past this. Matches the SILENT alert policy's window,
# and the hourly health check alone guarantees a row every hour — so two hours of
# nothing is genuinely abnormal rather than merely idle.
_QUIET_AFTER = timedelta(hours=2)


def run_status(
    days: int = typer.Option(1, "--days", "-d", help="Window for the activity + compute sections"),
):
    """Show runner liveness, overdue schedules, recent failures and where compute went."""
    asyncio.run(_status(days))


async def _status(days: int) -> None:
    now = now_ist()
    since = now - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        recent = (
            await db.execute(
                select(Job).where(Job.created_at >= since).order_by(Job.created_at.desc())
            )
        ).scalars().all()
        last_started = (
            await db.execute(
                select(Job)
                .where(Job.started_at.is_not(None))
                .order_by(Job.started_at.desc())
                .limit(1)
            )
        ).scalars().first()
        queued = (
            await db.execute(
                select(Job).where(
                    Job.status.in_([JobStatus.pending, JobStatus.running])
                )
            )
        ).scalars().all()

    console.print()
    console.print(
        f"[bold]Foresight — system status[/bold]   [dim]{now:%d %b %Y %H:%M} IST · "
        f"last {days}d[/dim]"
    )

    _runner_section(last_started, queued, now)
    await _schedule_section()
    _activity_section(recent, days)
    _failure_section(recent)
    _compute_section(recent, days)
    console.print()


def _runner_section(last_started, queued, now) -> None:
    console.print("\n[bold]RUNNER[/bold]")
    if last_started is None or last_started.started_at is None:
        console.print("  [red]No job has ever started[/red] — the runner may never have run.")
        return

    age = now - last_started.started_at
    if age > _QUIET_AFTER:
        console.print(
            f"  [red]SILENT[/red] · nothing has started for {_duration(age.total_seconds())} "
            f"— expected a job at least hourly"
        )
        console.print("  [dim]Check: systemctl status foresight-runner (on the VM)[/dim]")
    else:
        console.print(
            f"  [green]Alive[/green] · last job started {_duration(age.total_seconds())} ago"
        )
    console.print(f"  [dim]{last_started.locked_by or 'unknown host'}[/dim]")

    pending = sum(1 for j in queued if j.status == JobStatus.pending)
    running = sum(1 for j in queued if j.status == JobStatus.running)
    console.print(f"  Queue: {pending} pending, {running} running")


async def _schedule_section() -> None:
    """Reuses the deadman check the hourly health check runs — same verdict, but shown
    on demand instead of only being expressed as a non-zero exit code."""
    issues = await check_deadman()
    console.print("\n[bold]SCHEDULED WORK[/bold]")
    if not issues:
        console.print("  [green]All schedules have run within their expected window[/green]")
        return
    console.print(f"  [red]{len(issues)} overdue[/red]")
    for i in issues:
        console.print(f"    [red]·[/red] {i}")


def _activity_section(recent, days) -> None:
    console.print(f"\n[bold]ACTIVITY[/bold] [dim]· last {days}d[/dim]")
    if not recent:
        console.print("  [dim]No jobs in this window.[/dim]")
        return

    per: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for j in recent:
        per[j.job_type][j.status.value] += 1

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for col in ("what", "ok", "failed", "other"):
        table.add_column(col)
    for job_type, counts in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        ok = counts.get("success", 0)
        bad = counts.get("failed", 0)
        other = sum(v for k, v in counts.items() if k not in ("success", "failed"))
        table.add_row(
            label_for(job_type),
            f"[green]{ok}[/green]" if ok else "[dim]0[/dim]",
            f"[red]{bad}[/red]" if bad else "[dim]0[/dim]",
            str(other) if other else "[dim]—[/dim]",
        )
    console.print(table)


def _failure_section(recent) -> None:
    failures = [j for j in recent if j.status == JobStatus.failed]
    console.print("\n[bold]FAILURES[/bold]")
    if not failures:
        console.print("  [green]None[/green]")
        return

    # Identical failures repeat hourly (a broken schedule fails every fire), so collapse
    # them: twenty copies of one line is how a real problem gets scrolled past.
    grouped: dict[tuple, list] = defaultdict(list)
    for j in failures:
        grouped[(j.job_type, j.error)].append(j)

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for col in ("what", "why", "n", "last seen", "log"):
        table.add_column(col)
    for (job_type, error), jobs in sorted(
        grouped.items(), key=lambda kv: max(j.created_at for j in kv[1]), reverse=True
    ):
        newest = max(jobs, key=lambda j: j.created_at)
        table.add_row(
            label_for(job_type),
            f"[red]{_plain_reason(error, newest.exit_code)}[/red]",
            str(len(jobs)),
            f"{newest.created_at:%d %b %H:%M}",
            f"[dim]{str(newest.id)[:8]}[/dim]",
        )
    console.print(table)
    console.print("  [dim]Read one: python -m cli jobs logs <id>[/dim]")


def _compute_section(recent, days) -> None:
    """Where the VM's time actually went. Wall-clock occupancy per lane, not CPU —
    CPU per job is not recorded anywhere (see docs/jobs.md), so this measures how long
    each lane was *busy*, which is what governs whether lanes starve each other."""
    console.print(f"\n[bold]COMPUTE[/bold] [dim]· last {days}d[/dim]")
    done = [j for j in recent if j.started_at and j.completed_at]
    if not done:
        console.print("  [dim]No completed runs in this window.[/dim]")
        return

    busy: dict[str, float] = defaultdict(float)
    peak: dict[str, int] = defaultdict(int)
    runs: dict[str, int] = defaultdict(int)
    for j in done:
        lane = j.lane.value
        busy[lane] += (j.completed_at - j.started_at).total_seconds()
        peak[lane] = max(peak[lane], j.peak_rss_mb or 0)
        runs[lane] += 1

    window_s = days * 24 * 3600
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for col in ("lane", "runs", "busy", "% of window", "peak RAM"):
        table.add_column(col)
    for lane in sorted(busy, key=lambda k: -busy[k]):
        share = busy[lane] / window_s * 100
        table.add_row(
            lane,
            str(runs[lane]),
            _duration(busy[lane]),
            f"{share:.1f}%",
            f"{peak[lane]} MB" if peak[lane] else "[dim]—[/dim]",
        )
    console.print(table)

    total = sum(busy.values())
    console.print(
        f"  [dim]Lanes run in parallel, so these overlap. Total busy "
        f"{_duration(total)} across {len(done)} runs.[/dim]"
    )
