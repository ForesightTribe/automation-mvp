"""The job-type registry.

One entry per job type: which lane it runs in, its runtime ceiling, which params it
accepts, and how to turn those params into CLI arguments. Adding a job type is one
entry here — the runner, the queue, and (later) the API need no changes.

`build_args(tenant_id, params)` returns the args that follow `python -m cli`, i.e.
the exact command you would type by hand. Keep these thin: all real behaviour lives
in the existing CLI commands.
"""

import uuid
from typing import Any, Callable, NamedTuple

from app.models.job import Lane


class JobTypeSpec(NamedTuple):
    lane: Lane
    timeout_s: int
    # (tenant_id, params) -> args after `python -m cli`
    build_args: Callable[[uuid.UUID | None, dict[str, Any]], list[str]]
    needs_tenant: bool = True
    # Accepted param names — used to reject typos and to document the type.
    param_keys: tuple[str, ...] = ()
    # What to call this in a log line, an email, or a UI — written for someone who
    # does not know the codebase. `scrape.blinkit_marketing` is a registry key, not a
    # description; "Blinkit ads scrape" is what the run actually is. Every
    # human-facing surface reads this instead of the dotted type name.
    label: str = ""


# Values that mean "off" for a boolean param. Without this, `sales=false` would be a
# non-empty string and therefore truthy — silently turning the flag ON.
_FALSEY = {"", "0", "false", "no", "off"}


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() not in _FALSEY


def _opt(args: list[str], flag: str, value: Any) -> None:
    """Append `flag value` only when value is set (skips None / '' / missing)."""
    if value not in (None, ""):
        args.extend([flag, str(value)])


def _flag(args: list[str], flag: str, value: Any) -> None:
    """Append a bare `flag` only when the value is truthy (see _FALSEY)."""
    if _truthy(value):
        args.append(flag)


def parse_params(pairs: list[str] | None, spec: JobTypeSpec) -> dict[str, str]:
    """Turn ["city=delhi ncr", "workers=5"] into a dict, rejecting unknown keys.

    Values keep spaces: only the FIRST '=' splits, and the subprocess is spawned with
    an argv list (no shell), so `city=delhi ncr` survives end to end.
    """
    out: dict[str, str] = {}
    for kv in pairs or []:
        if "=" not in kv:
            raise ValueError(
                f"expected key=value, got {kv!r}"
                + (f". Valid params: {', '.join(spec.param_keys)}" if spec.param_keys else "")
            )
        k, v = kv.split("=", 1)
        k = k.strip()
        if spec.param_keys and k not in spec.param_keys:
            raise ValueError(
                f"unknown param {k!r} for this job type. Valid: {', '.join(spec.param_keys)}"
            )
        out[k] = v
    return out


def _marketing(tenant_id, p):
    a = ["scrape", "blinkit", "--tenant", str(tenant_id)]
    _opt(a, "--from", p.get("date_from"))
    _opt(a, "--to", p.get("date_to"))
    _opt(a, "--limit", p.get("limit"))
    return a


def _seller(tenant_id, p):
    a = ["scrape", "blinkit-seller", "--tenant", str(tenant_id)]
    _opt(a, "--from", p.get("date_from"))
    _opt(a, "--to", p.get("date_to"))
    for flag in ("sales", "po", "soh"):
        _flag(a, f"--{flag}", p.get(flag))
    return a


def _scorecard(tenant_id, p):
    a = ["scrape", "blinkit-scorecard", "--tenant", str(tenant_id)]
    _opt(a, "--week", p.get("week"))
    return a


def _zepto_sales(tenant_id, p):
    a = ["scrape", "zepto-sales", "--tenant", str(tenant_id)]
    _opt(a, "--from", p.get("date_from"))
    _opt(a, "--to", p.get("date_to"))
    return a


