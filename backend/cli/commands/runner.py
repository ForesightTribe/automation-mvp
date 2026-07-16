import asyncio
from pathlib import Path

import typer

from app.core.config import settings
from app.utils.logger import logger
from jobs import runner as runner_service

app = typer.Typer(help="The job runner daemon (see docs/jobs.md).")


@app.command("start")
def start():
    """Run the job runner in the foreground. On the VM this is launched by systemd
    (foresight-runner.service); run it here directly for local testing."""
    # A JSON-serialized sink dedicated to the runner process. The Ops Agent ships
    # this to Cloud Logging, where serialize=True makes job_id/job_type/etc.
    # filterable fields rather than substring searches. Added here (the entry
    # point) so it's configured exactly once per process.
    logger.add(
        str(Path(settings.LOG_DIR) / "runner.log"),
        serialize=True,
        rotation="20 MB",
        retention="14 days",
        level="INFO",
        enqueue=True,      # process/async-safe
    )
    try:
        asyncio.run(runner_service.run())
    except KeyboardInterrupt:
        pass
