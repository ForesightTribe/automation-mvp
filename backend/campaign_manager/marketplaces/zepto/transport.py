"""Zepto HTTP transport — the AWS WAF token, and the only browser in the system.

Zepto guards `/ads-bff/*` with an AWS WAF **Challenge**: an unrecognised client gets
`202` with a JavaScript challenge instead of a response. Solving it means running
AWS's own SDK in a real browser, which hands back a signed token proving "I am a
browser". So:

    headless Chromium loads the console  ->  aws-waf-token cookie  ->  close browser
    every real API call then runs over plain httpx, carrying that token

The browser is a **token faucet**, not the transport. This is the important
difference from Blinkit, where Cloudflare rejects httpx outright and every single
fetch must happen inside a live page. Here one ~10s browser launch covers a whole
run (a 3-write session measured 37s end to end).

## Three things that will bite whoever touches this next

**`waf-enabled: false` is REQUIRED, not a feature flag.** Its name says "client
hint you can ignore"; it is not. Send the WAF token WITHOUT it and CloudFront
answers **429** — which reads exactly like rate limiting. That misreading cost an
afternoon: three wrong diagnoses (rate limit, IP block, unverified token) chased
before the real cause turned out to be a missing header that had been visible in the
very first capture. If you see 429 here, check the headers before theorising about
the network.

**The token lives ~5 minutes** (measured: alive at 4, dead at 6 — AWS's default
challenge immunity). It is never cached in the DB: every job interval we have is
longer than its life, so a stored token would be expired essentially every read.
We re-mint on the failure signal rather than on a clock — no arithmetic to get wrong.

**Re-mint by RELAUNCHING, never by holding a browser open.** Holding Chromium for a
long run is the always-on shape D1 rejected: ~1 GB resident for the whole run
against ~1 GB for ten seconds. On an 8 GB box shared with scrapes, transient wins.

## Session eviction

Zepto permits ONE session per user. A human logging into the dashboard silently
kills ours mid-run, and vice versa. `_reauth` handles that, with a hard cap — see
its docstring for why unbounded retry is actively harmful here.
"""
import asyncio
import os
from typing import Any

import httpx

from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from app.utils.time import now_ist
from campaign_manager.marketplaces.zepto import endpoints as ep
from platform_auth import service as auth_service
from platform_auth import store as auth_store

_TIMEOUT = 45
_PLATFORM = "zepto"

# How many times ONE run may re-login after being evicted. Unbounded retry is not
# "more robust" here — it is a fight with a human. Each cycle burns a single-use
# emailed OTP and walks the auth circuit breaker toward tripping, so a client
# working in the dashboard could cost us a whole day's logins in minutes.
MAX_REAUTH_PER_RUN = 2

# The CROSS-RUN floor: refuse a re-login when the last one (shared `last_login_at`, so every
# run on every machine sees the same clock) was less than this long ago.
#
# ⚠️ DEFAULT 0 = OFF, since 2026-09-21 (Deepansh). It was 30 minutes, built to stop a
# tug-of-war with a person in the dashboard — each of our logins logs them out and costs an
# OTP, each of theirs logs us out. But there is no service user coming and the client
# accepts being logged out, so the floor's only remaining effect was a job that REFUSED to
# log in and failed — a missed bid tick, a budget window left open. Actions must not be
# missed for a login we could have made.
#
# What still bounds logins: `MAX_REAUTH_PER_RUN` (one job cannot loop), the auth circuit
# breaker (3 consecutive FAILED logins stop all logins and alert), and `_adopt_stored`
# (jobs overlapping reuse each other's login instead of each making their own). Set the env
# var to a positive number of seconds to bring the floor back.
MIN_REAUTH_INTERVAL_SECONDS = int(os.getenv("CM_ZEPTO_MIN_REAUTH_INTERVAL_SECONDS", "0"))

# CloudFront's answers when the WAF is unsatisfied: 202 = challenge, 429 = present
# but rejected (or the `waf-enabled` header missing). Both mean "re-mint", not
# "back off".
_WAF_REJECT = (202, 429)


