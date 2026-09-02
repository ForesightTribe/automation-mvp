"""Every reconciler-made schedule must SAY which marketplace it is for.

The bug this pins: schedule NAMES were platform-scoped, but `params` were not — and
the runner builds argv from params, never from the name. `jobs/types.py` fills in
`_DEFAULT_MP` ("blinkit") when `marketplace` is missing, so a Zepto reconcile produced
rows called `auto:cm:bid:<tenant>:zepto:opt` that fired

    cm bid-optimizer --tenant <t> --marketplace blinkit

i.e. Zepto's rules driving Blinkit's ad account — and, once armed, writing real money
to the wrong marketplace. Nothing in the naming would have looked wrong.

    python -m campaign_manager.tests.test_reconciler_marketplace
"""
from datetime import datetime

from campaign_manager import reconciler as rc
from jobs import types as jt

NOW = datetime(2026, 9, 2, 12, 0)


class _BidRule:
    """Minimal stand-in — only the attributes the planner reads."""

    def __init__(self, **kw):
        self.state, self.type, self.date, self.days = "active", "recurring", None, []
        self.start_date = self.stop_date = None
        self.start_time, self.stop_time = "09:00", "21:00"
        self.campaign_id, self.keyword = 1, "kw"
        for k, v in kw.items():
            setattr(self, k, v)


def _plan(platform, **kw):
    return rc.desired_schedules("T-1", platform, [], [_BidRule()], NOW, **kw)


def _argv(desired):
    return jt.JOB_TYPES[desired.job_type].build_args("T-1", desired.params)


# ── the stamp ────────────────────────────────────────────────────────────────

def test_every_schedule_carries_its_marketplace():
    for mp in ("blinkit", "zepto"):
        plan = _plan(mp)
        assert plan, f"{mp} planned nothing"
        for d in plan:
            assert d.params.get("marketplace") == mp, f"{mp}: {d.name} params={d.params}"


def test_the_cleanup_row_is_stamped_too():
    """It is appended after the arming loop, so it is the one most likely to be missed
    — and it re-runs reconcile, which would then reconcile the WRONG marketplace and
    delete the other one's schedules."""
    cleanup = [d for d in _plan("zepto") if d.job_type == rc.RECONCILE_JOB]
    assert cleanup, "no cleanup schedule planned"
    assert all(d.params.get("marketplace") == "zepto" for d in cleanup)


def test_zepto_schedules_actually_run_zepto():
    """The end-to-end assertion: params → argv, the way the runner does it."""
    for d in _plan("zepto"):
        argv = _argv(d)
        assert "--marketplace" in argv
        assert argv[argv.index("--marketplace") + 1] == "zepto", argv


def test_blinkit_argv_is_unchanged_by_the_stamp():
    """Existing Blinkit rows gain an explicit `marketplace=blinkit`, which resolves to
    exactly what the missing-param default produced. Stated, not altered."""
    for d in _plan("blinkit"):
        argv = _argv(d)
        assert argv[argv.index("--marketplace") + 1] == "blinkit"
        stripped = dict(d.params)
        stripped.pop("marketplace")
        assert _argv(rc.Desired(d.name, d.job_type, d.cron, d.repeat,
                                d.next_run_at, params=stripped)) == argv


# ── the stamp must not clobber the other params ──────────────────────────────

def test_arming_and_the_marketplace_stamp_coexist():
    """`live` is applied before the stamp; both must survive, or an armed Zepto
    schedule silently reverts to dry — or to Blinkit."""
    for d in _plan("zepto", live=True):
        if d.job_type == rc.RECONCILE_JOB:
            continue                     # cleanup is always live by construction
        assert d.params.get("live") == "true", d.name
        assert d.params.get("marketplace") == "zepto", d.name


def test_the_reset_flag_survives_the_stamp():
    resets = [d for d in _plan("zepto") if d.params.get("reset")]
    assert resets, "no end-of-window reset planned"
    for d in resets:
        argv = _argv(d)
        assert "--reset" in argv and argv[argv.index("--marketplace") + 1] == "zepto"


# ── isolation between marketplaces ──────────────────────────────────────────

def test_the_two_marketplaces_plan_disjoint_schedule_names():
    """Names must not collide, or reconciling one would delete the other's rows —
    `_apply` only keeps what the current platform's plan contains."""
    a = {d.name for d in _plan("blinkit")}
    b = {d.name for d in _plan("zepto")}
    assert a and b and not (a & b)


def test_marketplace_is_an_accepted_param_on_every_cm_job_type():
    """A param the registry rejects as a typo would fail the enqueue at runtime, not
    here — so check the spec agrees the key exists."""
    for job in (rc.BUDGET_JOB, rc.BID_JOB, rc.RECONCILE_JOB):
        assert "marketplace" in jt.JOB_TYPES[job].param_keys, job


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)}/{len(tests)} reconciler-marketplace tests passed.")
