"""The job-type registry.

One entry per job type: which lane it runs in, its runtime ceiling, which params it
accepts, and how to turn those params into CLI arguments. Adding a job type is one
entry here — the runner, the queue, and (later) the API need no changes.

`build_args(tenant_id, params)` returns the args that follow `python -m cli`, i.e.
the exact command you would type by hand. Keep these thin: all real behaviour lives
in the existing CLI commands.
"""

import uuid
from datetime import datetime
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
    # Does this type record what it did in `cm_run_log`? If so, `enqueue` mints a
    # `run_id` into its params and the builder passes it through as `--run-id`, so the
    # job row and the rows it writes share one id.
    #
    # Why it matters. A finished job says only that the process exited: the CM commands
    # return their counts and never set a non-zero exit code, so a write the marketplace
    # REFUSED settles exactly like one it accepted. The real answer is in the run log —
    # and until this existed there was no way to get from a job to the rows it wrote.
    # The UI guessed, by reading the newest row for the campaign it thought it had acted
    # on, which is wrong whenever anything else touched that campaign in the same window
    # (`cm_ops` and `cm_bid` are parallel lanes, so that is a real race, not a theoretical
    # one) and impossible for a run that spans many campaigns.
    #
    # Minted at `enqueue`, which is the ONE path both the API and the scheduler take —
    # so every correlated job gets one, whoever started it, and operational log↔job
    # correlation works as a side effect rather than as a second feature.
    carries_run_id: bool = False
    # Is this something a PERSON does, as opposed to something the system does on its own?
    #
    # Only these appear in the dashboard's activity list — "what I just asked for", which is
    # a different question from "what has the engine been doing", and the run log already
    # answers the second. Without the split, every rule edit would post a `cm.reconcile`
    # into that list (the API fires one on every save) and the hourly engines would bury the
    # one action the reader is actually waiting on.
    #
    # ⚠️ Necessary but NOT sufficient on its own: it says the TYPE is a human action, while
    # `schedule_id IS NULL` says THIS RUN was one. Both are required — the reconciler can
    # schedule a type a person also triggers by hand, and a cron fire of it is not an action
    # anyone is waiting for. The query applies both; see `campaign_manager_service.recent_actions`.
    user_action: bool = False


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



def _zepto(tenant_id, p):
    """Sales + PO + ads in ONE run.

    Blinkit needs two job types because it has two dashboards behind two
    separate logins; Zepto's single console needs one. Passing no section flag
    runs all three on a single login and a single WAF mint — which also means
    the client's Zepto dashboard is evicted once a day instead of three times.
    """
    a = ["scrape", "zepto", "--tenant", str(tenant_id)]
    _opt(a, "--from", p.get("date_from"))
    _opt(a, "--to", p.get("date_to"))
    _opt(a, "--po-days-back", p.get("po_days_back"))
    # Leave `category` unset for the CLI's own default of 'all'. The three ad
    # tabs return DISJOINT campaigns, so anything narrower silently drops the
    # others' spend.
    _opt(a, "--category", p.get("category"))
    for flag in ("sales", "po", "ads"):
        _flag(a, f"--{flag}", p.get(flag))
    _flag(a, "--all-cities", p.get("all_cities"))
    return a


def _instamart(tenant_id, p):
    """Sales + ads + PO in ONE run — the same 'one console, one login' shape
    as Zepto: Instamart's Brand Portal covers all three behind one login (see
    platform_auth/registry.py), unlike Blinkit's two separate dashboards.
    Mirrors `cli scrape instamart`'s own flags, the master command it drives.
    """
    a = ["scrape", "instamart", "--tenant", str(tenant_id)]
    _opt(a, "--from", p.get("date_from"))
    _opt(a, "--to", p.get("date_to"))
    _opt(a, "--sales-days-back", p.get("sales_days_back"))
    _opt(a, "--ads-days-back", p.get("ads_days_back"))
    for flag in ("sales", "ads", "po"):
        _flag(a, f"--{flag}", p.get(flag))
    return a



