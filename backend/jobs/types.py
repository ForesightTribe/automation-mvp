"""The job-type registry.

One entry per job type: which lane it runs in, its runtime ceiling, and how to
turn its `params` into CLI arguments. Adding a job type is one entry here — the
runner, the queue, and (later) the API need no changes.

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


def _opt(args: list[str], flag: str, value: Any) -> None:
    """Append `flag value` only when value is set (skips None / '' / missing)."""
    if value not in (None, ""):
        args.extend([flag, str(value)])


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
        if p.get(flag):
            a.append(f"--{flag}")
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
    if p.get("resume"):
        a.append("--resume")
    return a


def _public_skus(tenant_id, p):
    a = ["scrape", "public-skus", "--tenant", str(tenant_id)]
    _opt(a, "--city", p.get("city"))
    _opt(a, "--brand-cap", p.get("brand_cap"))
    _opt(a, "--workers", p.get("workers"))
    if p.get("resume"):
        a.append("--resume")
    return a


# 30 min covers a dashboard scrape comfortably; public scrapes are hours, so their
# ceilings are generous. Override per-type via settings.JOB_TIMEOUT_OVERRIDES.
JOB_TYPES: dict[str, JobTypeSpec] = {
    "scrape.blinkit_marketing": JobTypeSpec(Lane.dashboard, 60 * 60, _marketing),
    "scrape.blinkit_seller": JobTypeSpec(Lane.dashboard, 60 * 60, _seller),
    "scrape.blinkit_scorecard": JobTypeSpec(Lane.dashboard, 30 * 60, _scorecard),
    "scrape.public_keyword": JobTypeSpec(Lane.batch, 12 * 60 * 60, _public_keyword),
    "scrape.public_skus": JobTypeSpec(Lane.batch, 12 * 60 * 60, _public_skus),
}


def spec_for(job_type: str) -> JobTypeSpec:
    try:
        return JOB_TYPES[job_type]
    except KeyError:
        known = ", ".join(sorted(JOB_TYPES))
        raise ValueError(f"unknown job_type {job_type!r}. Known: {known}") from None
