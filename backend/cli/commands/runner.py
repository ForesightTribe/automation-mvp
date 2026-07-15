import asyncio

import typer

from jobs import runner as runner_service

app = typer.Typer(help="The job runner daemon (see docs/jobs.md).")


@app.command("start")
def start():
    """Run the job runner in the foreground. On the VM this is launched by systemd
    (foresight-runner.service); run it here directly for local testing."""
    try:
        asyncio.run(runner_service.run())
    except KeyboardInterrupt:
        pass
