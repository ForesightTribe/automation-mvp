"""A seller-hub scrape that gets logged out after its probe logs in again, once.

WHY THIS EXISTS
---------------
2026-10-06, Sereko: `auth_service.ensure()` probed the stored session at 12:30:54 and
it passed, so auto-login never ran; the scrape was bounced to the login page 8 s later
and the job failed with "Not on a dashboard route — session may be dead". These tests
pin the recovery: a `SessionDead` from the scrape forces one fresh login and one retry.
Anything else still fails at once, and a second `SessionDead` fails the job.

No browser, network or DB: every collaborator of the CLI function is a fake.

    python -m scraper.platforms.blinkit.dashboard_data.seller_hub.tests.test_relogin
"""
import asyncio
import contextlib
from types import SimpleNamespace

import typer

from cli.commands import scrape as cli
from scraper.platforms.blinkit.dashboard_data.seller_hub import scraper as hub

TENANT = "293b8fa2-9008-4194-9a3a-28df52184d98"
OLD = SimpleNamespace(email="seller@example.com", storage_state={"cookies": [{"name": "old"}]})
NEW = SimpleNamespace(email="seller@example.com", storage_state={"cookies": [{"name": "new"}]})
RAW = {"products": [], "window_label": "Last 30 days", "orders": []}


class _DB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@contextlib.contextmanager
def _patched(scrape_results: list, login_error: Exception | None = None):
    """Fake every collaborator; `scrape_results` is consumed one per scrape call
    (an Exception is raised, anything else returned). Yields the call log."""
    log: dict = {"scrapes": [], "logins": 0, "marked": [], "jobs": []}
    results = list(scrape_results)

    async def scrape_sales(email, storage_state, time_range_filter):
        log["scrapes"].append(storage_state["cookies"][0]["name"])
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def ensure(*_a, **_k):
        return OLD

    async def login(*_a, **_k):
        log["logins"] += 1
        if login_error:
            raise login_error
        return NEW

    async def mark_failed(_db, _tid, platform, error, *, login_attempt=True):
        log["marked"].append((platform, error, login_attempt))

    async def create(*_a, **_k):
        return "job-1"

    async def complete(_db, _job, written=0):
        log["jobs"].append(("success", written))

    async def fail(_db, _job, error, records_written=None):
        log["jobs"].append(("failed", error))

    async def save(*_a, **_k):
        return 7

    targets = {
        (cli, "AsyncSessionLocal"): _DB,
        (cli, "create_scrape_job"): create,
        (cli, "complete_scrape_job"): complete,
        (cli, "fail_scrape_job"): fail,
        (cli, "parse_seller_hub_sales_by_product"): lambda *a, **k: [],
        (cli, "parse_seller_hub_sales_orders"): lambda *a, **k: [],
        (cli, "save_seller_hub_sales_results"): save,
        (cli.auth_service, "ensure"): ensure,
        (cli.auth_service, "login"): login,
        (cli.auth_store, "mark_failed"): mark_failed,
        (hub, "scrape_sales"): scrape_sales,
    }
    saved = {key: getattr(*key) for key in targets}
    for (mod, name), v in targets.items():
        setattr(mod, name, v)
    try:
        yield log
    finally:
        for (mod, name), v in saved.items():
            setattr(mod, name, v)


def _run() -> int | None:
    """Exit code of the CLI function; None when it returns normally."""
    try:
        asyncio.run(cli._scrape_blinkit_seller_hub(TENANT, False, True, "Last 30 days"))
    except typer.Exit as e:
        return e.exit_code
    return None


def test_logged_out_mid_scrape_logs_in_and_retries_once():
    with _patched([hub.SessionDead("Not on a dashboard route"), RAW]) as log:
        assert _run() is None
    assert log["scrapes"] == ["old", "new"]          # retried on the NEW session
    assert log["logins"] == 1
    # An expiry, not a failed login — must not feed the circuit breaker.
    assert log["marked"] == [("blinkit_seller_new", "logged out mid-scrape", False)]
    assert log["jobs"] == [("success", 7)]


def test_logged_out_twice_fails_the_job():
    with _patched([hub.SessionDead("first"), hub.SessionDead("second")]) as log:
        assert _run() == 1
    assert log["scrapes"] == ["old", "new"]
    assert log["logins"] == 1                         # once, never a loop
    assert log["jobs"] == [("failed", "second")]


def test_failed_login_fails_the_job():
    with _patched([hub.SessionDead("dead")], login_error=RuntimeError("OTP never arrived")) as log:
        assert _run() == 1
    assert log["scrapes"] == ["old"]
    assert log["jobs"] == [("failed", "OTP never arrived")]


def test_other_errors_do_not_log_in():
    with _patched([RuntimeError("reports/poll returned 500")]) as log:
        assert _run() == 1
    assert log["logins"] == 0
    assert log["marked"] == []
    assert log["jobs"] == [("failed", "reports/poll returned 500")]


def test_session_dead_is_still_a_runtime_error():
    # Anything that caught the old RuntimeError keeps catching it.
    assert issubclass(hub.SessionDead, RuntimeError)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
