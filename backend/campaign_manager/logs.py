"""Structured, dry-run-aware logging for the campaign manager (docs §12.2).

Every event binds structured fields (via loguru's `logger.bind`, so they become
filterable in Cloud Logging) AND emits a readable message, so a human tailing the
per-run log sees exactly what happened. Every line records `dry_run` and, in dry
mode, a `[DRY-RUN]` prefix — so there is never ambiguity about whether a run touched
Blinkit for real.

Event vocabulary (one run):
  run.start → session.ok|expired → per item: decision
            → around each write: write.intent → write.guardrail → write.result
            → run.summary
Levels → severity: INFO normal · WARNING skip/hold/guardrail-trip/no-op · ERROR
fail/rejected-write. So `severity>=WARNING` surfaces everything alert-worthy.
"""
import uuid
from typing import Any

from app.utils.logger import logger


def new_run_id() -> str:
    """Short id correlating every line of one run."""
    return uuid.uuid4().hex[:8]


def _prefix(dry_run: bool) -> str:
    return "[DRY-RUN] " if dry_run else ""


def _emit(level: str, event: str, dry_run: bool, msg: str, **fields: Any) -> None:
    bound = logger.bind(cm_event=event, dry_run=dry_run, **fields)
    getattr(bound, level)(f"{_prefix(dry_run)}{event} · {msg}")


def run_start(run_id: str, job: str, tenant, *, dry_run: bool, **fields: Any) -> None:
    _emit("info", "run.start", dry_run, f"{job} tenant={tenant}",
          run_id=run_id, job=job, tenant=str(tenant), **fields)


def session_ok(run_id: str, *, dry_run: bool) -> None:
    _emit("info", "session.ok", dry_run, "Blinkit session loaded", run_id=run_id)


def session_expired(run_id: str, *, dry_run: bool) -> None:
    _emit("error", "session.expired", dry_run,
          "Blinkit session expired — re-auth with `cli auth blinkit`", run_id=run_id)


def decision(run_id: str, *, dry_run: bool, campaign_id, verdict: str, reason: str,
             keyword: str | None = None, **fields: Any) -> None:
    who = f"campaign={campaign_id}" + (f" kw={keyword!r}" if keyword else "")
    _emit("info", "decision", dry_run, f"{who} → {verdict} ({reason})",
          run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          verdict=verdict, reason=reason, **fields)


def write_intent(run_id: str, *, dry_run: bool, campaign_id, what: str, old, new,
                 keyword: str | None = None) -> None:
    who = f"campaign={campaign_id}" + (f" kw={keyword!r}" if keyword else "")
    _emit("info", "write.intent", dry_run, f"{who} {what} {old}→{new}",
          run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          action=what, old=old, new=new)


def write_guardrail(run_id: str, *, dry_run: bool, campaign_id, passed: bool,
                    reason: str | None = None) -> None:
    verdict = "PASS" if passed else f"REJECT ({reason})"
    _emit("info" if passed else "warning", "write.guardrail", dry_run,
          f"campaign={campaign_id} {verdict}",
          run_id=run_id, campaign_id=campaign_id, passed=passed, reason=reason)


def write_result(run_id: str, *, dry_run: bool, campaign_id, applied: bool,
                 detail: str = "") -> None:
    if dry_run:
        msg, level = f"campaign={campaign_id} would-apply (dry-run, not sent)", "info"
    elif applied:
        msg, level = f"campaign={campaign_id} applied {detail}".strip(), "info"
    else:
        msg, level = f"campaign={campaign_id} FAILED {detail}".strip(), "error"
    _emit(level, "write.result", dry_run, msg,
          run_id=run_id, campaign_id=campaign_id, applied=applied)


def run_summary(run_id: str, job: str, *, dry_run: bool, processed: int,
                applied: int, skipped: int, errors: int) -> None:
    _emit("info" if not errors else "warning", "run.summary", dry_run,
          f"{job} processed={processed} applied={applied} skipped={skipped} errors={errors}",
          run_id=run_id, job=job, processed=processed, applied=applied,
          skipped=skipped, errors=errors)