class ZeptoClient:
    """One tenant's authenticated Zepto API client.

    Holds the two independent credentials — they are NOT the same kind of thing:

    * `jwt`  — identity, from `platform_auth`. Dies at local midnight IST, or the
               instant another login evicts it. Cannot be refreshed.
    * `waf`  — proof-of-browser, minted here. ~5 minutes. Anonymous: it says nothing
               about who we are, which is exactly why it does not belong in
               `AuthSession`.

    Their failure modes are distinguishable and must be handled differently:
    `401` = identity gone (re-login), `202`/`429` = browser proof gone (re-mint).
    Conflating them burns OTPs on a problem a header would have fixed.
    """

    def __init__(self, tenant_id: str, jwt: str, waf_token: str,
                 brand_ids: list[str] | None = None) -> None:
        self.tenant_id = tenant_id
        self.jwt = jwt
        self.waf = waf_token
        self.brand_ids = brand_ids or []
        self.reauth_count = 0
        self.remint_count = 0

    # ── header construction ──────────────────────────────────────────────────
    def headers(self, *, brand_analytics: bool = False) -> dict[str, str]:
        h = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": ep.CONSOLE,
            "referer": f"{ep.CONSOLE}/",
            "user-agent": ep.USER_AGENT,
            "authorization": self.jwt,          # RAW jwt — never "Bearer <jwt>"
        }
        if brand_analytics:
            h[ep.PROXY_TARGET_HEADER] = ep.PROXY_TARGET_BRAND_ANALYTICS
        else:
            # /ads-bff/* needs BOTH of these. Either one alone gets a 429.
            h[ep.WAF_TOKEN_HEADER] = self.waf
            h[ep.WAF_ENABLED_HEADER] = ep.WAF_ENABLED_VALUE
        return h

    @property
    def brand_id(self) -> str:
        """The ad account every ads call is scoped by (Zepto's advertiser analog).

        Unlike Blinkit — where the advertiser id appears in NO read API and a stale
        stored value writes real money to a dead account — Zepto returns this in the
        login response, so it is derived rather than remembered.
        """
        if not self.brand_ids:
            raise RuntimeError(
                "Zepto session carries no brandIds — the account may lack ads access. "
                "Re-run `cli auth login zepto -t <tenant>` and check `auth status`."
            )
        return self.brand_ids[0]

    # ── recovery ─────────────────────────────────────────────────────────────
    async def _remint(self) -> None:
        self.waf = await mint_waf_token()
        self.remint_count += 1
        logger.info(f"Zepto WAF token re-minted (#{self.remint_count})")

    async def _adopt_stored(self) -> bool:
        """Take a FRESHER session another job already saved, instead of logging in. (ZC-P25)

        Several Zepto jobs run at once — the daily `scrape.zepto` in the `dashboard` lane,
        the campaign-manager jobs in `cm_ops` / `cm_bid` — and they share ONE Zepto login,
        because Zepto allows one session per user. When one of them logs in again, every
        other job's in-memory token is revoked. Before this, the next 401 in those jobs went
        straight to `_reauth`, saw "last login < 30 min ago", refused, and FAILED the run —
        with a perfectly good token sitting in `platform_sessions` the whole time.

        Costs one DB read, no request to Zepto, no OTP, and evicts nobody — so it is tried
        before every re-login, and is also safe on a write (see `request`).
        Returns True only when the stored token differs from the one that just got a 401.
        """
        try:
            async with AsyncSessionLocal() as db:
                stored = await auth_store.load(db, self.tenant_id, _PLATFORM)
        except Exception as e:
            logger.debug(f"Zepto: could not re-read the stored session ({e})")
            return False
        raw = (stored.raw if stored else None) or {}
        jwt = raw.get("jwt")
        if not jwt or jwt == self.jwt:
            return False
        self.jwt = jwt
        self.brand_ids = raw.get("brand_ids") or self.brand_ids
        logger.info("Zepto session was replaced by another job's login — adopted the "
                    "fresher stored session instead of logging in again")
        return True

    async def _reauth(self) -> bool:
        """Re-login after eviction. Returns False when either budget is spent.

        A fresher session another job already saved is adopted FIRST (`_adopt_stored`) —
        that is the common case when jobs overlap, and it costs no login at all.

        Otherwise it LOGS IN — the policy since 2026-09-21: a missed action costs more
        than logging a dashboard user out, and the client accepts that. Bounded by
        `MAX_REAUTH_PER_RUN` (a single job cannot loop), by the auth circuit breaker
        (3 consecutive failed logins), and — only if configured above 0 — by
        `MIN_REAUTH_INTERVAL_SECONDS` (see its note: off by default).

        ⚠️ Known cost: with someone working in the Zepto dashboard during a bid window,
        each tick logs them out and sends an OTP email. Our jobs keep running.
        """
        if await self._adopt_stored():
            return True
        if self.reauth_count >= MAX_REAUTH_PER_RUN:
            logger.error(f"Zepto session rejected (401) again after {MAX_REAUTH_PER_RUN} "
                         "re-logins in this run — giving up on this run.")
            return False

        async with AsyncSessionLocal() as db:
            last = await auth_store.last_login(db, self.tenant_id, _PLATFORM) \
                if MIN_REAUTH_INTERVAL_SECONDS > 0 else None
            if last is not None:
                age = (now_ist() - last).total_seconds()
                if age < MIN_REAUTH_INTERVAL_SECONDS:
                    logger.error(
                        f"Zepto session rejected (401), but the last login was only "
                        f"{age / 60:.0f} min ago (floor {MIN_REAUTH_INTERVAL_SECONDS / 60:.0f} "
                        f"min) — NOT logging in again. Someone is almost certainly using "
                        f"the dashboard on this account: Zepto allows one session per "
                        f"user, so each of our logins takes theirs away and burns an OTP. "
                        f"This run will fail; a service user is the fix."
                    )
                    return False

            self.reauth_count += 1
            logger.warning(
                f"Zepto session rejected (401) — logging in again ({self.reauth_count}/"
                f"{MAX_REAUTH_PER_RUN} this run). This logs out anyone using the Zepto "
                "dashboard on the same account."
            )
            session = await auth_service.ensure(db, self.tenant_id, _PLATFORM)
        self.jwt = session.raw.get("jwt", "")
        self.brand_ids = session.raw.get("brand_ids", []) or self.brand_ids
        return bool(self.jwt)

    # ── the one request path ─────────────────────────────────────────────────
    async def request(self, method: str, path: str, *, brand_analytics: bool = False,
                      retry_writes: bool = True, **kw: Any) -> httpx.Response:
        """Make one API call, recovering from the two recoverable failures:

        * **202/429** — the WAF pass is stale: re-mint, resend once.
        * **401** — the session is gone: adopt a fresher stored one or log in
          (`_reauth`), resend once. For EVERY method, writes included, since 2026-09-21:
          a 401 is rejected before Zepto processes anything, so resending cannot apply a
          change twice — and refusing to log in on a write meant an action was missed.

        A **timeout** is never retried, on any method: the call may have landed and we
        simply never heard. The write path reads back instead (`writes.WriteUnverified`).

        `retry_writes` is accepted for the callers that pass it and no longer changes
        anything: it only ever governed the 401 retry, which is now safe everywhere.
        """
        url = f"{ep.API}{path}"
        # http2 is deliberately OFF: the VM's venv has no `h2`, so http2=True raises
        # there while working locally — a failure that only appears in production.
        # Zepto does not require http2.
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            r = await http.request(method, url, headers=self.headers(
                brand_analytics=brand_analytics), **kw)

            if r.status_code in _WAF_REJECT and not brand_analytics:
                await self._remint()
                r = await http.request(method, url, headers=self.headers(), **kw)

            if r.status_code == 401:
                if await self._reauth():
                    r = await http.request(method, url, headers=self.headers(
                        brand_analytics=brand_analytics), **kw)
        return r

    async def get_json(self, path: str, *, brand_analytics: bool = False,
                       **kw: Any) -> dict:
        r = await self.request("GET", path, brand_analytics=brand_analytics, **kw)
        if r.status_code != 200:
            raise RuntimeError(
                f"Zepto GET {path} -> {r.status_code}: {r.text[:200]}"
            )
        return r.json()


