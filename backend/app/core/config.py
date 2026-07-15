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

    # Engine pool size PER PROCESS. Supabase's pooler caps total clients (set to
    # 25). The runner spawns each scrape as its own process, each with its own
    # engine + pool, so on the VM keep this small (3–5) to stay within budget:
    # API + runner + N concurrent scrape subprocesses must sum under the cap.
    DB_POOL_SIZE: int = 10

    # --- Job runner (see docs/jobs.md) ---
    # Absolute log root. MUST be absolute: the runner's CWD under systemd is not
    # backend/, so a relative "logs/" would resolve to /logs and fail silently.
    LOG_DIR: str = str(BASE_DIR / "logs")
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
    }
    # A job whose subprocess runs longer than its type's ceiling is killed and
    # marked timeout, so a wedged Chromium can't hold a lane forever. Overrides
    # the per-type defaults in job_types.py; keyed by job_type.
    JOB_TIMEOUT_OVERRIDES: dict[str, int] = {}

    # Marketplaces with real, trusted data today. Everything else is shown but
    # gated as "not connected" in the UI (no real scrapers yet). Stopgap until
    # connectivity is derived from successful scrape_jobs per platform.
    CONNECTED_MARKETPLACES: list[str] = ["blinkit"]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
