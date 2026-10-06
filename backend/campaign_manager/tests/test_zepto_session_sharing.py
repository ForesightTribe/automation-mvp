"""ZC-P25 — parallel Zepto jobs must not kill each other's session.

Zepto allows ONE session per user, and several jobs share it: the daily `scrape.zepto`
(`dashboard` lane) and the campaign-manager jobs (`cm_ops`, `cm_bid`) run in parallel. When
one logs in again, every other job's in-memory token is revoked. Their next 401 used to go
straight to a re-login, find "last login < 30 min ago", refuse — and fail the run, while a
valid token sat in `platform_sessions` the whole time.

Now a 401 first ADOPTS a fresher stored token (no login, no OTP, no eviction), and only
then logs in. Since 2026-09-21 that holds for WRITES too, and the 30-minute floor is off by
default (Deepansh: a missed action costs more than logging a dashboard user out) — so a
job logs in whenever it has to, bounded by `MAX_REAUTH_PER_RUN` and the circuit breaker.

No network, no DB: the session store, the login and Zepto itself are faked.

    python -m campaign_manager.tests.test_zepto_session_sharing
"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx

from app.utils.time import now_ist
from scraper.platforms.zepto.dashboard_data.seller import client as zt

LIVE_JWT = "fresh-token"          # what Zepto accepts right now
TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"


class _Env:
    """Fakes for the store, the login and Zepto, installed on the client module."""

    def __init__(self, *, stored_jwt: str, last_login_minutes_ago: float = 5,
                 login_works: bool = True):
        self.stored_jwt = stored_jwt
        self.last_login = now_ist() - timedelta(minutes=last_login_minutes_ago)
        self.login_works = login_works
        self.logins = 0
        self.sent_tokens: list[str] = []

    def install(self):
        env = self

        class _DB:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        async def load(db, tenant_id, platform):
            return SimpleNamespace(raw={"jwt": env.stored_jwt, "brand_ids": ["b"]})

        async def last_login(db, tenant_id, platform):
            return env.last_login

        async def ensure(db, tenant_id, platform):
            env.logins += 1
            # A login that "works" yields the token Zepto accepts; one that does not yields
            # a fresh-looking token Zepto still rejects (evicted again at once).
            jwt = LIVE_JWT if env.login_works else f"doomed-{env.logins}"
            env.stored_jwt = jwt
            return SimpleNamespace(raw={"jwt": jwt, "brand_ids": ["b"]})

        class _Http:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, method, url, headers=None, **kw):
                token = (headers or {}).get("authorization")
                env.sent_tokens.append(token)
                req = httpx.Request(method, url)
                return httpx.Response(200 if token == LIVE_JWT else 401, json={}, request=req)

        self.orig = (zt.AsyncSessionLocal, zt.auth_store.load, zt.auth_store.last_login,
                     zt.auth_service.ensure, zt.httpx.AsyncClient)
        zt.AsyncSessionLocal = _DB
        zt.auth_store.load, zt.auth_store.last_login = load, last_login
        zt.auth_service.ensure = ensure
        zt.httpx.AsyncClient = _Http
        return self

    def restore(self):
        (zt.AsyncSessionLocal, zt.auth_store.load, zt.auth_store.last_login,
         zt.auth_service.ensure, zt.httpx.AsyncClient) = self.orig


def _call(env, method="GET", *, retry_writes=True, token="old-token"):
    client = zt.ZeptoClient(TENANT, token, "waf", ["b"])
    env.install()
    try:
        r = asyncio.run(client.request(method, "/ads-bff/api/v1/campaigns/pla/2427461",
                                       brand_analytics=True, retry_writes=retry_writes))
    finally:
        env.restore()
    return r, client


def test_a_read_adopts_the_token_another_job_saved():
    """The P25 case: another job logged in 5 minutes ago. We must NOT log in again (that
    would evict it) and must NOT fail — its token is in the store."""
    env = _Env(stored_jwt=LIVE_JWT, last_login_minutes_ago=5)
    r, client = _call(env)
    assert r.status_code == 200
    assert env.logins == 0, "adopting must not log in"
    assert client.jwt == LIVE_JWT
    assert env.sent_tokens == ["old-token", LIVE_JWT]


def test_logged_out_mid_run_logs_in_even_right_after_another_login():
    """The 2026-09-21 policy. Someone logged into the dashboard 5 minutes after our last
    login; nothing fresher is stored. The job logs in again rather than failing — the old
    30-minute floor would have refused here and the action would have been missed."""
    assert zt.MIN_REAUTH_INTERVAL_SECONDS == 0, "the floor must be off by default"
    env = _Env(stored_jwt="old-token", last_login_minutes_ago=5)
    r, _ = _call(env)
    assert r.status_code == 200 and env.logins == 1


def test_the_floor_still_works_if_someone_configures_it():
    env = _Env(stored_jwt="old-token", last_login_minutes_ago=5)
    orig, zt.MIN_REAUTH_INTERVAL_SECONDS = zt.MIN_REAUTH_INTERVAL_SECONDS, 30 * 60
    try:
        r, _ = _call(env)
    finally:
        zt.MIN_REAUTH_INTERVAL_SECONDS = orig
    assert r.status_code == 401 and env.logins == 0


def test_a_write_logs_in_when_it_has_to():
    """A 401 is rejected before Zepto processes anything, so resending a write after a
    re-login cannot double-apply it. Refusing to log in on a write meant a missed action."""
    env = _Env(stored_jwt=LIVE_JWT)                       # another job's login: adopt it
    r, _ = _call(env, method="PUT", retry_writes=False)
    assert r.status_code == 200 and env.logins == 0

    env = _Env(stored_jwt="old-token")                    # nothing to adopt: log in
    r, _ = _call(env, method="PUT", retry_writes=False)
    assert r.status_code == 200 and env.logins == 1


def test_one_job_cannot_loop_on_logins():
    """If every login is evicted at once (someone fighting back in the dashboard), a single
    job stops after MAX_REAUTH_PER_RUN logins instead of looping."""
    env = _Env(stored_jwt="old-token", login_works=False)
    client = zt.ZeptoClient(TENANT, "old-token", "waf", ["b"])
    env.install()
    try:
        for _ in range(5):
            asyncio.run(client.request("GET", "/x", brand_analytics=True))
    finally:
        env.restore()
    assert env.logins == zt.MAX_REAUTH_PER_RUN


def test_adopting_does_not_spend_the_relogin_budget():
    env = _Env(stored_jwt=LIVE_JWT)
    _, client = _call(env)
    assert client.reauth_count == 0


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e or 'assertion failed'}")
    print(f"\n{len(tests) - failed}/{len(tests)} session-sharing tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