async def mint_waf_token() -> str:
    """Load the console in headless Chromium and take the token it earns.

    Loading the PUBLIC console page is enough — no login, no credentials. The token
    proves "browser", not "user", which is why an anonymous page load produces a
    valid one. Validated headless on the Mumbai VM (datacenter IP, full challenge:
    challenge.js -> mp_verify -> inputs -> mp_verify, all 200).

    The browser is closed before returning: it has done its whole job.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(user_agent=ep.USER_AGENT)
            page = await ctx.new_page()
            await page.goto(f"{ep.CONSOLE}/", wait_until="networkidle", timeout=90_000)
            # The challenge resolves asynchronously AFTER load; the cookie is not
            # there the instant networkidle fires.
            await page.wait_for_timeout(10_000)
            cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        finally:
            await browser.close()

    token = cookies.get("aws-waf-token", "")
    if not token:
        raise RuntimeError(
            "Zepto: headless Chromium did not produce an aws-waf-token. The WAF "
            "challenge did not complete — check that the console loads from this IP."
        )
    logger.info(f"Zepto WAF token minted ({len(token)} chars)")
    return token


async def setup(tenant_id: str):
    """Return `(playwright, browser, ZeptoClient)` — the adapter contract.

    The first two are **always None**: Zepto needs no persistent browser, and the
    engines already guard `if browser is not None` before closing. Returning the
    triple keeps one shape across marketplaces (see marketplaces/base.py).

    `ensure()` probes the stored session and re-logs-in if it is dead, raising a
    typed AuthError that `cli/main.py` maps to exit 3 -> `jobs.error='auth_expired'`.
    That matters more here than in a scraper: this path WRITES budgets and bids, so
    discovering a dead session halfway through is money-adjacent.
    """
    async with AsyncSessionLocal() as db:
        session = await auth_service.ensure(db, tenant_id, _PLATFORM)

    jwt = session.raw.get("jwt")
    if not jwt:
        raise RuntimeError(
            "Zepto session has no jwt — it may be a legacy row written by the "
            "retired zepto_seller path. Re-run `cli auth login zepto`."
        )

    # Minting and the session load are independent, but keep them sequential: a
    # failed login should not have paid for a browser launch first.
    waf = await mint_waf_token()
    client = ZeptoClient(tenant_id, jwt, waf, session.raw.get("brand_ids"))
    logger.info(
        f"Zepto client ready (brand {client.brand_ids[0] if client.brand_ids else '—'}), "
        "no persistent browser"
    )
    return None, None, client
