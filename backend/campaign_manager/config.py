"""Campaign-manager v2 configuration — guardrail bounds + the dry-run default.

Self-contained so the CM doesn't touch the shared app Settings. Every value has a
safe default; override via env only if needed (no new REQUIRED .env keys).
"""
import os


def _flag(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in ("", "0", "false", "no", "off")


# Every CM action is DRY-RUN unless explicitly armed with --live. Fail-safe (D15).
DRY_RUN_DEFAULT: bool = _flag("CM_DRY_RUN_DEFAULT", True)

# Budget guardrails — writes.py rejects a target outside [MIN_BUDGET, MAX_BUDGET].
# A bug computing budget=0 or an absurd value must be REJECTED, never sent.
MIN_BUDGET: float = float(os.getenv("CM_MIN_BUDGET", "1"))
MAX_BUDGET: float = float(os.getenv("CM_MAX_BUDGET", "100000"))

# Rate limit — refuse to write the same campaign more than MAX_WRITES_PER_WINDOW
# times within RATE_WINDOW_MINUTES (catches a runaway loop, à la the every-minute-cron
# incident). Counted from cm_run_log at apply time.
MAX_WRITES_PER_WINDOW: int = int(os.getenv("CM_MAX_WRITES_PER_WINDOW", "12"))
RATE_WINDOW_MINUTES: int = int(os.getenv("CM_RATE_WINDOW_MINUTES", "60"))
