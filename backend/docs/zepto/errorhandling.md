# Zepto Private Scraping — Error Handling

How this system fails, what recovers itself, and what needs a human.

The governing idea: **failures that look alike are not alike.** A `401` and a `429`
both mean "your call was rejected", but one costs a single-use emailed OTP to fix and
the other costs a header. Telling them apart is most of this document.

---

## 1. The error taxonomy

Defined in [`platform_auth/errors.py`](../../platform_auth/errors.py). All inherit
`AuthError`.

| Exception | Means | Recoverable? |
|---|---|---|
| `SessionExpired` | stored session no longer valid | **Yes** — log in again |
| `NoSession` | never logged in for this tenant/platform | needs one command |
| `LoginFailed` | the login ran but produced no session | **No** — needs a human |
| `SecretNotFound` | no OTP email arrived in time | **No** — check forwarding |
| `UnknownPlatform` | bad slug | config error |
| `PlatformNotWired` | registered as a placeholder, no implementation | by design |

`LoginFailed` vs `SessionExpired` is the important split. The first is routine and
self-healing; the second needs someone to look. Before this module both arrived as bare
`RuntimeError`s with prose messages, so nothing could react to either.

### `NoDataYet` — not an auth error, and not a failure

`scraper/platforms/zepto/dashboard_data/seller/scraper.py:299`

```python
class NoDataYet(RuntimeError):
    """Zepto accepted the request but has not computed that date range yet."""
```

The session is fine, the parameters are fine — **the day simply is not ready.**
Zepto recomputes once each morning, and asking too early returns a structurally
different response: the `headers` block carrying the totals is **absent** and every
point in `metrics` is null.

```
2026-08-28   headers present   gmv ₹64,280
2026-08-29   headers present   gmv ₹54,275
2026-08-30   headers ABSENT    gmv null      ← still not ready the next morning
```

Reading `data["headers"]` blind raised a bare `KeyError('headers')`, which surfaced as
`Scrape failed: 'headers'` — no indication that the only problem was asking too early.

**Report this as "try later", not as a broken scrape.** The CLI defaults `--to` to
yesterday precisely to avoid it; this path is only reached when that default is
overridden.

---

## 2. Exit codes — the only channel a job has

Jobs run as **subprocesses**, so a typed exception in the child cannot reach the
runner. The exit code is the entire vocabulary.

| Code | Meaning | Runner records |
|---|---|---|
| `0` | success | `status='success'` |
| `1` | anything else | `status='failed'` |
| **`3`** | `AUTH_EXPIRED_EXIT_CODE` | **`jobs.error='auth_expired'`** |

`cli/main.py` catches `AuthError` and exits 3. That is what makes auth failures
filterable in Cloud Logging instead of hiding among anonymous `exit_1`s.

> ⚠️ **Job failures must log at ERROR or the alert never fires.** The Cloud Monitoring
> policy matches `severity>=ERROR`; failures used to log at WARNING and were invisible.
> Any new failure path inherits this rule.

---

## 3. The recovery ladder

Two independent failures, two different recoveries, handled **per call** inside
`ZeptoClient.request()`.

```
        ┌─ 202 / 429 ──→ WAF token gone ──→ _remint()  ──→ retry
call ───┤                                    (unbounded, ~10s Chromium)
        └─ 401 ────────→ identity gone ───→ _reauth()  ──→ retry
                                             (bounded — see below)
```

### Why per-call and not per-run

On the shared `varun@brikoven.com` account the session was evicted **three times in
ten minutes** on 2026-09-01 and the run still finished. A per-run health check would
have died halfway through. This is the difference between completing and not.

### The bounded reauth

```python
MAX_REAUTH_PER_RUN = 2
```

Unbounded retry is not "more robust" here — **it is a fight with a human.** Zepto
permits one session per user, so the loop is: we log in, they get evicted, they log
back in, we get evicted. Each cycle burns a single-use emailed OTP and walks the
circuit breaker toward tripping. Left unbounded, "someone opened the dashboard"
becomes "auto-login is suspended for this tenant".

When the budget is spent, `_reauth()` returns `False` and the call fails honestly.

### The unbounded remint

