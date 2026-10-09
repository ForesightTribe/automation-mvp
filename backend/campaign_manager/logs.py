"""Structured, dry-run-aware logging for the campaign manager.

Two audiences, one call:

- **A human tailing the run** reads plain sentences. The engine narrates what it is doing
  and why — no event names, no `campaign=…` repeated on every line, no run id in the tag.
  Runs are sequential (one slot in the `cm_bid` lane), so context set by a block header
  holds for the lines beneath it and a run reads top to bottom.
- **Structured fields** (`cm_event`, `run_id`, `campaign_id`, `keyword`, `dry_run`, and the
  per-store `verdict` / `rank` / `position`) are bound on every line but NOT printed.
  ⚠️ They do not reach Cloud Logging either: a job's output is written to its per-run file
  in the plain-text console format and shipped as text (`foresight_cm_bid` /
  `foresight_cm_ops`, deploy/ops-agent-logging.yaml). Only the runner's own `runner.log` is
  JSON. So in the Logs Explorer you search the MESSAGE text; the queryable per-store record
  is the `cm_bid_store_reads` table.

Levels → severity: INFO normal · WARNING skip/hold/guardrail-trip/no-op · ERROR
fail/rejected-write. So `severity>=WARNING` surfaces everything alert-worthy.

Dry-run marking changed deliberately: it used to prefix EVERY line, which was noise on the
90% of lines that never write anything. Now the run header says it loudly once and only the
lines that would have touched the marketplace say `DRY RUN, not sent` — the one place
ambiguity would actually be dangerous.

CRISP BY DESIGN (2026-10-02). One line per fact, numbers over sentences (`#2`, `₹10 → ₹12`),
and the decision and its outcome on ONE line (`raise ₹10 → ₹12 (+₹2) · #2 vs target #1 ·
applied`). The full sentences still exist — they are the History reasons a client reads in
the dashboard (`cm_run_log`), which this module never touches. Everything about one
automation is indented under its header; run-level lines sit at the margin.
"""
import uuid
from typing import Any

from app.utils.logger import logger

_TAG = "cm"
_INDENT = "  "                          # rule-detail lines sit under their block header

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
    parts = [title, tenant_name or str(tenant)]
    if fields.get("platform"):
        parts.append(str(fields["platform"]))
    parts += ["DRY RUN" if dry_run else "LIVE", f"run {run_id}"]
    _emit("info", "run.start", dry_run, f"── {' · '.join(parts)} ──",
          run_id=run_id, job=job, tenant=str(tenant), **fields)
    # The id behind the name, for whoever needs it — not for the reader of every run.
    _emit("debug", "run.tenant", dry_run, f"tenant {tenant}",
          run_id=run_id, job=job, tenant=str(tenant))


def blank(run_id: str, *, dry_run: bool = False) -> None:
    """A separator between blocks, so a run is scannable rather than a wall."""
    _emit("info", "spacer", dry_run, "", run_id=run_id)


def note(run_id: str, msg: str, *, dry_run: bool = False, level: str = "info",
         indent: bool = False) -> None:
    """A run-level line that isn't part of a rule block (counts, readiness, …). `indent` when
    it is said from INSIDE one (a stock check made for that automation)."""
    _emit(level, "note", dry_run, msg, indent=indent, run_id=run_id)


def session_ok(run_id: str, *, dry_run: bool, platform: str) -> None:
    # `platform` is required — no default marketplace (ZC-D1). It once said "Blinkit
    # session loaded" unconditionally, which is actively misleading in a Zepto run — the
    # one line that tells you WHOSE account you are about to touch.
    # DEBUG: the run header already names the marketplace, and the bid engine's `ready`
    # line says the session is up.
    _emit("debug", "session.ok", dry_run, f"{platform} session loaded",
          run_id=run_id, platform=platform)


def _count(n: int, unit: str) -> str:
    """`1 automation`, `2 automations` — `unit` is given plural."""
    return f"{n} {unit[:-1] if n == 1 and unit.endswith('s') else unit}"


