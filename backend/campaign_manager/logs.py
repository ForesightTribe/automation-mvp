"""Structured, dry-run-aware logging for the campaign manager.

Two audiences, one call:

- **A human tailing the run** reads plain sentences. The engine narrates what it is doing
  and why — no event names, no `campaign=…` repeated on every line, no run id in the tag.
  Runs are sequential (one slot in the `cm_bid` lane), so context set by a block header
  holds for the lines beneath it and a run reads top to bottom.
- **Cloud Logging** reads the structured fields. `cm_event`, `run_id`, `campaign_id`,
  `keyword`, `dry_run` are all still bound on every line — they simply stopped being
  printed. Filtering by run or event is unaffected.

Levels → severity: INFO normal · WARNING skip/hold/guardrail-trip/no-op · ERROR
fail/rejected-write. So `severity>=WARNING` surfaces everything alert-worthy.

Dry-run marking changed deliberately: it used to prefix EVERY line, which was noise on the
90% of lines that never write anything. Now the run header says it loudly once and only the
lines that would have touched the marketplace carry `[DRY-RUN]` — the one place ambiguity
would actually be dangerous.
"""
import uuid
from typing import Any

from app.utils.logger import logger

_TAG = "cm"
_INDENT = "      "                      # rule-detail lines sit under their block header

# Job key → how it reads in the run header.
_JOB_TITLES = {
    "bid_optimizer": "Bid optimizer",
    "bid_reset": "Bid reset",
    "budget_scheduler": "Budget scheduler",
    "set_budget": "Set budget",
    "set_activation": "Set activation",
    "reconcile": "Reconcile",
}


def new_run_id() -> str:
    """Short id correlating every line of one run."""
    return uuid.uuid4().hex[:8]


def _prefix(dry_run: bool) -> str:
    return "[DRY-RUN] " if dry_run else ""


def _emit(level: str, event: str, dry_run: bool, msg: str, *, indent: bool = False,
          **fields: Any) -> None:
    bound = logger.bind(tag=_TAG, cm_event=event, dry_run=dry_run, **fields)
    getattr(bound, level)(f"{_INDENT if indent else ''}{msg}")


# ── Run frame ────────────────────────────────────────────────────────────────

def run_start(run_id: str, job: str, tenant, *, dry_run: bool,
              tenant_name: str | None = None, **fields: Any) -> None:
    title = _JOB_TITLES.get(job, job.replace("_", " ").capitalize())
    banner = f"─── {title} · run {run_id} ───"
    if dry_run:
        banner = f"─── {title} · run {run_id} · DRY RUN, nothing will be written ───"
    _emit("info", "run.start", dry_run, banner,
          run_id=run_id, job=job, tenant=str(tenant), **fields)
    who = f"{tenant_name} ({tenant})" if tenant_name else str(tenant)
    _emit("info", "run.tenant", dry_run, f"Tenant: {who}",
          run_id=run_id, job=job, tenant=str(tenant))


def blank(run_id: str, *, dry_run: bool = False) -> None:
    """A separator between blocks, so a run is scannable rather than a wall."""
    _emit("info", "spacer", dry_run, "", run_id=run_id)


def note(run_id: str, msg: str, *, dry_run: bool = False, level: str = "info") -> None:
    """A run-level line that isn't part of a rule block (counts, readiness, …)."""
    _emit(level, "note", dry_run, msg, run_id=run_id)


def session_ok(run_id: str, *, dry_run: bool, platform: str = "blinkit") -> None:
    # `platform` defaults for the callers that predate a second marketplace. It said
    # "Blinkit session loaded" unconditionally, which is actively misleading in a
    # Zepto run — the one line that tells you WHOSE account you are about to touch.
    _emit("info", "session.ok", dry_run, f"{platform} session loaded",
          run_id=run_id, platform=platform)


def live_armed(run_id: str, *, advertiser: int) -> None:
    _emit("warning", "live.armed", False,
          f"LIVE writes armed — advertiser {advertiser} (stored account config)",
          run_id=run_id, advertiser=advertiser)


def live_refused(run_id: str, *, reason: str) -> None:
    _emit("error", "live.refused", False,
          f"LIVE write refused — {reason}", run_id=run_id, reason=reason)


def session_expired(run_id: str, *, dry_run: bool) -> None:
    _emit("error", "session.expired", dry_run,
          "Blinkit session expired — re-auth with `cli auth blinkit`", run_id=run_id)


def decision(run_id: str, *, dry_run: bool, campaign_id, verdict: str, reason: str,
             keyword: str | None = None, **fields: Any) -> None:
    """Generic per-item decision — used by the budget/activation engines, which have no
    block structure, so the campaign still belongs in the message. The bid engine narrates
    through `rule_header` / `rule_context` / `observed` / `decided` instead."""
    who = f"campaign {campaign_id}" + (f" · {keyword!r}" if keyword else "")
    _emit("info", "decision", dry_run, f"{who} → {verdict} ({reason})",
          run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          verdict=verdict, reason=reason, **fields)


# ── Per-rule narration (the bid engine's block) ─────────────────────────────

def rule_header(run_id: str, *, dry_run: bool, index: int, total: int,
                campaign_name: str | None, campaign_id) -> None:
    name = campaign_name or f"campaign {campaign_id}"
    _emit("info", "rule.start", dry_run, f"[{index}/{total}] {name}  (campaign {campaign_id})",
          run_id=run_id, campaign_id=campaign_id)