Re-minting is cheap (a page load, no credential, no email), so it has no cap. It also
**relaunches** Chromium rather than holding one open — ~1 GB for ten seconds instead
of ~1 GB for the whole run.

---

## 4. What is never retried, and why

```python
await client.request(..., retry_writes=False)
```

**Every** Zepto scrape call passes this. A `401` is safe to replay — it was rejected
*before* processing, so nothing landed. A **timeout is not**: the call may well have
applied and we simply never heard the answer. Retrying that blindly is how a retry
becomes a second unintended write.

Timeouts are therefore never retried in the client at all. The caller must re-read and
compare.

The scrapes are read-only, so `retry_writes=False` is about **intent**, not necessity —
it keeps the flag honest if any of these paths ever gains a write.

---

## 5. The circuit breaker

[`platform_auth/service.py`](../../platform_auth/service.py)

```python
MAX_LOGIN_ATTEMPTS      = 2      # per login() call; each requests a NEW secret
RETRY_BACKOFF_SECONDS   = 5.0
MAX_CONSECUTIVE_FAILURES = 3     # then stop trying automatically
LOCK_TIMEOUT_SECONDS    = 180    # waiting on another process's login
```

Past three consecutive failures, auto-login **stops and surfaces** instead of retrying.
Two reasons, both real: hammering a login endpoint from one datacenter IP is how an
account gets flagged, and burning OTP quota on a broken config helps nobody. **Any
success clears it.**

A `pg_advisory_lock` keyed on `(tenant, platform)` stops two processes logging in at
once — which matters more for Zepto than anywhere else, since the second login would
evict the first.

Reset by hand with `cli auth reset`.

---

## 6. HTTP failures, decoded

| Status | Looks like | Actually is | Handled by |
|---|---|---|---|
| `401` | auth | auth — session evicted or past midnight IST | `_reauth`, bounded |
| `202` | success | AWS WAF **challenge** — no valid token | `_remint` |
| `429` | **rate limiting** | **missing `waf-enabled: false` header** | `_remint` |
| `404` bare `text/plain` | wrong URL | missing `x-proxy-target: brand-analytics` | not automatic — fix the call |
| `500` on `/vendor/*` | our bug | Zepto's upstream exceeded its own gateway timeout | `_post_5xx_retry` |
| `200` + `{"data": null}` | empty error | genuinely **no rows** for that filter | `or {}` — returns empty |

### The 429 that cost an afternoon

`waf-enabled: false` reads like a client hint you can ignore. It is not — it is
**required**. Send the WAF token without it and CloudFront answers `429`, which reads
exactly like rate limiting. Three wrong diagnoses were chased (rate limit, IP block,
unverified token) before the cause turned out to be a header visible in the very first
capture.

> **If you see a 429 here, check the headers before theorising about the network.**

### The 200-with-null-data case

Verified 2026-08-31: `grn/filter` for 30–31 Aug returned HTTP 200 with
`{"success":true,"data":null}` — a filter window matching nothing, not an error.
`_get_with_auth_fallback` returns `{}` so callers read an empty list instead of raising
`AttributeError` on `None`.

---

## 7. The PO endpoints are genuinely flaky

Measured 2026-08-30: `asn/filter` returned in anywhere from **4.8s to 21s** for the
*same* 31-day window, with roughly **4 failures in 18 attempts**, randomly
distributed. Not the window size (a 31-day window succeeded 5/5), not the payload
(every variant worked), not the call order.

When Zepto's upstream exceeds its gateway timeout, the gateway answers **500** — so the
failure arrives as a server error, not a client timeout.

```python
_PO_RETRY_WAITS_S = (5, 15, 45)
```

**Only 5xx is retried.** A 4xx will not fix itself, and auth errors already have their
own recovery one layer down.

The waits are deliberately long because the endpoint does not fail in isolated blips:
four consecutive attempts each timed out at ~23s and the whole 103s stretch failed,
then the next two calls succeeded in 15.7s and 5.2s. A short backoff would land inside
the same bad patch. 5/15/45 spans ~160s of waiting plus ~90s of attempts, which cleared
it in testing.

### What a total PO failure actually costs

One dataset for one run. `_scrape_zepto_po`'s `_try` guard catches the exception so a
flaky endpoint cannot kill the whole run, and the upsert writes nothing when the list
is empty — **previously stored rows survive**.

