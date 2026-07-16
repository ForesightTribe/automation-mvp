"""Log hygiene — the `maint.log_cleanup` job.

Per-run job logs grow forever; a full disk on the VM causes bizarre silent
failures. This prunes `logs/jobs/<date>/*.log` older than a retention window and
tidies up the emptied date folders. Runs as a normal job (batch lane).
"""

import time
from pathlib import Path

from app.core.config import settings


def prune_logs(days: int = 14, dry_run: bool = False) -> tuple[int, int]:
    """Delete per-run log files older than `days`. Returns (files, bytes_freed).
    `dry_run` counts what would go without deleting."""
    root = Path(settings.LOG_DIR) / "jobs"
    if not root.exists():
        return 0, 0

    cutoff = time.time() - days * 86400
    files = freed = 0
    for f in root.rglob("*.log"):
        try:
            st = f.stat()
        except FileNotFoundError:
            continue
        if st.st_mtime < cutoff:
            freed += st.st_size
            files += 1
            if not dry_run:
                f.unlink(missing_ok=True)

    if not dry_run:
        # Remove now-empty date directories.
        for d in root.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    return files, freed
