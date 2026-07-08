import sys
from loguru import logger

logger.remove()

_CONSOLE_FMT = "{time:HH:mm:ss} | {level:<5} | {message}"

# Kept so callers (e.g. the scrape progress bar) can temporarily silence the
# console without touching the file sink.
CONSOLE_SINK = logger.add(sys.stdout, level="INFO", format=_CONSOLE_FMT, colorize=True)

logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)


def mute_console() -> None:
    """Drop the stdout INFO sink (the file sink stays). Used while a live progress
    bar owns the terminal, so per-line logs don't scribble over it."""
    global CONSOLE_SINK
    if CONSOLE_SINK is not None:
        logger.remove(CONSOLE_SINK)
        CONSOLE_SINK = None


def unmute_console() -> None:
    """Restore the stdout INFO sink removed by mute_console()."""
    global CONSOLE_SINK
    if CONSOLE_SINK is None:
        CONSOLE_SINK = logger.add(sys.stdout, level="INFO", format=_CONSOLE_FMT, colorize=True)
