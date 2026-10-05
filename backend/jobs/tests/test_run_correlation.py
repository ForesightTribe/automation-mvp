"""Unit tests for run-id correlation (jobs/types.py + jobs/queue.py).

A job row and the `cm_run_log` rows the run writes must share one id, or there is no way
to answer "did the change I asked for actually happen" — a job's `status` only reports
that the process exited, and the CM commands never set a non-zero exit code, so a refused
write settles exactly like an accepted one.

Pure: the spec + argv layer only. No DB, no queue, no marketplace.

Run:  python -m jobs.tests.test_run_correlation
"""
import uuid

from jobs.types import JOB_TYPES, spec_for

_TENANT = uuid.UUID("a870fd8d-7373-47ec-ad69-5dd08ce35542")


def _argv(job_type: str, params: dict) -> list[str]:
    return spec_for(job_type).build_args(_TENANT, params)


# ── Which types carry one ────────────────────────────────────────────────────

def test_every_type_that_writes_history_carries_a_run_id():
    # The six that call repo.write_run_log. If a new cm.* type starts recording history,
    # it belongs here too — otherwise its jobs are silently untraceable.
    for t in ("cm.budget_scheduler", "cm.bid_optimizer", "cm.set_budget",
              "cm.set_bid", "cm.set_activation", "cm.reconcile"):
        assert JOB_TYPES[t].carries_run_id, f"{t} should carry a run id"


def test_sync_campaigns_does_not():
    # It writes the CATALOGUE, not the run log, so a run id would promise rows that never
    # arrive and leave the UI waiting on an answer that cannot come.
    assert not JOB_TYPES["cm.sync_campaigns"].carries_run_id


def test_scrapes_do_not():
    for t in ("scrape.blinkit_marketing", "scrape.public_keyword", "monitor.heartbeat"):
        assert not JOB_TYPES[t].carries_run_id


# ── argv ─────────────────────────────────────────────────────────────────────

def test_a_run_id_reaches_the_command_line():
    argv = _argv("cm.set_budget", {"marketplace": "blinkit", "campaign": 637511,
                                   "budget": 700, "live": True, "run_id": "abc12345"})
    assert "--run-id" in argv
    assert argv[argv.index("--run-id") + 1] == "abc12345"


def test_every_correlated_type_passes_it_through():
    params = {"marketplace": "zepto", "campaign": 1, "budget": 100, "status": "paused",
              "keyword": "soda", "cpm": 200, "run_id": "abc12345"}
    for t, spec in JOB_TYPES.items():
        if not spec.carries_run_id:
            continue
        assert "--run-id" in _argv(t, params), f"{t} drops the run id"


def test_absent_run_id_emits_no_flag():
    # A schedule row created before this existed has no run_id in its params. The command
    # must then look exactly as it always did — the run mints its own id instead.
    argv = _argv("cm.budget_scheduler", {"marketplace": "blinkit", "live": True})
    assert "--run-id" not in argv
    assert argv == ["cm", "budget-scheduler", "--tenant", str(_TENANT),
                    "--marketplace", "blinkit", "--live"]


def test_empty_run_id_emits_no_flag():
    assert "--run-id" not in _argv("cm.budget_scheduler",
                                   {"marketplace": "blinkit", "run_id": ""})


# ── ZC-D1: no default marketplace ────────────────────────────────────────────

def test_every_cm_job_without_a_marketplace_refuses_to_build():
    """It used to fall back to Blinkit. A cm.* job drives a real ad account, so an unnamed
    one fails (the runner marks it failed, nothing starts) instead of guessing."""
    from jobs.types import MissingMarketplace

    params = {"campaign": 1, "budget": 100, "status": "paused", "keyword": "soda", "cpm": 200}
    for t in JOB_TYPES:
        if not t.startswith("cm."):
            continue
        try:
            _argv(t, params)
        except MissingMarketplace:
            continue
        raise AssertionError(f"{t} built without a marketplace")


def test_the_named_marketplace_reaches_the_command_line():
    for mp in ("blinkit", "zepto"):
        argv = _argv("cm.set_activation", {"marketplace": mp, "campaign": 1, "status": "paused"})
        assert argv[argv.index("--marketplace") + 1] == mp


def test_public_scrapes_refuse_to_build_without_a_marketplace_too():
    """Public scrapes used to keep a Blinkit fallback ("stored schedules predate the
    param"). No public schedule exists, and an unnamed job quietly scraped Blinkit and
    staged it as a Blinkit run — so since 2026-10-02 they follow ZC-D1 as well."""
    from jobs.types import MissingMarketplace

    for t in ("scrape.public_keyword", "scrape.public_skus"):
        try:
            _argv(t, {})
        except MissingMarketplace:
            pass
        else:
            raise AssertionError(f"{t} built without a marketplace")
        argv = _argv(t, {"marketplace": "zepto"})
        assert argv[argv.index("--marketplace") + 1] == "zepto"


# ── params ───────────────────────────────────────────────────────────────────

def test_run_id_is_an_accepted_param_wherever_it_is_minted():
    # `parse_params` rejects unknown keys, so a type that is minted a run_id but does not
    # accept one would fail at enqueue — for scheduled runs, silently and nightly.
    for t, spec in JOB_TYPES.items():
        if spec.carries_run_id:
            assert "run_id" in spec.param_keys, f"{t} mints a run id it will not accept"


# ── user_action: what the dashboard's activity list may show ─────────────────

def test_the_four_things_a_person_clicks_are_actions():
    # Set budget, Start/Pause, Reset (and Delete-with-reset), Refresh Campaigns.
    for t in ("cm.set_budget", "cm.set_activation", "cm.set_bid", "cm.sync_campaigns"):
        assert JOB_TYPES[t].user_action, f"{t} is triggered from the dashboard"


def test_the_background_engines_are_not_actions():
    # They run on cron. Listing them would bury the one line a reader is waiting on, and
    # their work is already in the history below.
    for t in ("cm.budget_scheduler", "cm.bid_optimizer"):
        assert not JOB_TYPES[t].user_action


def test_reconcile_is_not_an_action():
    # The noisiest thing that would otherwise qualify: the API fires one on EVERY rule
    # edit, and nobody thinks of it as something they did.
    assert not JOB_TYPES["cm.reconcile"].user_action


def test_nothing_outside_the_campaign_manager_is_an_action():
    # The activity list is a campaign-manager surface; a scrape appearing in it would be
    # a category error (and it has its own reporting).
    for t, spec in JOB_TYPES.items():
        if spec.user_action:
            assert t.startswith("cm."), f"{t} is not a campaign-manager job"


def test_an_action_type_is_still_only_half_the_test():
    # Documents the invariant the query depends on: `user_action` says the TYPE is a human
    # action, `schedule_id IS NULL` says THIS run was one. A type flagged here may still be
    # fired by a schedule, and that instance must not show — so the service must apply both.
    # `cm.set_budget` is exactly such a type: the dashboard's Budget Reset enqueues one.
    assert JOB_TYPES["cm.set_budget"].user_action
    assert "campaign" in JOB_TYPES["cm.set_budget"].param_keys


def _run() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} run-correlation tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