def _short_id(value) -> str:
    """An advertiser id as a reader needs it — a UUID's first block is enough to recognise."""
    s = str(value)
    return s.split("-")[0] if "-" in s else s


def live_armed(run_id: str, *, advertiser: int, quiet: bool = False) -> None:
    """`quiet` when the caller says it in its own `ready` line (the bid engine)."""
    _emit("debug" if quiet else "warning", "live.armed", False,
          f"LIVE armed · advertiser {_short_id(advertiser)}",
          run_id=run_id, advertiser=advertiser)


def ready(run_id: str, *, dry_run: bool, automations: int, advertiser=None,
          unit: str = "automations") -> None:
    """The bid engine's one setup line: session up, armed (or not), how much work there is.
    WARNING on a live run — the level the separate "LIVE armed" line had, so filtering on
    severity finds live runs exactly as before."""
    armed = (f" · LIVE armed (advertiser {_short_id(advertiser)})"
             if advertiser is not None and not dry_run else "")
    _emit("warning" if armed else "info", "run.ready", dry_run,
          f"ready · session ok{armed} · {_count(automations, unit)} in window",
          run_id=run_id, automations=automations)


def live_refused(run_id: str, *, reason: str) -> None:
    _emit("error", "live.refused", False,
          f"LIVE write refused — {reason}", run_id=run_id, reason=reason)


def session_expired(run_id: str, *, dry_run: bool, platform: str) -> None:
    # Named the marketplace unconditionally ("Blinkit session expired — re-auth with `cli
    # auth blinkit`") — on a Zepto run that is the wrong account AND a command that does
    # not exist. Same bug `session_ok` had.
    _emit("error", "session.expired", dry_run,
          f"{platform.title()} session expired · re-auth: python -m cli auth login "
          f"{platform} -t <tenant>",
          run_id=run_id, platform=platform)


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
                campaign_name: str | None, campaign_id, keyword: str | None = None,
                match_type: str | None = None, target: int | None = None) -> None:
    """`[1/2] Foresight | Sour Cream (TP) · #2443333 · "sour cream" EXACT · target Ad #1`."""
    parts = [f"[{index}/{total}] {campaign_name or f'campaign {campaign_id}'}",
             f"#{campaign_id}"]
    if keyword:
        parts.append(f'"{keyword}"' + (f" {match_type.upper()}" if match_type else ""))
    if target is not None:
        parts.append(f"target Ad #{target}")
    _emit("info", "rule.start", dry_run, " · ".join(parts),
          run_id=run_id, campaign_id=campaign_id, keyword=keyword)


def rule_context(run_id: str, *, dry_run: bool, campaign_id, keyword: str, target: int,
                 current_cpm: int, min_bid: int, max_bid: int | None,
                 location_name: str | None, lat: float, lon: float,
                 store_source: str | None = None, store_count: int = 1,
                 rotation: list[str] | None = None,
                 store_names: list[str] | None = None) -> None:
    """`bid ₹10 (₹10–50) · stores: J. P. Nagar → VIJAY NAGAR → Kadugodi (client set)`.

    `rotation` = a rotating marketplace's set, one store per check, in turn (→). Otherwise
    `store_names` (or the single `location_name`) — every store read each tick (commas)."""
    limits = f"₹{min_bid}–{max_bid}" if max_bid else f"₹{min_bid}+"
    why = _STORE_SOURCE.get(store_source)
    tail = f" ({why})" if why else ""
    if rotation:
        where = f"stores: {' → '.join(rotation)}{tail}"
    elif store_names and len(store_names) > 1:
        where = f"stores: {', '.join(store_names)}{tail} · worst counts"
    else:
        where = f"store: {location_name or 'default store'}{tail}"
    _emit("info", "rule.config", dry_run, f"bid ₹{current_cpm} ({limits}) · {where}",
          indent=True, run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          target_position=target, current_cpm=current_cpm, lat=lat, lon=lon,
          store_source=store_source, store_count=store_count)


