"""The runner daemon.

One long-lived process, supervised by systemd. It drains the `jobs` queue by
spawning each job as a SUBPROCESS — the exact `python -m cli …` you would type by
hand — with the child's stdout+stderr redirected into a per-run log file. When the
child exits, the outcome is written back to the job row.

Subprocess, not in-process call, on purpose: a Chromium OOM kills the child, not
this daemon; memory is fully reclaimed on exit; the child's console output *is* the
log. See docs/jobs.md.

Phase 1 is the CONSUMER only. The scheduler that enqueues on a cron (the producer)
is Phase 2.
"""

import asyncio
import os
import shlex
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlmodel import select

from app.core.config import BASE_DIR, settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, Lane
from app.models.tenant import Tenant
from app.utils.logger import logger
from jobs import queue as job_queue
from jobs.types import label_for, spec_for
from platform_auth.errors import AUTH_EXPIRED_EXIT_CODE

try:
    import psutil
except ImportError:  # sampling degrades gracefully where psutil is absent
    psutil = None

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_HOSTNAME = socket.gethostname()

_SAMPLE_INTERVAL_S = 2.0        # how often to poll a running child's RSS
_SHUTDOWN_GRACE_S = 20.0        # after SIGTERM, how long a child gets before SIGKILL

# Reading a failed job's own log back into the failure line. The runner supervises
# SUBPROCESSES, so the only thing that crosses back from a child is an exit code —
# `exit_1` is not laziness, it is genuinely all this process knows. The reason is in
# the child's log, whose path we already hold. Tailing it is what turns the failure
# into a sentence, in the log AND in the alert email built from it.
_TAIL_BYTES = 16 * 1024         # read from the END: a public scrape's log is huge
_TAIL_LINES = 8

_REASON_TEXT = {
    "auth_expired": "could not log in to the platform",
    "oom": "ran out of memory and was killed",
    "timeout": "ran past its time limit and was stopped",
    "runner_died": "the runner was killed while this was running",
    "interrupted": "was stopped when the runner shut down",
}

# Tenant names for log lines, cached for the process lifetime — a UUID tells a human
# nothing, and names effectively never change.
_TENANT_NAMES: dict[uuid.UUID, str] = {}


def _tree_rss_mb(pid: int) -> int:
    """Resident memory of a process AND its descendants, in MB. Chromium spawns
    children, so a naive single-process read misses most of the footprint. 0 when
    psutil is unavailable or the process has already gone."""
    if psutil is None:
        return 0
    try:
        proc = psutil.Process(pid)
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total // (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0


def _kill_tree(pid: int) -> None:
    """Terminate a process and its descendants, escalating to kill after a grace."""
    if psutil is None:
        return
    try:
        procs = [psutil.Process(pid)]
        procs += procs[0].children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=10)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def _log_path_for(job: Job) -> Path:
    """logs/jobs/<date>/<lane>/<job_type>__<job_id>.log

    The lane is in the PATH so log shipping can split by it: the Ops Agent gets one
    receiver per lane, which surfaces in Logs Explorer as a separate stream — a 5h
    public scrape's thousands of lines never drown a 30s dashboard scrape.
    """
    day = datetime.now().strftime("%Y-%m-%d")
    d = Path(settings.LOG_DIR) / "jobs" / day / job.lane.value
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job.job_type}__{job.id}.log"


def _clip(text: str, limit: int = 220) -> str:
    """Trim a log line to something that fits in a message without swallowing it."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tail_lines(path: Path, max_lines: int = _TAIL_LINES) -> list[str]:
    """The last few meaningful lines of a job's own log file.

    Seeks to the END rather than reading the file: a public scrape's log runs to
    hundreds of MB and must never be loaded whole just to describe a failure. Never
    raises — a missing or unreadable log must not break the job it describes.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > _TAIL_BYTES:
                f.seek(-_TAIL_BYTES, os.SEEK_END)
            blob = f.read()
    except OSError:
        return []
    lines = blob.decode("utf-8", errors="replace").splitlines()
    # Drop the runner's own bookkeeping (the `# argv` / `# exit N` markers written
    # around the child's output) and blank padding — never the reason for anything.
    meaningful = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    return meaningful[-max_lines:]


