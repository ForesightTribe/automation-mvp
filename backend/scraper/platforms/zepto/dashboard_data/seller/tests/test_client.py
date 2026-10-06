"""Zepto's shared client (seller/client.py) — the two kinds of 429, 2026-10-06 (P53).

  CloudFront 429 / 202   the WAF pass is stale or a header is missing → re-mint, resend
  Zepto 429 JSON         `{"error":"rate limit exceeded"}`, Zepto's own limit → wait and
                         resend with the SAME token; never relaunch the browser for it

Before P53 both re-minted, so a fast loop relaunched Chromium 7 times in 90 s. The waits
are counted (`ratelimit_count`) and show on the section's closing line.

No network, no browser: httpx, the minting and sleep are faked.

Run:  python -m scraper.platforms.zepto.dashboard_data.seller.tests.test_client
"""
import asyncio

import httpx

from scraper.platforms.zepto.dashboard_data.seller import client as zt
from scraper.platforms.zepto.dashboard_data.seller import run as zr

TENANT = "fa53082e-7e83-424d-aab9-086fe1b4c680"
LIMITED = {"error": "rate limit exceeded"}


def _call(answers: list, *, method: str = "GET", brand_analytics: bool = False):
    """One `client.request` against a Zepto that answers `answers` in order: each is a
    status (empty body, as CloudFront sends) or `(status, json)`. Returns the response,
    the client, the WAF tokens each attempt carried, and the waits slept."""
    sent, slept, mints = [], [], {"n": 0}
    queue = list(answers)

    class _Http:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, m, url, headers=None, **kw):
            sent.append((headers or {}).get(zt.ep.WAF_TOKEN_HEADER))
            a = queue.pop(0)
            req = httpx.Request(m, url)
            if isinstance(a, tuple):
                return httpx.Response(a[0], json=a[1], request=req)
            return httpx.Response(a, text="", request=req)

    async def mint():
        mints["n"] += 1
        return f"waf-{mints['n']}"

    async def sleep(s):
        slept.append(s)

    async def reauth():
        return False

    client = zt.ZeptoClient(TENANT, "jwt", "waf-0", ["b"])
    client._reauth = reauth
    orig = (zt.httpx.AsyncClient, zt.mint_waf_token, zt.asyncio.sleep)
    zt.httpx.AsyncClient, zt.mint_waf_token, zt.asyncio.sleep = _Http, mint, sleep
    try:
        r = asyncio.run(client.request(method, "/ads-bff/api/v1/keyword/config",
                                       brand_analytics=brand_analytics))
    finally:
        zt.httpx.AsyncClient, zt.mint_waf_token, zt.asyncio.sleep = orig
    assert not queue, f"{len(queue)} answer(s) never asked for"
    return r, client, sent, slept


def test_zeptos_rate_limit_is_waited_out_with_the_same_token():
    r, client, sent, slept = _call([(429, LIMITED), (429, LIMITED), (200, {})])
    assert r.status_code == 200
    assert sent == ["waf-0"] * 3, "no re-mint for Zepto's own limit"
    assert client.remint_count == 0 and client.ratelimit_count == 2
    assert slept == list(zt._RATE_LIMIT_WAITS[:2])


def test_a_cloudfront_429_still_re_mints():
    r, client, sent, slept = _call([429, (200, {})])
    assert r.status_code == 200 and sent == ["waf-0", "waf-1"]
    assert client.remint_count == 1 and client.ratelimit_count == 0 and slept == []


def test_a_waf_challenge_still_re_mints():
    r, client, sent, _ = _call([202, (200, {})])
    assert r.status_code == 200 and client.remint_count == 1


def test_a_rate_limit_after_a_re_mint_is_waited_out_too():
    r, client, sent, slept = _call([429, (429, LIMITED), (200, {})])
    assert r.status_code == 200 and sent == ["waf-0", "waf-1", "waf-1"]
    assert client.remint_count == 1 and client.ratelimit_count == 1


def test_a_limit_that_never_lifts_is_returned_after_the_last_wait():
    """Bounded: the caller gets the 429 (the scrape counts a lost fetch, the write path a
    refusal) — and the browser is never launched for it."""
    answers = [(429, LIMITED)] * (len(zt._RATE_LIMIT_WAITS) + 1)
    r, client, sent, slept = _call(answers)
    assert r.status_code == 429 and zt.is_rate_limited(r)
    assert slept == list(zt._RATE_LIMIT_WAITS) and client.remint_count == 0


def test_a_rate_limited_write_is_resent():
    """A rate-limited request was refused before Zepto processed it, so a write is resent
    exactly like a read."""
    r, client, sent, _ = _call([(429, LIMITED), (200, {"ok": True})], method="PUT")
    assert r.status_code == 200 and len(sent) == 2


def test_brand_analytics_rate_limits_are_waited_out_without_a_waf():
    r, client, sent, slept = _call([(429, LIMITED), (200, {})], brand_analytics=True)
    assert r.status_code == 200 and client.ratelimit_count == 1 and client.remint_count == 0


def test_the_two_429s_are_told_apart_by_the_body():
    req = httpx.Request("GET", "https://x")
    assert zt.is_rate_limited(httpx.Response(429, json=LIMITED, request=req))
    assert zt.is_rate_limited(httpx.Response(429, json={"message": "Rate limit exceeded"},
                                             request=req))
    assert not zt.is_rate_limited(httpx.Response(429, text="", request=req))
    assert not zt.is_rate_limited(httpx.Response(429, text="<html>Too many</html>", request=req))
    assert not zt.is_rate_limited(httpx.Response(429, json={"error": "other"}, request=req))
    assert not zt.is_rate_limited(httpx.Response(400, json=LIMITED, request=req))


def test_the_section_line_counts_the_waits():
    client = zt.ZeptoClient(TENANT, "jwt", "waf", ["b"])
    rec = zr._Recoveries(client)
    client.remint_count, client.ratelimit_count = 1, 3
    assert rec.note() == " · 1 WAF renewal(s) · 3 rate-limit wait(s)"


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
    print(f"\n{len(tests) - failed}/{len(tests)} Zepto client tests passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run())
