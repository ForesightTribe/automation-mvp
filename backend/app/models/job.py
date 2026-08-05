import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column, Index, LargeBinary, UniqueConstraint, text

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class Lane(str, Enum):
    """Which parallel queue a job runs in. Lanes run concurrently; each is
    sequential within its slot count. A job's lane is a property of its TYPE, not
    caller-chosen — see jobs/types.py. The point: a live control loop
    (bid optimizer) must never queue behind a 5-hour batch scrape. See docs/jobs.md.
    """

    batch = "batch"                        # public scrapes — hours long, nobody waiting
    dashboard = "dashboard"                # marketing/seller/scorecard — minutes, scheduled
    live = "live"                          # generic live lane
    interactive = "interactive"            # explorer/heartbeat/cm-reconcile — no browser, prompt
    budget_scheduler = "budget_scheduler"  # v1 ads.* — deprecated at cutover
    bid_optimizer = "bid_optimizer"        # v1 ads.* — deprecated at cutover
    sync_campaign_data = "sync_campaign_data"  # v1 ads.* — deprecated at cutover
    cm_bid = "cm_bid"                      # Campaign Manager v2 — bid optimizer, isolated (latency-critical)
    cm_ops = "cm_ops"                      # Campaign Manager v2 — budget / sync / set-budget (share; latency-tolerant)


class Job(SQLModel, table=True):
    """One unit of work: the queue row AND the run record.

    Every run — a CLI command, a scheduler tick, or a future UI button — is a row
    here. The runner daemon drains the queue by spawning the scrape as a subprocess
    (the exact `python -m cli …` you would type by hand) and writes the outcome back.

    This sits ABOVE `scrape_jobs`/`explorer_runs`, which keep internal scrape
    progress + `--resume` state untouched; `ref_job_id` links to that detail row.
    """

    __tablename__ = "jobs"

    __table_args__ = (
        # Consumer claim path: pending jobs of a lane, oldest eligible first.
        Index("idx_jobs_lane_claim", "lane", "status", "priority", "scheduled_for"),
        # Note: `idx_jobs_tenant` is already taken by the scrape_jobs table — index
        # names are schema-global in Postgres, so this one is namespaced distinctly.
        Index("idx_jobs_queue_tenant", "tenant_id", "created_at"),
        # Overlap guard: at most one active (pending|running) job per (type, tenant).
        # Partial index — NULL tenants (explorer) are distinct, so not deduped.
        Index(
            "uq_jobs_active",
            "job_type",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_type: str
    lane: Lane = Lane.batch
    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id")
    params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    status: JobStatus = JobStatus.pending
    priority: int = 100                       # lower runs first, within a lane
    scheduled_for: datetime = Field(default_factory=now_ist)
    schedule_id: int | None = Field(default=None, foreign_key="job_schedules.id")  # set when enqueued by the scheduler

    attempts: int = 0
    max_attempts: int = 1                     # scrapers already retry internally

    locked_at: datetime | None = None
    locked_by: str | None = None              # "hostname:pid" of the claiming runner

    argv: str | None = None                   # exact command run — copy-paste to reproduce
    exit_code: int | None = None
    log_path: str | None = None
    peak_rss_mb: int | None = None            # child + descendants; sizes lane slots
    ref_job_id: uuid.UUID | None = None       # → scrape_jobs.id / explorer_runs.id
    error: str | None = None                  # auth_expired / oom / timeout / runner_died / …

    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_ist)


class ScrapeJob(SQLModel, table=True):
    __tablename__ = "scrape_jobs"

    __table_args__ = (
        Index("idx_jobs_tenant", "tenant_id", "platform"),
        Index("idx_jobs_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "blinkit"
    dashboard: str
    status: JobStatus = JobStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    records_written: int = 0
    created_at: datetime = Field(default_factory=now_ist)


class JobSchedule(SQLModel, table=True):
    """A recurring OR one-shot job definition — "run this job_type on this cron",
    or "run it once at this time".

    The scheduler (the producer half of the runner) reads enabled rows, and when
    `next_run_at` is due it ENQUEUES a Job (never runs anything itself). Editing a
    row takes effect within one producer tick — schedules live here, not in a
    crontab, so the future UI can manage them without SSH. See docs/jobs.md.

    Two shapes share this table (Campaign Manager v2 needs both — a recurring budget
    window and a one-shot expiry cleanup ride the same scheduler):
    - `repeat=True` (recurring): `cron` set; after firing, `next_run_at` advances to
      the next cron occurrence.
    - `repeat=False` (one-shot): `cron` is NULL, `next_run_at` is an explicit fire
      time; after firing it disables itself instead of re-arming.
    """

    __tablename__ = "job_schedules"

    __table_args__ = (
        Index("idx_job_schedules_due", "enabled", "next_run_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str
    job_type: str
    tenant_id: uuid.UUID | None = Field(default=None, foreign_key="tenants.id")
    params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    cron: str | None = None                   # 5-field crontab (IST); NULL for one-shots
    repeat: bool = True                        # True=recurring (re-arm via cron); False=one-shot (fire once, then disable)
    priority: int = 100                       # passed through to the enqueued job
    enabled: bool = True
    # If the runner was down at a fire time: run the missed occurrence once on
    # recovery (True), or skip it and wait for the next (False). See docs/jobs.md.
    catchup: bool = False

    last_enqueued_at: datetime | None = None
    next_run_at: datetime | None = None       # precomputed from cron; drives the poller + the UI
    created_at: datetime = Field(default_factory=now_ist)


class PlatformSession(SQLModel, table=True):
    __tablename__ = "platform_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", name="uq_platform_sessions_tenant_platform"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str
    encrypted_session: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    # Liveness, so expiry is visible without launching a browser. The row's mere
    # existence used to be the only signal, which is why a session that died on
    # 2026-07-21 kept reporting "Session exists" for days.
    status: str = "unknown"                    # active | expired | unknown
    last_login_at: datetime | None = None      # last full login (consumed a secret)
    last_validated_at: datetime | None = None  # last time it was proven working
    consecutive_failures: int = 0              # resets on success; drives alerting
    last_error: str | None = None

    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)


class PlatformCredential(SQLModel, table=True):
    """What a tenant needs to BEGIN a login — the input, not the result.

    Kept separate from PlatformSession on purpose. Credentials are long-lived and
    entered by a human; sessions are short-lived, machine-generated, and rotate
    constantly. Mixing them means every token refresh rewrites the row holding
    the password.

    Blinkit's dashboards are passwordless (magic link / OTP), so `encrypted_password`
    is null for them. Zepto uses email + password, which is why this exists now
    rather than being retrofitted later.
    """

    __tablename__ = "platform_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "platform", name="uq_platform_credentials_tenant_platform"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str

    # Plaintext: PII, not a secret, and it must stay readable to render status
    # and to decide whether a tenant can auto-login at all.
    login_email: str

    # Fernet, same key as encrypted_session. Null where the platform has no password.
    encrypted_password: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )

    # Anything else a marketplace needs to start a login (sub-account id, portal
    # code). JSON-encoded, so a new platform needs no schema change.
    extra: str | None = None

    created_at: datetime = Field(default_factory=now_ist)
    updated_at: datetime = Field(default_factory=now_ist)