def _plain_reason(error: str | None, returncode: int | None) -> str:
    """`exit_1` rendered in English. The machine-readable code stays in the structured
    `error` field for filtering; this is the half a human reads."""
    if not error:
        return "failed"
    if error in _REASON_TEXT:
        return _REASON_TEXT[error]
    if error.startswith("spawn_failed"):
        return "the runner could not start the command"
    if error.startswith("unresolvable"):
        return "this runner has no code for that job type"
    return f"the command exited with code {returncode}"


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


async def _tenant_name(tenant_id: uuid.UUID | None) -> str | None:
    """The client's name, for log lines. Returns None rather than raising — a label
    must never be able to fail the job it is describing."""
    if tenant_id is None:
        return None
    if tenant_id in _TENANT_NAMES:
        return _TENANT_NAMES[tenant_id]
    try:
        async with AsyncSessionLocal() as db:
            name = (
                await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
            ).scalar()
    except Exception:
        return None
    if name:
        _TENANT_NAMES[tenant_id] = name
    return name


def _describe(job: Job, tenant_name: str | None) -> str:
    """How a job introduces itself to a human: "Dobra · Blinkit ads scrape"."""
    label = label_for(job.job_type)
    return f"{tenant_name} · {label}" if tenant_name else label


def _classify_failure(returncode: int | None, timed_out: bool, interrupted: bool) -> str:
    if interrupted:
        return "interrupted"
    if timed_out:
        return "timeout"
    # On Linux the OOM killer sends SIGKILL → asyncio reports returncode -9.
    if returncode == -9:
        return "oom"
    # Jobs are subprocesses, so a typed exception in the child cannot reach us —
    # only an exit code can. cli/main.py exits with AUTH_EXPIRED_EXIT_CODE when a
    # run dies specifically because a platform session could not be established,
    # which is what makes `auth_expired` a real, filterable value rather than
    # another anonymous exit_1.
    if returncode == AUTH_EXPIRED_EXIT_CODE:
        return "auth_expired"
    return f"exit_{returncode}"


async def _supervise(proc, timeout_s: int, shutdown: asyncio.Event) -> tuple[int | None, int, bool, bool]:
    """Wait for the child, sampling peak RSS and enforcing the timeout + shutdown.
    Returns (returncode, peak_rss_mb, timed_out, interrupted)."""
    peak = _tree_rss_mb(proc.pid)   # sample once up front — short jobs may exit before the first wait
    start = time.monotonic()
    shutdown_deadline: float | None = None
    while True:
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=_SAMPLE_INTERVAL_S)
            peak = max(peak, _tree_rss_mb(proc.pid))
            return proc.returncode, peak, False, shutdown.is_set()
        except asyncio.TimeoutError:
            peak = max(peak, _tree_rss_mb(proc.pid))

        if time.monotonic() - start > timeout_s:
            _kill_tree(proc.pid)
            await proc.wait()
            return proc.returncode, peak, True, False

        if shutdown.is_set():
            if shutdown_deadline is None:
                shutdown_deadline = time.monotonic() + _SHUTDOWN_GRACE_S
            elif time.monotonic() > shutdown_deadline:
                _kill_tree(proc.pid)
                await proc.wait()
                return proc.returncode, peak, False, True


