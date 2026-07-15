import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

# Absolute log root — see settings.LOG_DIR. Created eagerly so the first write
# never fails on a missing directory (a silent killer under systemd).
_LOG_DIR = Path(settings.LOG_DIR)
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()

logger.add(
    sys.stdout,
    level="INFO",
    format="{time:HH:mm:ss} | {level:<5} | {message}",
    colorize=True,
)

logger.add(
    str(_LOG_DIR / "app.log"),
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)