def _public_keyword(tenant_id, p):
    a = ["scrape", "public-run", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--city", p.get("city"))
    _opt(a, "--keyword", p.get("keyword"))
    _opt(a, "--cap", p.get("cap"))
    _opt(a, "--workers", p.get("workers"))
    _flag(a, "--resume", p.get("resume"))
    return a


def _public_skus(tenant_id, p):
    a = ["scrape", "public-skus", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--city", p.get("city"))
    _opt(a, "--brand-cap", p.get("brand_cap"))
    _opt(a, "--workers", p.get("workers"))
    _flag(a, "--resume", p.get("resume"))
    return a


# Campaign Manager (cm.*). Dry-run by default; the `live` param maps to --live to arm a
# real write. The legacy `ads.*` job types this once ran parallel to were deleted with the
# v1 engine on 2026-09-03 — see the Lane note in app/models/job.py for why their LANES
# survive the deletion.
#
# `marketplace` selects the adapter (see campaign_manager/marketplaces/__init__.py).
#
# The CLI REQUIRES --marketplace (no default) so a human can never drive the wrong
# ad account by forgetting a flag. Stored schedules predate that flag, so the builder
# fills in `_DEFAULT_MP` when a schedule has no marketplace param — every row already
# in job_schedules keeps running against Blinkit with nothing to rewrite.
#
# ⚠️ argv is therefore NO LONGER byte-identical to pre-Zepto runs: an old schedule
# now emits `--marketplace blinkit`. Behaviour is unchanged, and nothing keys on argv
# (the overlap guard is a DB index on (job_type, tenant_id)) — but a log diff will
# show it.
# Named `marketplace`, not `platform`, to match the public scrape job types.
_DEFAULT_MP = "blinkit"
def _cm_budget_scheduler(tenant_id, p):
    a = ["cm", "budget-scheduler", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
    _flag(a, "--live", p.get("live"))
    return a


def _cm_bid_optimizer(tenant_id, p):
    a = ["cm", "bid-optimizer", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
    _flag(a, "--live", p.get("live"))
    _flag(a, "--reset", p.get("reset"))     # end-of-window de-escalation, not optimization
    return a


def _cm_reconcile(tenant_id, p):
    a = ["cm", "reconcile", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
    _flag(a, "--live", p.get("live"))
    return a


def _cm_sync_campaigns(tenant_id, p):
    a = ["cm", "sync-campaigns", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--days", p.get("days"))
    return a


def _cm_set_budget(tenant_id, p):
    a = ["cm", "set-budget", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
    _opt(a, "--campaign", p.get("campaign"))
    _opt(a, "--budget", p.get("budget"))
    _flag(a, "--live", p.get("live"))
    return a


def _cm_set_bid(tenant_id, p):
    a = ["cm", "set-bid", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
    _opt(a, "--campaign", p.get("campaign"))
    _opt(a, "--keyword", p.get("keyword"))
    _opt(a, "--cpm", p.get("cpm"))
    _opt(a, "--match-type", p.get("match_type"))
    _flag(a, "--live", p.get("live"))
    return a


def _cm_set_activation(tenant_id, p):
    a = ["cm", "set-activation", "--tenant", str(tenant_id)]
    _opt(a, "--marketplace", p.get("marketplace") or _DEFAULT_MP)
    _opt(a, "--run-id", p.get("run_id"))
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


def _auth_login(tenant_id, p):
    return ["auth", "login", str(p["platform"]), "--tenant", str(tenant_id)]


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
    # ── Zepto, mirroring Blinkit's three ────────────────────────────────────
    # Data calls are plain HTTP, but each run still launches headless Chromium
    # ONCE (~10s) to mint an AWS WAF token — campaign_manager/marketplaces/
    # zepto/transport.py::mint_waf_token, called unconditionally by setup(),
    # so sales and PO pay for it too even though only /ads-bff/* needs it.
    # Transient, unlike Blinkit's browser-driven scrapes which hold ~950 MB for
    # the whole run, hence the tighter ceilings below.
    #
    # `dashboard`, shared with Blinkit and deliberately NOT a lane of its own.
    # The lane has ONE slot, and that is the only thing serialising these three:
    # the overlap index keys on job_type, so zepto_ads and zepto_po would
    # otherwise run together and evict each other's Zepto session (one session
    # per account, server-enforced). Splitting the lane removes that protection
    # for concurrency this workload does not need — revisit only when jobs are
    # visibly queueing.
    #
    # Session comes from `cli auth login zepto`; `ensure()` self-heals an
    # expired one mid-run. No display, no Xvfb — the login is browserless REST
    # and the OTP is read from the shared inbox.
    # ONE Zepto job type, where Blinkit needs two. Blinkit's split is forced by
    # two dashboards behind two separate logins (see platform_auth/registry.py);
    # Zepto's single console does not have that constraint, so carrying the
    # split over would copy a workaround rather than a design.
    #
    # Ceiling is the sum of the three sections' own worst cases — sales 15,
    # ads 30, PO 45, the last of which has to clear its 5/15/45s retry ladder.
    # Measured real runs are ~5 min total, so this is a safety ceiling for a
    # hung section, not an expectation.
    #
    # `dashboard`, shared with Blinkit and deliberately NOT a lane of its own:
    # that lane's single slot is the only thing serialising Zepto against
    # itself, and Zepto permits one session per account.
    "scrape.zepto": JobTypeSpec(
        Lane.dashboard, 90 * 60, _zepto,
        param_keys=("date_from", "date_to", "sales", "po", "ads",
                    "po_days_back", "category", "all_cities"),
        label="Zepto scrape",
    ),
    # ── Instamart, same "one console" shape as Zepto ────────────────────────
    # `dashboard` lane for the same reason Zepto shares it: one browser-driven
    # scrape at a time on this VM. 120-minute ceiling (vs Zepto's 90) because
    # Instamart's own edge throttles per-call and can force several 60-120s
    # backoffs in a row — measured live 2026-09-28, a 30-day ads fetch alone
    # took over 15 minutes under heavy throttling, on top of sales' own report-
    # generation poll (up to 15 min) and PO's full-history fetch (~15 min).
    # This is a safety ceiling for a genuinely hung run, not an expectation.
    "scrape.instamart": JobTypeSpec(
        Lane.dashboard, 120 * 60, _instamart,
        param_keys=("date_from", "date_to", "sales_days_back", "ads_days_back",
                    "sales", "ads", "po"),
        label="Instamart scrape",
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
    # Campaign Manager — its OWN lanes (D18): bid isolated in cm_bid (latency-
    # critical); budget + set-budget + sync share cm_ops (latency-tolerant); reconcile
    # is no-browser → the shared interactive lane (prompt).
    "cm.budget_scheduler": JobTypeSpec(
        Lane.cm_ops, 15 * 60, _cm_budget_scheduler, param_keys=("marketplace", "live", "run_id"),
        carries_run_id=True,
        label="Campaign budget scheduler",
    ),
    "cm.bid_optimizer": JobTypeSpec(
        Lane.cm_bid, 15 * 60, _cm_bid_optimizer, param_keys=("marketplace", "live", "reset", "run_id"),
        carries_run_id=True,
        label="Campaign bid optimizer",
    ),
    "cm.set_budget": JobTypeSpec(
        Lane.cm_ops, 10 * 60, _cm_set_budget, param_keys=("marketplace", "campaign", "budget", "live", "run_id"),
        carries_run_id=True, user_action=True,
        label="Campaign budget change",
    ),
    # Reset one keyword's bid to its floor — behind the dashboard's Reset, and behind
    # Delete-with-reset. Deliberately in cm_ops, NOT cm_bid: cm_bid has one slot and an
    # optimizer tick holds it for 87-547s, so a reset queued there would wait minutes for
    # the very engine it is countermanding. cm_ops runs in parallel with cm_bid and is
    # nearly idle (an hourly ~15s budget run), and sharing a single-slot lane with the
    # other campaign writes is a bonus: two whole-campaign PUTs can never overlap.
    # Priority is set by the caller (the API enqueues these ahead of scheduled work).
    "cm.set_bid": JobTypeSpec(
        Lane.cm_ops, 10 * 60, _cm_set_bid,
        param_keys=("marketplace", "campaign", "keyword", "cpm", "match_type", "live", "run_id"),
        carries_run_id=True, user_action=True,
        label="Campaign bid reset",
    ),
    # On-demand campaign start/stop (the dashboard's Start/Pause buttons). Shares the
    # cm_ops lane with the other latency-tolerant campaign writes, so it can never run
    # concurrently with the budget scheduler against the same account.
    "cm.set_activation": JobTypeSpec(
        Lane.cm_ops, 10 * 60, _cm_set_activation,
        param_keys=("marketplace", "campaign", "status", "budget", "live", "run_id"),
        carries_run_id=True, user_action=True,
        label="Campaign start/pause",
    ),
    # Catalogue refresh — a READ (one list call), so it never writes to Blinkit and needs
    # no `live` param. Short timeout: it is a browser launch plus two requests, and it
    # backs a button someone is waiting on, so a hung run should surface fast.
    "cm.sync_campaigns": JobTypeSpec(
        Lane.cm_ops, 5 * 60, _cm_sync_campaigns, param_keys=("marketplace", "days",),
        label="Campaign list refresh", user_action=True,
    ),
    "cm.reconcile": JobTypeSpec(
        Lane.interactive, 5 * 60, _cm_reconcile, param_keys=("marketplace", "live", "run_id"),
        carries_run_id=True,
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
    # ⚠️ A scheduled LOGIN, which docs/platform-auth.md otherwise forbids: a login
    # burns a single-use emailed secret and can lose to mail-scanner lag, where a
    # refresh costs one API call and cannot. Zepto leaves no choice — it has no
    # refresh endpoint at all and its JWT dies at local midnight IST, so the only
    # way to hold a session is to log in again. Do NOT add other platforms here;
    # if a platform can refresh, refresh it.
    #
    # Schedule it just AFTER midnight (e.g. "5 0 * * *"): a login at 23:50 would
    # buy a ten-minute session. It is also when the single-session eviction that
    # every Zepto login causes costs a human the least.
    "auth.login": JobTypeSpec(
        Lane.interactive, 5 * 60, _auth_login,
        param_keys=("platform",),
        label="Platform login (daily, Zepto only)",
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


# ── Schedule names ───────────────────────────────────────────────────────────
#
# The campaign manager's reconciler generates its schedule names as MACHINE KEYS:
#
#   auto:cm:budget:a870fd8d-7373-47ec-ad69-5dd08ce35542:blinkit:0200
#
# and that is the right shape for what they are — `reconciler._apply` matches desired
# rows against existing ones BY NAME, and `_is_managed` parses the platform out of
# them, so the format is load-bearing and must stay stable and deterministic.
#
# The mistake was showing it to people. It surfaces in `cli schedules list/show`, in
# `cli status`, and — worst — inside the overdue-schedule ALERTS raised by
# `jobs/monitor.py::check_deadman`, where someone reading a 2am page gets a 36-char
# UUID and `0200` instead of "the 02:00 budget run". The tenant is already its own
# column everywhere it is displayed, so the UUID tells a reader nothing at all.
#
# So: render, don't rename. Nothing about the stored key changes, which means live
# client automations are not churned by a cosmetic fix.
#
# ⚠️ COUPLED TO `campaign_manager/reconciler.py`. If a new `Desired(...)` name shape
# is added there, add it here too — `campaign_manager/tests/test_schedule_labels.py`
# feeds every real reconciler-generated name through this and fails if one falls back
# to the raw key.

_SCHEDULE_PREFIX = "auto:cm:"

_KIND_LABELS = {
    "budget": "budget",
    "bid": "bids",
    "cleanup": "automations",
}


def _hhmm(token: str) -> str | None:
    """'0200' → '02:00'. None if it isn't a four-digit time."""
    if len(token) == 4 and token.isdigit() and int(token[:2]) < 24 and int(token[2:]) < 60:
        return f"{token[:2]}:{token[2:]}"
    return None


def _when(token: str) -> str | None:
    """A one-shot's fire time: '20260904T0200' → '04 Sep 02:00', '20260904' → '04 Sep'."""
    for fmt, out in (("%Y%m%dT%H%M", "%d %b %H:%M"), ("%Y%m%d", "%d %b")):
        try:
            return datetime.strptime(token, fmt).strftime(out)
        except ValueError:
            continue
    return None


def schedule_label(name: str | None, tenant: str | None = None) -> str:
    """A reconciler schedule name → something a person can read.

    Any other name (a hand-made `schedules add` row, which is already written for
    humans) is returned unchanged, as is anything unparseable — same rule as
    `label_for`: a name we don't recognise must still be printable, because the case
    that produces one is a format change, exactly when a readable message matters.

    `tenant` prefixes the client in the same `DOBRA | …` style the hand-made rows
    already use, so every row in a listing reads the same way. It matters more than it
    looks: the table is multi-tenant, and "'Blinkit budget · 02:00' is overdue" does
    not say WHOSE budget run — with two active clients that is a real question at 2am.
    Omitted when unknown rather than guessed.

        auto:cm:budget:<uuid>:blinkit:0200            -> Blinkit budget · 02:00
        auto:cm:budget:<uuid>:blinkit:poll            -> Blinkit budget · hourly catch-up
        auto:cm:budget:<uuid>:blinkit:once:20260904T0200
                                                      -> Blinkit budget · one-off 04 Sep 02:00
        auto:cm:budget:<uuid>:blinkit:expire:42       -> Blinkit budget · reset after rule 42 ends
        auto:cm:bid:<uuid>:blinkit:opt                -> Blinkit bids · optimiser
        auto:cm:bid:<uuid>:blinkit:reset:1930         -> Blinkit bids · reset 19:30
        auto:cm:bid:<uuid>:blinkit:reset:20260904T1930
                                                      -> Blinkit bids · reset 04 Sep 19:30
        auto:cm:bid:<uuid>:blinkit:once:20260904      -> Blinkit bids · one-off 04 Sep
        auto:cm:cleanup:<uuid>:blinkit                -> Blinkit automations · nightly tidy-up
    """
    if not name or not name.startswith(_SCHEDULE_PREFIX):
        # A hand-made row already carries its own client prefix; adding another would
        # render "DOBRA | DOBRA | Blinkit seller daily".
        return name or ""
    parts = name.split(":")
    if len(parts) < 5:
        return name
    kind, platform, rest = parts[2], parts[4], parts[5:]

    head = f"{platform.title()} {_KIND_LABELS.get(kind, kind)}"
    tail = _schedule_tail(kind, rest)
    label = f"{head} · {tail}" if tail else head
    return f"{tenant.upper()} | {label}" if tenant else label


def _schedule_tail(kind: str, rest: list[str]) -> str | None:
    """The part after the platform — what this particular row does."""
    if kind == "cleanup" and not rest:
        return "nightly tidy-up"
    if not rest:
        return None

    head, arg = rest[0], (rest[1] if len(rest) > 1 else "")

    if head == "poll":
        return "hourly catch-up"
    if head == "opt":
        return "optimiser"
    if head == "settle":
        return "finish ended automations"
    if head == "once":
        when = _when(arg)
        return f"one-off {when}" if when else "one-off"
    if head == "expire":
        # `arg` is a rule id — kept verbatim, because it is the one thing that lets
        # someone find the rule this row was created to clean up after.
        return f"reset after rule {arg} ends" if arg else "reset after the rule ends"
    if head == "reset":
        return f"reset {_hhmm(arg) or _when(arg) or arg}".strip()

    # A bare recurring time, e.g. `…:blinkit:0200`.
    return _hhmm(head) or head
