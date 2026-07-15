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
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

from app.core.config import BASE_DIR, settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, Lane
from app.utils.logger import logger
from jobs import queue as job_queue
from jobs.types import spec_for

try:
    import psutil
except ImportError:  # sampling degrades gracefully where psutil is absent
    psutil = None

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_HOSTNAME = socket.gethostname()

_SAMPLE_INTERVAL_S = 2.0        # how often to poll a running child's RSS
_SHUTDOWN_GRACE_S = 20.0        # after SIGTERM, how long a child gets before SIGKILL


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
    day = datetime.now().strftime("%Y-%m-%d")
    d = Path(settings.LOG_DIR) / "jobs" / day
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job.job_type}__{job.id}.log"


def _classify_failure(returncode: int | None, timed_out: bool, interrupted: bool) -> str:
    if interrupted:
        return "interrupted"
    if timed_out:
        return "timeout"
    # On Linux the OOM killer sends SIGKILL → asyncio reports returncode -9.
    if returncode == -9:
        return "oom"
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
    spec = spec_for(job.job_type)
    timeout_s = settings.JOB_TIMEOUT_OVERRIDES.get(job.job_type, spec.timeout_s)
    args = spec.build_args(job.tenant_id, job.params or {})
    argv = " ".join([sys.executable, "-m", "cli", *args])
    log_path = _log_path_for(job)

    async with AsyncSessionLocal() as db:
        await job_queue.mark_started(db, job.id, argv, str(log_path))

    logger.info(f"job {str(job.id)[:8]} [{job.lane.value}] {job.job_type} → {log_path.name}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    returncode = peak = None
    timed_out = interrupted = False
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
            logger.error(f"job {str(job.id)[:8]} spawn failed: {e}")
            return
        returncode, peak, timed_out, interrupted = await _supervise(proc, timeout_s, shutdown)
        f.write(f"\n# exit {returncode} · peak {peak} MB · "
                f"{'timeout' if timed_out else 'interrupted' if interrupted else 'done'}\n")

    if returncode == 0:
        status, error = JobStatus.success, None
    else:
        status, error = JobStatus.failed, _classify_failure(returncode, timed_out, interrupted)

    async with AsyncSessionLocal() as db:
        await job_queue.complete(db, job.id, status, exit_code=returncode,
                                 error=error, peak_rss_mb=peak)
    level = logger.info if status == JobStatus.success else logger.warning
    level(f"job {str(job.id)[:8]} {status.value}"
          + (f" ({error})" if error else "") + f" · peak {peak} MB")


async def run() -> None:
    """The consumer loop. Runs until SIGTERM/SIGINT, then drains in-flight jobs."""
    shutdown = asyncio.Event()
    _install_signal_handlers(shutdown)

    logger.info(f"runner {WORKER_ID} starting · lanes={settings.LANE_SLOTS}")

    # Reaper: clean up jobs stranded by a previous crash before claiming anything.
    async with AsyncSessionLocal() as db:
        pid_alive = psutil.pid_exists if psutil else (lambda _p: False)
        reaped = await job_queue.reap_stale(db, _HOSTNAME, pid_alive)
    if reaped:
        logger.warning(f"reaped {reaped} stale running job(s) from a previous run")

    active: dict[Lane, set[asyncio.Task]] = {lane: set() for lane in Lane}

    while not shutdown.is_set():
        for lane in Lane:
            slots = settings.LANE_SLOTS.get(lane.value, 0)
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
