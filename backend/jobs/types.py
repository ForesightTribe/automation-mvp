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


def _public_keyword(tenant_id, p):
    a = ["scrape", "public-run", "--tenant", str(tenant_id)]
    _opt(a, "--city", p.get("city"))
    _opt(a, "--keyword", p.get("keyword"))
    _opt(a, "--cap", p.get("cap"))
    _opt(a, "--workers", p.get("workers"))
    _flag(a, "--resume", p.get("resume"))
    return a


def _public_skus(tenant_id, p):
    a = ["scrape", "public-skus", "--tenant", str(tenant_id)]
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


def _log_cleanup(tenant_id, p):
    a = ["maint", "log-cleanup"]
    _opt(a, "--days", p.get("days"))
    return a


def _heartbeat(tenant_id, p):
    a = ["monitor", "heartbeat"]
    _opt(a, "--disk-pct", p.get("disk_pct"))
    return a


# Timeouts are SAFETY CEILINGS (~2–3× expected), not expectations — a healthy run
# should never hit one. They exist so a hung (not crashed) Chromium can't hold a lane
# forever. Override per type via settings.JOB_TIMEOUT_OVERRIDES.
JOB_TYPES: dict[str, JobTypeSpec] = {
    "scrape.blinkit_marketing": JobTypeSpec(
        Lane.dashboard, 60 * 60, _marketing,
        param_keys=("date_from", "date_to", "limit"),
    ),
    "scrape.blinkit_seller": JobTypeSpec(
        Lane.dashboard, 60 * 60, _seller,
        param_keys=("date_from", "date_to", "sales", "po", "soh"),
    ),
    "scrape.blinkit_scorecard": JobTypeSpec(
        Lane.dashboard, 30 * 60, _scorecard,
        param_keys=("week",),
    ),
    "scrape.public_keyword": JobTypeSpec(
        Lane.batch, 12 * 60 * 60, _public_keyword,
        param_keys=("city", "keyword", "cap", "workers", "resume"),
    ),
    "scrape.public_skus": JobTypeSpec(
        Lane.batch, 12 * 60 * 60, _public_skus,
        param_keys=("city", "brand_cap", "workers", "resume"),
    ),
    # Ad automations — each has its own dedicated lane so they never block each other.
    "ads.budget_scheduler": JobTypeSpec(
        Lane.budget_scheduler, 15 * 60, _budget_scheduler,
    ),
    "ads.bid_optimizer": JobTypeSpec(
        Lane.bid_optimizer, 10 * 60, _bid_optimizer,
    ),
    "ads.sync_campaign_data": JobTypeSpec(
        Lane.sync_campaign_data, 60 * 60, _sync_campaign_data,
    ),
    # Maintenance / monitoring — tenant-less. Heartbeat runs in the interactive lane
    # so it fires promptly (never queued behind a multi-hour scrape).
    "maint.log_cleanup": JobTypeSpec(
        Lane.batch, 10 * 60, _log_cleanup, needs_tenant=False,
        param_keys=("days",),
    ),
    "monitor.heartbeat": JobTypeSpec(
        Lane.interactive, 5 * 60, _heartbeat, needs_tenant=False,
        param_keys=("disk_pct",),
    ),
}


def spec_for(job_type: str) -> JobTypeSpec:
    try:
        return JOB_TYPES[job_type]
    except KeyError:
        known = ", ".join(sorted(JOB_TYPES))
        raise ValueError(f"unknown job_type {job_type!r}. Known: {known}") from None