# Why a rule measured where it did — `bid.measurement_stores`' `source`, in words. A store
# that moved because someone changed a city's setting should be explainable from the log.
_STORE_SOURCE = {
    "tenant": "client set",
    "global": "default set",
    "rule": "the automation's store",
    "default": "no store set — Bengaluru fallback",
}


def store_reading(run_id: str, *, dry_run: bool, campaign_id, keyword: str, reading,
                  many: bool = False, of: int | None = None) -> None:
    """What one measurement store showed this tick (campaign_manager/coverage.py `Reading`):
    `J. P. Nagar (1/3): Ad #2 · position 5 · ads at 2,5,6,9 · organic 1`. `of` = how many
    stores the rule has, so the line says which one this is (`many` is the older yes/no form
    of the same thing)."""
    s = reading.store
    name = getattr(s, "label", "") or getattr(s, "merchant_id", "") or "store"
    n = of if of is not None else (2 if many else 1)
    if n > 1:
        name = f"{name} ({getattr(s, 'rank', 1)}/{n})" if of else f"{name} ({getattr(s, 'rank', 1)})"
    verdict = reading.verdict
    page = _page_said(reading)
    if verdict == "sponsored":
        pos = getattr(reading, "page_position", None)
        msg = (f"{name}: Ad #{reading.position:g}"
               + (f" · position {pos}" if pos is not None else "") + page)
    elif verdict == "absent":
        msg = f"{name}: no ad slot — {reading.detail}{page}"
        if reading.eligibility == "unknown":
            msg += " · stock unknown, still counts"
    elif verdict == "skipped":
        msg = f"{name}: can't sell — {reading.detail}"
    elif verdict == "untrusted":
        msg = f"{name}: not counted — {reading.detail}"
    elif verdict == "gave_up":
        msg = f"{name}: not chased — {reading.detail}"
    else:
        msg = f"{name}: unreadable — {reading.detail}"
    _emit("info" if verdict in ("sponsored", "absent") else "warning", "rule.store_reading",
          dry_run, msg, indent=True, run_id=run_id, campaign_id=campaign_id, keyword=keyword,
          merchant_id=getattr(s, "merchant_id", ""), rank=getattr(s, "rank", 1),
          verdict=verdict, eligibility=reading.eligibility,
          ad_slot=reading.position if verdict == "sponsored" else None,
          position=getattr(reading, "page_position", None))


def _page_said(reading) -> str:
    """` · ads at 2,5,6 · organic 1,4` — the page around our slot, when we saw it."""
    ads = tuple(getattr(reading, "ad_positions", ()) or ())
    organic = tuple(getattr(reading, "organic_positions", ()) or ())
    out = f" · ads at {','.join(map(str, ads))}" if ads else ""
    if reading.verdict in ("sponsored", "absent") and not ads:
        out = " · no ads on the page"
    if organic:
        out += f" · organic {','.join(map(str, organic))}"
    return out


def context(run_id: str, *, dry_run: bool, campaign_id, msg: str,
            keyword: str | None = None) -> None:
    """The automation's own configuration, under its block header.

    The budget engine's counterpart to `rule_context` — that one takes the bid engine's
    fixed fields (target position, limits, measurement store); a schedule's configuration
    is a different shape, so it arrives already worded.
    """
    _emit("info", "rule.config", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword)


def observed(run_id: str, *, dry_run: bool, campaign_id, msg: str,
             keyword: str | None = None, level: str = "info", **fields: Any) -> None:
    """What the marketplace showed us — the bid engine's search result, the budget
    engine's campaign status and current budget. `keyword` is optional: a budget
    decision is per campaign, not per keyword."""
    _emit(level, "rule.observed", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword, **fields)


def decided(run_id: str, *, dry_run: bool, campaign_id, msg: str,
            keyword: str | None = None, level: str = "info", **fields: Any) -> None:
    """What we are going to do about it, and why — in one sentence."""
    _emit(level, "rule.decision", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, keyword=keyword, **fields)