That guard was right but incomplete before the retry existed: a single 500 wrote
**zero** ASNs while the API held 76, silently except for one warning line.

---

## 8. Pagination safety

```python
PO_PAGE_SIZE = 100
PO_MAX_PAGES = 20      # bounds the loop
```

All three PO endpoints share the shape `{list_key: [...], total, hasNext}`.
`PO_MAX_PAGES` exists so a misreported `hasNext` cannot spin forever. A 0.4s pause
sits between pages.

**A window wide enough to exceed 2,000 rows will silently truncate.** Nothing warns.
Split the window instead.

---

## 9. Timezone — a silent data bug, not an error

```python
def _po_window(date_from, date_to):
    start = f"{(date.fromisoformat(date_from) - timedelta(days=1)).isoformat()}T18:30:00.000Z"
    end   = f"{date_to}T18:29:59.999Z"
```

Zepto's PO filters take **IST day boundaries expressed in UTC**. Sending plain dates
returns a window shifted by 5h30m, quietly dropping the first and last few hours of
orders. No error — just fewer rows than there should be.

The VM sets `Asia/Kolkata` at provision time for the same class of reason.

---

## 10. Write-path failures

`storage.py` upserts in **chunks** with `ON CONFLICT (upsert_key) DO UPDATE`.

| Failure | Result |
|---|---|
| duplicate keys in one batch | collapsed before insert — `ON CONFLICT` cannot update the same row twice per statement |
| re-running a window | overwrites in place; **never** duplicates |
| null over a real snapshot | prevented by `_KEEP_IF_NULL` COALESCE — see [database.md](database.md) |
| chunk fails mid-run | **that chunk rolls back; earlier chunks are already committed** |

That last row is the honest caveat: a Zepto scrape is **not** all-or-nothing. A failure
partway through can leave a partial window written. Re-running is safe and is the fix —
idempotency is what makes that true.

> This differs from the **public** scrape path, which stages to SQLite and pushes in
> one transaction (see [docs/staging.md](../../../docs/staging.md)). The private path
> has no staging layer.

---

## 11. Failures that need a human

Nothing below recovers on its own.

| Symptom | Cause | Action |
|---|---|---|
| `SecretNotFound` after 120s | OTP mail not arriving | check forwarding to the auth inbox is live |
| `LoginFailed`: "check the stored password" | password changed or wrong | `cli auth credentials set zepto` |
| breaker tripped (3 consecutive) | broken config, or a human fighting us | fix cause, `cli auth reset` |
| `Zepto session carries no brandIds` | account may lack ads access | re-login; check with `auth status` |
| `Zepto session has no jwt` | legacy row from the retired `zepto_seller` path | `cli auth login zepto` |
| `headless Chromium did not produce an aws-waf-token` | WAF challenge did not complete from this IP | check the console loads from that box |
| `logins are disabled (AUTH_ALLOW_LOGIN=false)` | correct on Render, wrong on the VM | set true on the VM only |
| exit 3 on every run | session dead, cannot re-login | `cli auth probe zepto` first |

---

## 12. Diagnosing a run

```bash
cli jobs list                      # status, duration, peak RAM, error
cli jobs logs <prefix>             # that run's log
cli jobs logs <prefix> -f          # live tail
LOG_LEVEL=DEBUG cli scrape zepto-sales -t <tenant> --no-save
```

`--no-save` is the first thing to run on a new box or after a code change — it exercises
auth, the WAF mint and every fetch while writing nothing.

At `DEBUG`, `_get_with_auth_fallback` logs the status of any call ≥400 with its label,
which is usually enough to tell which of the three endpoint families misfired.

---

## 13. Failure modes with no handling yet

Named honestly rather than left to be discovered:

- **Multi-brand.** `discover_ids` takes `brandCategoryList[0]`. An account with several
  brands silently scrapes only the first. Untested.
- **Pagination overflow.** Past `PO_MAX_PAGES × PO_PAGE_SIZE` = 2,000 rows, data is
  dropped without a warning.
- **Partial-window writes.** See §10 — no staging layer on the private path.
- **No automated tests.** Everything here was verified live, by hand.
