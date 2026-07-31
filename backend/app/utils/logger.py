"""One logging pipeline for the whole system.

Everything — our loguru calls AND third-party/stdlib `logging` (the vendored Blinkit
client, Playwright, httpx, uvicorn) — flows through loguru, so there is a single format,
a single set of sinks, and one place to set levels. Without this the app printed two
interleaved formats (`16:15 | INFO | …` from loguru and `INFO:module:…` from stdlib).

Format: `HH:MM:SS | LEVEL | tag | message`, where `tag` is a short context label — the
run id for a campaign-manager run (`cm[a1b2c3]`, bound in `campaign_manager/logs.py`),
otherwise the emitting module's short name. Verbosity is `settings.LOG_LEVEL` (INFO in
prod; DEBUG surfaces the client/Playwright/httpx play-by-play).
"""
import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

_LOG_DIR = Path(settings.LOG_DIR)
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Third-party loggers that flood at their default levels — pinned to WARNING so only
# genuine problems surface. Flip settings.LOG_LEVEL=DEBUG *and* lower these if you need
# the firehose while debugging a network issue.
_NOISY = ("playwright", "httpx", "httpcore", "asyncio", "urllib3", "websockets",
          "uvicorn.access")

_CONSOLE_FMT = "{time:HH:mm:ss} | {level:<7} | {extra[tag]:<11} | {message}"
_FILE_FMT = "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[tag]} | {message}"


class InterceptHandler(logging.Handler):
    """Forward stdlib `logging` records into loguru (the standard loguru recipe), so
    code that uses `logging.getLogger(...)` shares our format + sinks. The record's
    module short-name becomes the `tag`."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        tag = record.name.rsplit(".", 1)[-1] if record.name else "-"
        logger.opt(depth=depth, exception=record.exc_info).bind(tag=tag).log(
            level, record.getMessage()
        )


def _configure() -> None:
    logger.configure(extra={"tag": "app"})       # default tag when none is bound
    logger.remove()
    logger.add(sys.stdout, level=settings.LOG_LEVEL, format=_CONSOLE_FMT, colorize=True)
    logger.add(
        str(_LOG_DIR / "app.log"),
        rotation="10 MB",
        retention="30 days",
        level=settings.LOG_LEVEL,
        format=_FILE_FMT,
    )
    # Route ALL stdlib logging through the InterceptHandler at the root, replacing any
    # handlers a library installed. force=True so a prior basicConfig() can't win.
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.NOTSET, force=True)
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)


_configure()