def applied(run_id: str, *, dry_run: bool, campaign_id, ok: bool, msg: str,
            keyword: str | None = None) -> None:
    """The decision AND the outcome of its write, on one line. The caller's `msg` ends in
    `applied`, `DRY RUN, not sent` or `NOT applied — why` (see `bid._outcome`) — the only
    line where confusing 'would have' with 'did' could actually cost money."""
    _emit("info" if ok else "error", "rule.applied", dry_run, msg, indent=True,
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
                    reason: str | None = None, keyword: str | None = None,
                    level: str | None = None) -> None:
    """A guardrail's verdict on a write.

    A PASS is the boring case and says nothing a reader needs — DEBUG. A REJECT is the whole
    reason the guardrail exists, so it is a WARNING, worded as a refusal in the block rather
    than as `campaign=583049 REJECT (…)`. `level` overrides that for a rejection that is
    routine rather than notable — a no-op write is the hourly poll's normal answer, and at
    WARNING it drowned the run.
    """
    if passed:
        _emit(level or "debug", "write.guardrail", dry_run, "guardrail passed", indent=True,
              run_id=run_id, campaign_id=campaign_id, passed=True, reason=None,
              keyword=keyword)
        return
    _emit(level or "warning", "write.guardrail", dry_run, f"refused — {reason}", indent=True,
          run_id=run_id, campaign_id=campaign_id, passed=False, reason=reason,
          keyword=keyword)


def write_result(run_id: str, *, dry_run: bool, campaign_id, applied: bool, subject: str,
                 new: str, old: str | None = None, reason: str | None = None,
                 keyword: str | None = None) -> None:
    """The write outcome for the budget/activation engines, in a sentence.

    The bid engine reports its own via `applied`; this is the same line for a value that
    belongs to a campaign rather than a keyword, so both engines read alike. It used to
    print `campaign 583049 applied ₹1202 → ₹802` — the campaign id repeated from the block
    header above it, and an arrow where a verb belongs. A FAILED write now says what the
    value still IS, which is the fact a reader is actually looking for, and why.
    """
    was = f" (was {old})" if old and old != new else ""
    if dry_run:
        msg, level = f"[DRY-RUN] would change {subject} to {new}{was} — not sent", "info"
    elif applied:
        msg, level = f"applied — {subject} is now {new}{was}", "info"
    else:
        still = f" — {subject} is still {old}" if old else ""
        msg, level = (f"not applied{still}" + (f" ({reason})" if reason else ""), "error")
    _emit(level, "write.result", dry_run, msg, indent=True,
          run_id=run_id, campaign_id=campaign_id, applied=applied, keyword=keyword)


def status_overwrites(run_id: str, *, dry_run: bool, campaign_id, fields: dict) -> None:
    """What a RESTART is about to overwrite (docs/campaign-manager.md §8.4).

    Resuming a campaign re-submits it whole — budget, keywords, bids, pids, dates — so a
    restart built from a stale read silently reverts the bid optimizer's work. WARNING
    level because it is worth noticing even on a healthy run.
    """
    summary = ", ".join(f"{k}={v}" for k, v in sorted(fields.items()))
    _emit("warning", "status.overwrites", dry_run,
          f"restarting re-submits the whole campaign: {summary}", indent=True,
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
                note: str | None = None, skipped_word: str = "skipped") -> None:
    """Closing banner. Zero-valued parts are left out so the line says only what happened."""
    parts = [f"done {seconds:.0f}s" if seconds is not None else "done",
             _count(processed, unit)]
    if applied:
        parts.append(f"{applied} changed")
    if skipped:
        parts.append(f"{skipped} {skipped_word}")
    if errors:
        parts.append(f"{errors} error" + ("s" if errors != 1 else ""))
    if note:
        parts.append(note)
    _emit("info" if not errors else "warning", "run.summary", dry_run,
          f"── {' · '.join(parts)} ──",
          run_id=run_id, job=job, processed=processed, applied=applied,
          skipped=skipped, errors=errors, seconds=seconds)