def rule_context(run_id: str, *, dry_run: bool, campaign_id, keyword: str, target: int,
                 current_cpm: int, min_bid: int, max_bid: int | None,
                 location_name: str | None, lat: float, lon: float) -> None:
    limits = f"₹{min_bid}–₹{max_bid}" if max_bid else f"₹{min_bid}–none"
    _emit("info", "rule.config", dry_run,
          f'keyword "{keyword}" · target position {target} · current bid ₹{current_cpm} '
          f"· limits {limits}",
          indent=True, run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          target_position=target, current_cpm=current_cpm)
    where = location_name or "default store"
    _emit("info", "rule.store", dry_run, f"measuring at {where} ({lat}, {lon})",
          indent=True, run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          lat=lat, lon=lon)


def observed(run_id: str, *, dry_run: bool, campaign_id, keyword: str, msg: str,
             level: str = "info", **fields: Any) -> None:
    """What the search saw — product counts and where our ad landed."""
    _emit(level, "rule.observed", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword, **fields)


def decided(run_id: str, *, dry_run: bool, campaign_id, keyword: str, msg: str,
            level: str = "info", **fields: Any) -> None:
    """What we are going to do about it, and why — in one sentence."""
    _emit(level, "rule.decision", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword, **fields)


def applied(run_id: str, *, dry_run: bool, campaign_id, keyword: str, ok: bool,
            msg: str) -> None:
    """The outcome of the write. `[DRY-RUN]` lives here and nowhere else — this is the
    only line where confusing 'would have' with 'did' could actually cost money."""
    _emit("info" if ok else "error", "rule.applied", dry_run,
          f"{_prefix(dry_run)}{msg}", indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword, applied=ok)


def write_intent(run_id: str, *, dry_run: bool, campaign_id, what: str, old, new,
                 keyword: str | None = None) -> None:
    # DEBUG, not INFO. `decision` already narrates what is about to happen and
    # `write.result` records what did — an intent line for every write tripled the volume
    # of a normal run without adding a fact. The full audit trail is still one
    # `LOG_LEVEL=DEBUG` away, which is the point of demoting rather than deleting it.
    who = f"campaign={campaign_id}" + (f" kw={keyword!r}" if keyword else "")
    _emit("debug", "write.intent", dry_run, f"{who} {what} {old}→{new}",
          run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          action=what, old=old, new=new)


def write_guardrail(run_id: str, *, dry_run: bool, campaign_id, passed: bool,
                    reason: str | None = None, keyword: str | None = None) -> None:
    # A PASS is the boring case and says nothing a reader needs — DEBUG. A REJECT is the
    # whole reason the guardrail exists, so it stays a WARNING.
    verdict = "PASS" if passed else f"REJECT ({reason})"
    _emit("debug" if passed else "warning", "write.guardrail", dry_run,
          f"campaign={campaign_id} {verdict}",
          run_id=run_id, campaign_id=campaign_id, passed=passed, reason=reason,
          keyword=keyword)


def write_result(run_id: str, *, dry_run: bool, campaign_id, applied: bool,
                 detail: str = "", keyword: str | None = None) -> None:
    """The write outcome for the budget/activation engines. The bid engine reports its own
    via `applied`, which sits inside the rule block."""
    if dry_run:
        msg, level = f"[DRY-RUN] campaign {campaign_id} would apply {detail} — not sent", "info"
    elif applied:
        msg, level = f"campaign {campaign_id} applied {detail}".strip(), "info"
    else:
        msg, level = f"campaign {campaign_id} FAILED {detail}".strip(), "error"
    _emit(level, "write.result", dry_run, msg,
          run_id=run_id, campaign_id=campaign_id, applied=applied, keyword=keyword)


def status_overwrites(run_id: str, *, dry_run: bool, campaign_id, fields: dict) -> None:
    """What a RESTART is about to overwrite (docs/campaign-manager.md §8.4).

    Resuming a campaign re-submits it whole — budget, keywords, bids, pids, dates — so a
    restart built from a stale read silently reverts the bid optimizer's work. WARNING
    level because it is worth noticing even on a healthy run.
    """
    summary = ", ".join(f"{k}={v}" for k, v in sorted(fields.items()))
    _emit("warning", "status.overwrites", dry_run,
          f"campaign={campaign_id} restart re-submits: {summary}",
          run_id=run_id, campaign_id=campaign_id, **{f"ow_{k}": v for k, v in fields.items()})


def reconcile_change(run_id: str, *, dry_run: bool, action: str, name: str,
                     detail: str = "") -> None:
    """One create/update/delete the reconciler made (or would make) to job_schedules.
    `dry_run` here means the reconciler did NOT write the schedule row — it only
    touches our own `job_schedules`, never Blinkit."""
    _emit("info", "reconcile.change", dry_run, f"{action} {name} {detail}".strip(),
          run_id=run_id, action=action, name=name)


def run_summary(run_id: str, job: str, *, dry_run: bool, processed: int,
                applied: int, skipped: int, errors: int,
                seconds: float | None = None, unit: str = "items",
                note: str | None = None) -> None:
    """Closing banner. Zero-valued parts are left out so the line says only what happened."""
    parts = []
    if seconds is not None:
        parts.append(f"Done in {seconds:.0f}s")
    else:
        parts.append("Done")
    parts.append(f"{processed} {unit}")
    if applied:
        parts.append(f"{applied} changed")
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} error" + ("s" if errors != 1 else ""))
    if note:
        parts.append(note)
    _emit("info" if not errors else "warning", "run.summary", dry_run,
          f"─── {' · '.join(parts)} ───",
          run_id=run_id, job=job, processed=processed, applied=applied,
          skipped=skipped, errors=errors, seconds=seconds)