async def _run_job(job: Job, shutdown: asyncio.Event) -> None:
    """Execute one claimed job as a subprocess and record its outcome."""
    # Resolving the type and building the argv happen AFTER the claim, so a failure here
    # must fail the job explicitly. Letting it raise strands the row in `running` with no
    # argv and no log — and the partial unique index then wedges that (job_type, tenant)
    # pair until a runner restart happens to reap it.
    #
    # The live case is a DEPLOY SKEW: the API and the runner ship separately, so a newly
    # added job type can be enqueued by the API minutes (or days) before this box has the
    # code for it. `spec_for` raises "unknown job_type" and every such enqueue is stranded.
    # Failing loudly instead makes it a visible, alerting error and frees the guard.
    short = str(job.id)[:8]
    tenant_name = await _tenant_name(job.tenant_id)
    desc = _describe(job, tenant_name)

    try:
        spec = spec_for(job.job_type)
        timeout_s = settings.JOB_TIMEOUT_OVERRIDES.get(job.job_type, spec.timeout_s)
        args = spec.build_args(job.tenant_id, job.params or {})
    except Exception as e:
        async with AsyncSessionLocal() as db:
            await job_queue.complete(db, job.id, JobStatus.failed, error=f"unresolvable: {e}")
        logger.bind(job_id=str(job.id), job_type=job.job_type,
                    tenant_id=str(job.tenant_id) if job.tenant_id else None,
                    lane=job.lane.value, error=f"unresolvable: {e}").error(
            f"{desc} · COULD NOT START — this runner has no code for job type "
            f"'{job.job_type}'. Something newer enqueued it, so this box is probably "
            f"behind main. Nothing ran. · job {short}")
        return
    # shlex.join so a value containing spaces (e.g. --city "delhi ncr") is recorded
    # unambiguously and stays copy-pasteable. The subprocess itself gets an argv
    # LIST, so spaces are safe there regardless — this is for the record/display.
    argv = shlex.join([sys.executable, "-m", "cli", *args])
    log_path = _log_path_for(job)

    async with AsyncSessionLocal() as db:
        await job_queue.mark_started(db, job.id, argv, str(log_path))

    logger.info(f"{desc} · started · {job.lane.value} lane · job {short}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    returncode = peak = None
    timed_out = interrupted = False
    started_at = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# {argv}\n# started {datetime.now().isoformat()}\n\n")
        f.flush()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "cli", *args,
                cwd=str(BASE_DIR), env=env,
                stdout=f, stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as e:
            f.write(f"\n# runner failed to spawn: {e}\n")
            async with AsyncSessionLocal() as db:
                await job_queue.complete(db, job.id, JobStatus.failed, error=f"spawn_failed: {e}")
            logger.bind(job_id=str(job.id), job_type=job.job_type,
                        tenant_id=str(job.tenant_id) if job.tenant_id else None,
                        lane=job.lane.value, error=f"spawn_failed: {e}").error(
                f"{desc} · COULD NOT START — the runner failed to launch the command: "
                f"{e} · job {short}")
            return
        returncode, peak, timed_out, interrupted = await _supervise(proc, timeout_s, shutdown)
        f.write(f"\n# exit {returncode} · peak {peak} MB · "
                f"{'timeout' if timed_out else 'interrupted' if interrupted else 'done'}\n")

    elapsed = time.monotonic() - started_at

    if returncode == 0:
        status, error = JobStatus.success, None
    else:
        status, error = JobStatus.failed, _classify_failure(returncode, timed_out, interrupted)

    async with AsyncSessionLocal() as db:
        await job_queue.complete(db, job.id, status, exit_code=returncode,
                                 error=error, peak_rss_mb=peak)

    # On failure, read back the end of the child's own log. See _tail_lines: this is
    # the ONLY way the reason can reach this process, and it is what the alert email
    # ends up quoting.
    tail = _tail_lines(log_path) if status == JobStatus.failed else []

    # Structured fields, not just a formatted string. runner.log is written with
    # loguru serialize=True, so these land in Cloud Logging as queryable
    # jsonPayload.record.extra.* — you can filter for every auth failure across
    # all tenants without substring-matching a sentence. `client`, `job_label` and
    # `log_tail` exist so an ALERT can interpolate a readable sentence without
    # anyone opening Logs Explorer.
    bound = logger.bind(
        job_id=str(job.id),
        job_type=job.job_type,
        job_label=label_for(job.job_type),
        client=tenant_name,
        lane=job.lane.value,
        tenant_id=str(job.tenant_id) if job.tenant_id else None,
        error=error,
        exit_code=returncode,
        peak_rss_mb=peak,
        duration_s=round(elapsed, 1),
        log_file=log_path.name,
        log_tail=" / ".join(tail) or None,
    )
    if status == JobStatus.success:
        bound.info(f"{desc} · OK in {_duration(elapsed)} · {peak} MB peak · job {short}")
    else:
        # ERROR, not WARNING. The alert that matters is
        # `log_id("foresight_runner") AND severity>=ERROR` — a failed job logged
        # at WARNING is invisible to it, which would have made this whole
        # auth_expired classification pointless: the DB would know, and nobody
        # would be told. Every job failure is something a human must see.
        bound.error(
            f"{desc} · FAILED after {_duration(elapsed)} — "
            f"{_plain_reason(error, returncode)}"
            + (f' · last log line: "{_clip(tail[-1])}"' if tail else "")
            + f" · full log: {log_path.name} · job {short}"
        )


async def _consume(shutdown: asyncio.Event, lane_slots: dict[str, int] | None = None) -> None:
    """The consumer half: claim due jobs per lane and run them as subprocesses.

    `lane_slots` overrides settings.LANE_SLOTS — used by the scoped `--only-cm` runner
    to give slots to only the campaign-manager lanes, so it physically cannot claim a
    scrape or a coworker's ad job off the shared queue."""
    lane_slots = lane_slots if lane_slots is not None else settings.LANE_SLOTS
    active: dict[Lane, set[asyncio.Task]] = {lane: set() for lane in Lane}

    while not shutdown.is_set():
        for lane in Lane:
            slots = lane_slots.get(lane.value, 0)
            while len(active[lane]) < slots and not shutdown.is_set():
                async with AsyncSessionLocal() as db:
                    job = await job_queue.claim_one(db, lane, WORKER_ID)
                if job is None:
                    break
                task = asyncio.create_task(_run_job(job, shutdown))
                active[lane].add(task)
                task.add_done_callback(active[lane].discard)
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=settings.RUNNER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass

    inflight = [t for tasks in active.values() for t in tasks]
    if inflight:
        logger.info(f"shutdown: draining {len(inflight)} in-flight job(s)…")
        await asyncio.gather(*inflight, return_exceptions=True)


# Campaign-manager lanes — the only lanes a `--only-cm` runner serves. `interactive`
# is included because cm.reconcile runs there (it's browser-less); the VM being down
# means no non-cm interactive job (heartbeat/explorer) is enqueued to compete.
_CM_LANES = ("cm_ops", "cm_bid", "interactive")


async def run(only_cm: bool = False) -> None:
    """Start the runner: producer (scheduler) + consumer, until SIGTERM/SIGINT.

    `only_cm` is the safe local-test mode: the consumer is scoped to the campaign-manager
    lanes and the producer fires only cm.* schedules, so nothing else on the shared DB
    (scrapes, coworker ad crons) is claimed or fired from this machine.
    """
    shutdown = asyncio.Event()
    _install_signal_handlers(shutdown)

    lane_slots = settings.LANE_SLOTS
    prefix = None
    if only_cm:
        lane_slots = {k: v for k, v in settings.LANE_SLOTS.items() if k in _CM_LANES}
        prefix = "cm."
        logger.warning(
            f"runner {WORKER_ID} in --only-cm mode · lanes={lane_slots} · producer fires cm.* only"
        )
    else:
        logger.info(f"runner {WORKER_ID} starting · lanes={lane_slots}")

    # Reaper: clean up jobs stranded by a previous crash before claiming anything.
    async with AsyncSessionLocal() as db:
        pid_alive = psutil.pid_exists if psutil else (lambda _p: False)
        reaped = await job_queue.reap_stale(db, _HOSTNAME, pid_alive)
    if reaped:
        logger.warning(f"reaped {reaped} stale running job(s) from a previous run")

    # Producer and consumer run concurrently. Imported here to keep the module's
    # import graph flat (scheduler imports jobs.queue, not jobs.runner).
    from jobs.scheduler import run_producer

    await asyncio.gather(
        run_producer(shutdown, job_type_prefix=prefix, force=only_cm),
        _consume(shutdown, lane_slots),
    )
    logger.info("runner stopped")


def _install_signal_handlers(shutdown: asyncio.Event) -> None:
    import signal
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError:
            # Windows: add_signal_handler is unsupported; Ctrl+C raises
            # KeyboardInterrupt in run()'s asyncio.run wrapper instead.
            pass
