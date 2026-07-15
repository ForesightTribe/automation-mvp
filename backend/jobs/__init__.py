"""The job/runner/scheduler subsystem — a top-level peer package (sibling to
`app/`, `cli/`, `scraper/`, `ad_campaigns/`).

- `queue`     — DB operations for the `jobs` queue (enqueue, atomic claim, reaper)
- `types`     — the job-type registry (type → lane, timeout, argv builder)
- `runner`    — the consumer daemon (subprocess dispatch, logging, RSS, shutdown)
- `scheduler` — the cron producer that enqueues on a schedule (Phase 2)
- `monitor`   — the deadman/heartbeat checks (Phase 3)

The `Job` SQLModel lives in `app/models/job.py` (models are shared and Alembic
autogenerates from `app.models`). CLI commands (`cli/commands/`) and future API
routes (`app/routes/`) are thin wrappers that import from here. See docs/jobs.md.
"""