def _public_keyword(tenant_id, p):
    a = ["scrape", "public-run", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace"))
    _opt(a, "--city", p.get("city"))
    _opt(a, "--keyword", p.get("keyword"))
    _opt(a, "--cap", p.get("cap"))
    _opt(a, "--workers", p.get("workers"))
    _flag(a, "--resume", p.get("resume"))
    return a


def _public_skus(tenant_id, p):
    a = ["scrape", "public-skus", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace"))
    _opt(a, "--city", p.get("city"))
    _opt(a, "--brand-cap", p.get("brand_cap"))
    _opt(a, "--workers", p.get("workers"))
    _flag(a, "--resume", p.get("resume"))
    return a


def _budget_scheduler(tenant_id, p):
    return ["ads", "budget-scheduler", "--tenant", str(tenant_id)]


def _bid_optimizer(tenant_id, p):
    return ["ads", "bid-optimizer", "--tenant", str(tenant_id)]


def _sync_campaign_data(tenant_id, p):
    return ["ads", "sync-campaign-data", "--tenant", str(tenant_id)]


# Campaign Manager v2 (cm.*) — parallel to ads.* (deleted at cutover). Dry-run by
# default; the `live` param maps to --live to arm a real write (only at/after cutover).
def _cm_budget_scheduler(tenant_id, p):
    a = ["cm", "budget-scheduler", "--tenant", str(tenant_id)]
    _flag(a, "--live", p.get("live"))
    return a


def _cm_bid_optimizer(tenant_id, p):
    a = ["cm", "bid-optimizer", "--tenant", str(tenant_id)]
    _flag(a, "--live", p.get("live"))
    _flag(a, "--reset", p.get("reset"))     # end-of-window de-escalation, not optimization
    return a


def _cm_reconcile(tenant_id, p):
    a = ["cm", "reconcile", "--tenant", str(tenant_id)]
    _flag(a, "--live", p.get("live"))
    return a


def _cm_sync_campaign_data(tenant_id, p):
    return ["cm", "sync-campaign-data", "--tenant", str(tenant_id)]


def _cm_sync_campaigns(tenant_id, p):
    a = ["cm", "sync-campaigns", "--tenant", str(tenant_id)]
    _opt(a, "--days", p.get("days"))
    return a


def _cm_set_budget(tenant_id, p):
    a = ["cm", "set-budget", "--tenant", str(tenant_id)]
    _opt(a, "--campaign", p.get("campaign"))
    _opt(a, "--budget", p.get("budget"))
    _flag(a, "--live", p.get("live"))
    return a


def _cm_set_activation(tenant_id, p):
    a = ["cm", "set-activation", "--tenant", str(tenant_id)]
    _opt(a, "--campaign", p.get("campaign"))
    _opt(a, "--status", p.get("status"))
    _opt(a, "--budget", p.get("budget"))     # resume only — a RESTART sets the budget
    _flag(a, "--live", p.get("live"))
    return a


def _log_cleanup(tenant_id, p):
    a = ["maint", "log-cleanup"]
    _opt(a, "--days", p.get("days"))
    return a


def _heartbeat(tenant_id, p):
    a = ["monitor", "heartbeat"]
    _opt(a, "--disk-pct", p.get("disk_pct"))
    return a


def _auth_refresh(tenant_id, p):
    return ["auth", "refresh-all", "--tenant", str(tenant_id)]


# Timeouts are SAFETY CEILINGS (~2–3× expected), not expectations — a healthy run
# should never hit one. They exist so a hung (not crashed) Chromium can't hold a lane
# forever. Override per type via settings.JOB_TIMEOUT_OVERRIDES.
JOB_TYPES: dict[str, JobTypeSpec] = {
    "scrape.blinkit_marketing": JobTypeSpec(
        Lane.dashboard, 60 * 60, _marketing,
        param_keys=("date_from", "date_to", "limit"),
        label="Blinkit ads scrape",
    ),
    "scrape.blinkit_seller": JobTypeSpec(
        Lane.dashboard, 60 * 60, _seller,
        param_keys=("date_from", "date_to", "sales", "po", "soh"),
        label="Blinkit seller scrape",
    ),
    "scrape.blinkit_scorecard": JobTypeSpec(
        Lane.dashboard, 30 * 60, _scorecard,
        param_keys=("week",),
        label="Blinkit scorecard scrape",
    ),
    # Browser-free (session health check + ID discovery + API calls, all plain
    # HTTP — see scraper/platforms/zepto/dashboard_data/seller/scraper.py), so
    # a much tighter timeout ceiling than Blinkit's browser-driven scrapes is
    # appropriate — this should normally finish in well under a minute.
    # Requires a session already saved via `cli auth zepto-seller` (run
    # separately, wherever there's a real display — not on this VM's lane).
    "scrape.zepto_seller_sales": JobTypeSpec(
        Lane.dashboard, 10 * 60, _zepto_sales,
        param_keys=("date_from", "date_to"),
    ),
    # Public scrapes take the marketplace as a PARAM rather than having a job type
    # each: lane and timeout are identical, and sharing the `batch` lane is correct —
    # two concurrent Chromium worker pools would thrash the VM. Per-marketplace
    # cadence still comes free, since schedules are rows. See docs/zepto.md.
    "scrape.public_keyword": JobTypeSpec(
        Lane.batch, 12 * 60 * 60, _public_keyword,
        param_keys=("marketplace", "city", "keyword", "cap", "workers", "resume"),
        label="Public keyword scrape",
    ),
    "scrape.public_skus": JobTypeSpec(
        Lane.batch, 12 * 60 * 60, _public_skus,
        param_keys=("marketplace", "city", "brand_cap", "workers", "resume"),
        label="Public own-SKU scrape",
    ),
    # Ad automations — each has its own dedicated lane so they never block each other.
    "ads.budget_scheduler": JobTypeSpec(
        Lane.budget_scheduler, 5 * 60, _budget_scheduler,
        label="Budget scheduler (legacy v1)",
    ),
    "ads.bid_optimizer": JobTypeSpec(
        Lane.bid_optimizer, 5 * 60, _bid_optimizer,
        label="Bid optimizer (legacy v1)",
    ),
    "ads.sync_campaign_data": JobTypeSpec(
        Lane.sync_campaign_data, 2 * 60 * 60, _sync_campaign_data,
        label="Campaign data sync (legacy v1)",
    ),
    # Campaign Manager v2 — its OWN lanes (D18): bid isolated in cm_bid (latency-
    # critical); budget + set-budget + sync share cm_ops (latency-tolerant); reconcile
    # is no-browser → the shared interactive lane (prompt).
    "cm.budget_scheduler": JobTypeSpec(
        Lane.cm_ops, 15 * 60, _cm_budget_scheduler, param_keys=("live",),
        label="Campaign budget scheduler",
    ),
    "cm.bid_optimizer": JobTypeSpec(
        Lane.cm_bid, 15 * 60, _cm_bid_optimizer, param_keys=("live", "reset"),
        label="Campaign bid optimizer",
    ),
    "cm.set_budget": JobTypeSpec(
        Lane.cm_ops, 10 * 60, _cm_set_budget, param_keys=("campaign", "budget", "live"),
        label="Campaign budget change",
    ),
    # On-demand campaign start/stop (the dashboard's Start/Pause buttons). Shares the
    # cm_ops lane with the other latency-tolerant campaign writes, so it can never run
    # concurrently with the budget scheduler against the same account.
    "cm.set_activation": JobTypeSpec(
        Lane.cm_ops, 10 * 60, _cm_set_activation,
        param_keys=("campaign", "status", "budget", "live"),
        label="Campaign start/pause",
    ),
    "cm.sync_campaign_data": JobTypeSpec(
        Lane.cm_ops, 2 * 60 * 60, _cm_sync_campaign_data,
        label="Campaign performance sync",
    ),
    # Catalogue refresh — a READ (one list call), so it never writes to Blinkit and needs
    # no `live` param. Short timeout: it is a browser launch plus two requests, and it
    # backs a button someone is waiting on, so a hung run should surface fast.
    "cm.sync_campaigns": JobTypeSpec(
        Lane.cm_ops, 5 * 60, _cm_sync_campaigns, param_keys=("days",),
        label="Campaign list refresh",
    ),
    "cm.reconcile": JobTypeSpec(
        Lane.interactive, 5 * 60, _cm_reconcile, param_keys=("live",),
        label="Campaign state reconcile",
    ),
    # Maintenance / monitoring — tenant-less. Heartbeat runs in the interactive lane
    # so it fires promptly (never queued behind a multi-hour scrape).
    "maint.log_cleanup": JobTypeSpec(
        Lane.batch, 10 * 60, _log_cleanup, needs_tenant=False,
        param_keys=("days",),
        label="Log cleanup",
    ),
    "monitor.heartbeat": JobTypeSpec(
        Lane.interactive, 5 * 60, _heartbeat, needs_tenant=False,
        param_keys=("disk_pct",),
        label="Health check",
    ),
    # Platform session upkeep (see docs/platform-auth.md). Interactive lane for the
    # same reason as the heartbeat: it is seconds of work and must never queue
    # behind a multi-hour scrape — a session it was meant to keep alive could
    # expire while it waits. Refresh consumes no secret and sends no email, so it
    # is cheap to run daily; the command itself skips if the tenant has other jobs
    # active, because a seller token rotation invalidates the previous token.
    "auth.refresh": JobTypeSpec(
        Lane.interactive, 3 * 60, _auth_refresh,
        label="Platform session refresh",
    ),
}


def spec_for(job_type: str) -> JobTypeSpec:
    try:
        return JOB_TYPES[job_type]
    except KeyError:
        known = ", ".join(sorted(JOB_TYPES))
        raise ValueError(f"unknown job_type {job_type!r}. Known: {known}") from None


def label_for(job_type: str) -> str:
    """The human name for a job type, for logs/emails/UI.

    Never raises: an UNKNOWN type must still be describable, because the case that
    produces one is deploy skew (the API enqueued a type this box has no code for)
    — precisely when a readable message matters most. Falls back to the raw key.
    """
    spec = JOB_TYPES.get(job_type)
    return (spec.label if spec and spec.label else job_type)
