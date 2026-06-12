import sys
from loguru import logger

logger.remove()

logger.add(
    sys.stdout,
    level="INFO",
    format="{time:HH:mm:ss} | {level:<5} | {message}",
    colorize=True,
)

logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)
