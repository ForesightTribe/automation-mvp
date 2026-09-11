from pathlib import Path

from pydantic_settings import BaseSettings

# backend/ — app/core/config.py → core → app → backend. Used for absolute paths
# (logs, cwd) that must not depend on the process's current working directory,
# because systemd starts services with an unrelated CWD.
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "Foresight API"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/foresight"

    SECRET_KEY: str = "change-me-in-production"
    ENCRYPTION_KEY: str = ""  # Generate with: Fernet.generate_key().decode()

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Engine pool size PER PROCESS — the most DB connections one process holds at once.
    # Supabase's session pooler caps total clients at 45, and in session mode every OPEN
    # pooled connection counts, idle ones included. The runner spawns each job as its own
    # process with its own pool, and every developer's local backend points at the same
    # pooler, so API + runner + job subprocesses + laptops must all sum under the cap.
    # Deliberately small by default (4 covers the runner and any CLI job) so a forgotten
    # environment is safe; set it explicitly on the API (Render, one worker: 10 — divide
    # across workers if it ever runs more than one). See docs/jobs.md.
    DB_POOL_SIZE: int = 4
    # Postgres terminates a connection that sits idle INSIDE a transaction for longer than
    # this many seconds (0 = never, the server default). A safety net for the API: without
    # it one stalled request pins a pooler slot until its process dies (37 slots for up to
    # ~1 h on 2026-09-11). Set ONLY on the API (Render: 60). Leave 0 on the VM — the scrape
    # loader deliberately holds one long all-or-nothing transaction.
    DB_IDLE_TX_TIMEOUT_S: int = 0

    # --- Job runner (see docs/jobs.md) ---
    # Absolute log root. MUST be absolute: the runner's CWD under systemd is not
    # backend/, so a relative "logs/" would resolve to /logs and fail silently.
    LOG_DIR: str = str(BASE_DIR / "logs")
    # Log verbosity. INFO in prod; set DEBUG to surface the per-request/per-scrape
    # play-by-play (Blinkit client internals, Playwright, httpx) that is otherwise hidden.
    LOG_LEVEL: str = "INFO"
    # How often the consumer polls the queue for claimable work.
    RUNNER_POLL_SECONDS: float = 5.0
    # Concurrency PER LANE. Lanes run in parallel; each is sequential within its
    # slot count. "2 at once" should mean one batch + one live, never two batch
    # scrapes competing for RAM and the same IP — so tune per lane, not globally.
    LANE_SLOTS: dict[str, int] = {
        "batch": 1,
        "dashboard": 1,
        "live": 1,
        "interactive": 1,
        "cm_bid": 1,               # Campaign Manager — bid, isolated
        "cm_ops": 1,               # Campaign Manager — budget / sync / set-budget
        # No slots for the retired v1 lanes (budget_scheduler / bid_optimizer /
        # sync_campaign_data). The Lane enum keeps those members so historical job rows
        # still read, but nothing can be queued into them any more, so they need no
        # capacity. A lane absent here simply never gets claimed.
    }
    # A job whose subprocess runs longer than its type's ceiling is killed and
    # marked timeout, so a wedged Chromium can't hold a lane forever. Overrides
    # the per-type defaults in job_types.py; keyed by job_type.
    JOB_TIMEOUT_OVERRIDES: dict[str, int] = {}

    # --- Scheduler (the producer half of the runner; see docs/jobs.md) ---
    # Master switch: run consumer-only by setting this false (schedules stay in the
    # DB but nothing fires). The runner claims/executes regardless.
    SCHEDULER_ENABLED: bool = True
    # How often the producer re-reads job_schedules and enqueues what's due. Also
    # how quickly a schedule edit takes effect.
    SCHEDULER_TICK_SECONDS: float = 60.0
    # A fire more than this late (e.g. the runner was down) counts as MISSED — then
    # the schedule's `catchup` flag decides run-once-on-recovery vs skip.
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = 300

    # --- Platform auto-login (see docs/platform-auth.md) ---
    # The mailbox every marketplace's magic links and OTPs are auto-forwarded to.
    # Unset = auto-login is unavailable and `cli auth login` falls back to
    # prompting a human; nothing else breaks.
    AUTH_INBOX_HOST: str = "imap.gmail.com"
    AUTH_INBOX_USER: str = ""
    AUTH_INBOX_APP_PASSWORD: str = ""   # Gmail App Password, not the account password
    AUTH_INBOX_FOLDER: str = "INBOX"
    # How long to wait for the login mail to arrive before giving up. Generous,
    # because forwarding adds a hop: observed arrival is a few seconds.
    AUTH_INBOX_TIMEOUT_SECONDS: float = 120.0
    # Whether THIS process may perform a platform login. True on the scraper VM;
    # set false on Render. Blinkit is India-geo, so a login from Render's US IP
    # minutes before the same account is used from Mumbai is exactly the pattern
    # fraud heuristics look for. With this false, ensure() raises SessionExpired
    # instead of quietly logging in from the wrong country — a loud failure beats
    # a silent account flag. Refresh and probe are unaffected (no login, no IP
    # sensitivity); the API should ENQUEUE an auth.refresh job, never log in.
    AUTH_ALLOW_LOGIN: bool = True

    # Marketplaces with real, trusted data today. Everything else is shown but
    # gated as "not connected" in the UI (no real scrapers yet). Superseded by
    # reference_service.list_marketplaces(), which derives `connected` from
    # actual scrape history instead — kept here for reference/rollback, not read
    # anywhere in the app.
    CONNECTED_MARKETPLACES: list[str] = ["blinkit"]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
