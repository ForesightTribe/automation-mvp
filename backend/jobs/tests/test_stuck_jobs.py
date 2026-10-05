"""Stuck-job protection (2026-09-25) — jobs/runner.py + jobs/queue.py.

On 2026-09-24 a Dobra bid job was claimed, the write recording its start failed during a
pooler outage, the task died silently, and the row sat `running` for ~8 h while the
overlap guard turned every later bid fire away. These pin the three defences:

  * a claimed job always ends in a recorded outcome, even when its DB writes fail;
  * a failed claim does not take the runner down;
  * the running runner releases its own rows that nothing is driving any more.

No DB, no subprocess: the session factory and queue writes are stubbed.

Run:  python -m jobs.tests.test_stuck_jobs
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.job import JobStatus, Lane
from jobs import queue as job_queue
from jobs import runner

NOW = datetime(2026, 9, 24, 4, 45)
TENANT = uuid.UUID("a870fd8d-7373-47ec-ad69-5dd08ce35542")


def _row(age_s, job_type="cm.bid_optimizer", jid=None):
    return SimpleNamespace(id=jid or uuid.uuid4(), job_type=job_type,
                           locked_at=NOW - timedelta(seconds=age_s), started_at=None)


def _verdicts(rows, active=()):
    return job_queue.orphan_verdicts(
        rows, set(active), NOW, grace_s=120, margin_s=600,
        timeout_for=lambda t: 900 if t == "cm.bid_optimizer" else None)


# ── which rows the self-check releases ──────────────────────────────────────

def test_a_row_nothing_is_driving_is_released_after_the_grace():
    old = _row(300)
    assert _verdicts([old]) == [(old, job_queue.ORPHANED)]


def test_a_freshly_claimed_row_is_left_alone():
    # Between the claim and its task registering; judging it now would race the claim.
    assert _verdicts([_row(30)]) == []


def test_a_job_being_driven_is_left_alone_within_its_limit():
    r = _row(1200)                        # 20 min: past the 15-min limit, within margin
    assert _verdicts([r], active=[r.id]) == []


def test_a_job_driven_far_past_its_limit_is_released():
    r = _row(900 + 601)
    assert _verdicts([r], active=[r.id]) == [(r, job_queue.PAST_TIMEOUT)]


def test_an_unknown_type_is_never_judged_by_time():
    r = _row(99999, job_type="something.new")
    assert _verdicts([r], active=[r.id]) == []


def test_a_row_with_no_timestamps_is_skipped():
    r = SimpleNamespace(id=uuid.uuid4(), job_type="cm.bid_optimizer",
                        locked_at=None, started_at=None)
    assert _verdicts([r]) == []


# ── a claimed job always ends in a recorded outcome ─────────────────────────

class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _job():
    return SimpleNamespace(id=uuid.uuid4(), job_type="cm.bid_optimizer", tenant_id=TENANT,
                           params={"marketplace": "blinkit", "live": "true"},
                           lane=Lane.cm_bid)


def _patched(fn):
    """Run `fn` with the runner's DB layer stubbed and its retry waits at zero."""
    def run():
        saved = (runner.AsyncSessionLocal, runner._JOB_WRITE_WAITS_S,
                 job_queue.mark_started, job_queue.complete, runner._TENANT_NAMES.copy())
        runner.AsyncSessionLocal = lambda: _Session()
        runner._JOB_WRITE_WAITS_S = (0.0, 0.0, 0.0)
        try:
            fn()
        finally:
            (runner.AsyncSessionLocal, runner._JOB_WRITE_WAITS_S,
             job_queue.mark_started, job_queue.complete, names) = saved
            runner._TENANT_NAMES.clear()
            runner._TENANT_NAMES.update(names)
    run.__name__ = fn.__name__
    return run


@_patched
def test_a_start_that_cannot_be_recorded_marks_the_job_failed():
    """The 2026-09-24 case: every start write fails → the job must not stay `running`."""
    job = _job()
    runner._TENANT_NAMES[TENANT] = "Dobra"
    starts, completes = [], []

    async def _start(db, *a, **k):
        starts.append(1)
        raise ConnectionError("pooler: ECHECKOUTTIMEOUT")

    async def _complete(db, job_id, status, **kw):
        completes.append((job_id, status, kw.get("error")))

    job_queue.mark_started, job_queue.complete = _start, _complete
    asyncio.run(runner._run_job(job, asyncio.Event()))

    assert len(starts) == 4, "the start write is retried before giving up"
    assert completes and completes[-1][:2] == (job.id, JobStatus.failed)
    assert completes[-1][2].startswith("runner_error")
    assert job.id not in runner._ACTIVE


@_patched
def test_when_even_the_failure_cannot_be_recorded_nothing_escapes():
    """DB fully down: the task must still end cleanly and forget the job, so the
    self-check (which sees it is no longer driven) can release the row later."""
    job = _job()
    runner._TENANT_NAMES[TENANT] = "Dobra"

    async def _down(*a, **k):
        raise ConnectionError("pooler down")

    job_queue.mark_started = job_queue.complete = _down
    asyncio.run(runner._run_job(job, asyncio.Event()))      # must not raise
    assert job.id not in runner._ACTIVE


@_patched
def test_a_write_that_fails_twice_then_lands_is_not_an_error():
    calls = []

    async def _flaky(db):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("blip")
        return "ok"

    assert asyncio.run(runner._job_write("test", _flaky)) == "ok"
    assert len(calls) == 3


# ── a failed claim does not take the runner down ────────────────────────────

def test_a_claim_that_errors_is_logged_and_the_loop_carries_on():
    saved = (runner.AsyncSessionLocal, job_queue.claim_one,
             runner.settings.RUNNER_POLL_SECONDS)
    claims = []

    async def _claim(db, lane, worker):
        claims.append(lane)
        raise ConnectionError("pooler: ECHECKOUTTIMEOUT")

    async def _main():
        shutdown = asyncio.Event()
        asyncio.get_running_loop().call_later(0.25, shutdown.set)
        await runner._consume(shutdown, {"cm_bid": 1})

    runner.AsyncSessionLocal = lambda: _Session()
    job_queue.claim_one = _claim
    runner.settings.RUNNER_POLL_SECONDS = 0.05
    try:
        asyncio.run(_main())                                  # returns; does not raise
    finally:
        (runner.AsyncSessionLocal, job_queue.claim_one,
         runner.settings.RUNNER_POLL_SECONDS) = saved
    assert len(claims) >= 2, "it kept polling after the failed claim"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} stuck-job protection tests passed.")
