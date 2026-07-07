"""Schedule storage helpers — load/save rules and run log."""
import json
from pathlib import Path

SCHEDULES_FILE = Path(__file__).parent / "schedules.json"
LOG_FILE = Path(__file__).parent / "scheduler_log.json"


def load_schedules() -> list[dict]:
    if not SCHEDULES_FILE.exists():
        return []
    return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))


def save_schedules(schedules: list[dict]) -> None:
    SCHEDULES_FILE.write_text(
        json.dumps(schedules, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    return json.loads(LOG_FILE.read_text(encoding="utf-8"))


def append_log(entry: dict) -> None:
    log = load_log()
    log.append(entry)
    LOG_FILE.write_text(
        json.dumps(log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
