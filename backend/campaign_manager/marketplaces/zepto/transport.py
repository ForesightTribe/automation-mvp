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
from typing import Any

import httpx

from app.core.database import AsyncSessionLocal
from app.utils.logger import logger
from campaign_manager.marketplaces.zepto import endpoints as ep
from platform_auth import service as auth_service

_TIMEOUT = 45
_PLATFORM = "zepto"

# How many times ONE run may re-login after being evicted. Unbounded retry is not
# "more robust" here — it is a fight with a human. Each cycle burns a single-use
# emailed OTP and walks the auth circuit breaker toward tripping, so a client
# working in the dashboard could cost us a whole day's logins in minutes.
MAX_REAUTH_PER_RUN = 2

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

    async def _reauth(self) -> bool:
        """Re-login after eviction. Returns False once the run's budget is spent.

        Bounded deliberately. Zepto allows one session per user, so this ping-pongs
        against a human: we log in, they are evicted, they log back in, we are
        evicted. Left unbounded that loop burns an OTP per cycle and trips the
        circuit breaker — turning "someone opened the dashboard" into "auto-login is
        suspended for this tenant".
        """
        if self.reauth_count >= MAX_REAUTH_PER_RUN:
            return False
        self.reauth_count += 1
        logger.warning(
            f"Zepto session rejected (401) — re-login {self.reauth_count}/"
            f"{MAX_REAUTH_PER_RUN}. If this recurs, someone is probably using the "
            "dashboard on the same account; a service user would end it."
        )
        async with AsyncSessionLocal() as db:
            session = await auth_service.ensure(db, self.tenant_id, _PLATFORM)
        self.jwt = session.raw.get("jwt", "")
        self.brand_ids = session.raw.get("brand_ids", []) or self.brand_ids
        return bool(self.jwt)

    # ── the one request path ─────────────────────────────────────────────────
    async def request(self, method: str, path: str, *, brand_analytics: bool = False,
                      retry_writes: bool = True, **kw: Any) -> httpx.Response:
        """Make one API call, recovering from the two recoverable failures.

        ⚠️ `retry_writes=False` for any non-idempotent call. A 401 is safe to retry
        (rejected BEFORE processing, so nothing landed), but a **timeout is not** —
        the write may well have applied and we simply never heard. Retrying that
        blindly is how a retry becomes a second unintended write. Timeouts are
        therefore never retried here at all; the caller must re-read and compare.
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

            if r.status_code == 401 and (retry_writes or method.upper() == "GET"):
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
