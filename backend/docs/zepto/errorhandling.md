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

`scraper/platforms/zepto/dashboard_data/seller/scraper.py`

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

**It is "try later", not a broken scrape.** The sales section drops the unready newest
day, asks again for the rest of the window, and records the day as *not ready* — not as a
failure (P45; it used to throw the whole 8-day window away and fail the run). The next
run's window covers that day. If nothing in the window is ready yet, the section
completes empty.

---

## 2. Exit codes — the only channel a job has

Jobs run as **subprocesses**, so a typed exception in the child cannot reach the
runner. The exit code is the entire vocabulary.

| Code | Meaning | Runner records |
|---|---|---|
| `0` | success | `status='success'` |
| `1` | a section lost fetches (after the re-check, §4) or failed | `status='failed'` |
| **`3`** | `AUTH_EXPIRED_EXIT_CODE` | **`jobs.error='auth_expired'`** |

`cli/main.py` catches `AuthError` and exits 3. That is what makes auth failures
filterable in Cloud Logging instead of hiding among anonymous `exit_1`s. An expired session
in ANY section (PO included, since P46) stops the run — later sections cannot work either.

Each section returns a `SectionResult`, and that one object decides the exit code, the
section's closing log line and its `scrape_jobs` row: success, or **failed** with
`partial: N fetch(es) lost — …` and the rows that did land (P35 — rows used to say success
while the job exited 1).

> ⚠️ **Job failures must log at ERROR or the alert never fires.** The Cloud Monitoring
> policy matches `severity>=ERROR`; failures used to log at WARNING and were invisible.
> Any new failure path inherits this rule.

---

## 3. The recovery ladder

Three different failures, three different recoveries, handled **per call** inside
`ZeptoClient.request()`.

```
        ┌─ 429 JSON "rate limit exceeded" → Zepto says slow down → wait, same token → retry
        │                                    (5 s, 15 s, 30 s, then give up — since 2026-10-06)
call ───┼─ 202 / 429 ──→ WAF token gone ──→ _remint()  ──→ retry
        │                                    (unbounded, ~10s Chromium)
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

## 4. Lost fetches and the re-check

A fetch that still fails after its own retries (§7) is **not** dropped and not fatal on
the spot: the section queues it as *lost* and carries on with the rest. Once the section's
first pass is done it waits `RECHECK_WAIT_S` (20 s) and replays every lost fetch once.
Whatever still fails goes on `SectionResult.lost`, the section saves everything that did
come back, and the run exits 1 so the alert fires.

What counts as one fetch: a sales day's product list, one city on one day, one ad day's
campaign list, one analytics view, one campaign's keyword detail, one PO's line items
(P15 — a failed PO used to be skipped with a warning, indistinguishable from a PO with no
lines), one catalogue campaign detail.

Two special cases in the ads section:

- **Three auth failures in a row = the session is gone.** The section stops, saves what
  it already fetched, and the run exits 3 — carrying on used to burn ~150 requests to
  save nothing.
- **A blank ad day** (every metric "-") is retried once after 6 s, then `blank_ads_day`
  decides: yesterday → *not ready*; an older day we hold spend for → keep the stored rows;
  otherwise → save genuine zeros (a day every campaign was paused).

### What is never retried

A **timeout**, on any call. The call may have landed and we simply never heard; replaying
it blindly is how a retry becomes a second unintended write. The client resends only what
was refused **unread** — a 401, a WAF challenge, Zepto's own rate limit — so a resent write
cannot apply twice. (`retry_writes=` is still accepted and changes nothing since
2026-09-21.)

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
| `429` (empty body) | **rate limiting** | **missing `waf-enabled: false` header** | `_remint` |
| `429` JSON `{"error":"rate limit exceeded"}` | rate limiting | **real** rate limiting, Zepto's own | wait 5/15/30 s, same token |
| `404` bare `text/plain` | wrong URL | missing `x-proxy-target: brand-analytics` | not automatic — fix the call |
| `500` on `/vendor/*` | our bug | Zepto's upstream exceeded its own gateway timeout | `_post_5xx_retry` (5/15/45 s) |
| `500` on `/ads-bff/*` | our bug | same gateway behaviour | `_ads_request` (3/8/20 s) |
| `200` + `{"data": null}` | empty error | genuinely **no rows** for that filter | `or {}` — returns empty |

### The 429 that cost an afternoon

`waf-enabled: false` reads like a client hint you can ignore. It is not — it is
**required**. Send the WAF token without it and CloudFront answers `429`, which reads
exactly like rate limiting. Three wrong diagnoses were chased (rate limit, IP block,
unverified token) before the cause turned out to be a header visible in the very first
capture.

> **If you see a 429 here, check the headers before theorising about the network.**

The one exception, found 2026-10-05: a 429 whose body is Zepto's JSON
`{"error":"rate limit exceeded","data":null}` is a genuine limit (the campaign catalogue
reading a campaign every 0.4 s drew it). Re-minting does nothing for it; until P53 the
client re-minted anyway and the ~10 s browser launch hid the problem. It now waits it
out, and the waits are counted on the section's closing line.

### The 200-with-null-data case

Verified 2026-08-31: `grn/filter` for 30–31 Aug returned HTTP 200 with
`{"success":true,"data":null}` — a filter window matching nothing, not an error.
`_get` returns `{}` so callers read an empty list instead of raising `AttributeError` on
`None`.

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

**Only 5xx is retried** (`scraper/utils/retry.retry_call`, one helper for every Zepto
endpoint family, each with its own measured waits). A 4xx will not fix itself, and auth
errors already have their own recovery one layer down.

The waits are deliberately long because the endpoint does not fail in isolated blips:
four consecutive attempts each timed out at ~23s and the whole 103s stretch failed,
then the next two calls succeeded in 15.7s and 5.2s. A short backoff would land inside
the same bad patch. 5/15/45 spans ~160s of waiting plus ~90s of attempts, which cleared
it in testing.

### What a total PO failure actually costs

One dataset for one run. `run_po`'s `_try` guard catches the exception so a flaky
endpoint cannot cost the other two, the endpoint is recorded as lost (the run exits 1),
and the upsert writes nothing for an empty list — **previously stored rows survive**.

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

**A window wide enough to exceed 2,000 rows will silently truncate.** Nothing warns
(P4 — left as is; the 30-day default is far below it). Split the window instead.

Product performance pages too (50 a page, P47): a day with more than 50 selling SKUs used
to be cut off silently.

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
| a write fails mid-save | **that section's save rolls back whole** — each `save_*` is one transaction, one commit |

The honest caveat is one level up: a Zepto **run** is not all-or-nothing. Sections save
independently (sales can land while ads fails), and a section saves what it fetched even
when some fetches were lost. Re-running the window is safe and is the fix — idempotency is
what makes that true, and the daily re-scrape windows (8 / 30 / 3 days) do it
automatically.

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
LOG_LEVEL=DEBUG cli scrape zepto -t <tenant> --sales --no-save
```

`--no-save` is the first thing to run on a new box or after a code change — it exercises
auth, the WAF mint and every fetch while writing nothing.

At `DEBUG`, `_get` / `_post` log the status of any call ≥400 with its label, which is
usually enough to tell which of the three endpoint families misfired. At the default
level a run is one line per step, tagged `zepto·<tenant>·<section>`, with each section's
recoveries (WAF renewals, re-logins, rate-limit waits) counted on its closing line.

---

## 13. Failure modes with no handling yet

Named honestly rather than left to be discovered:

- **Multi-brand.** `discover_ids` takes `brandCategoryList[0]`. An account with several
  brands silently scrapes only the first. Parked: clients are single-brand.
- **Pagination overflow.** Past `PO_MAX_PAGES × PO_PAGE_SIZE` = 2,000 rows, data is
  dropped without a warning (P4).
- **Partial runs.** See §10 — sections save independently; no staging layer on the
  private path.

Tests now exist (`seller/tests/`: parser, run, client — plus the campaign manager's Zepto
tests); live behaviour is still confirmed with `--no-save` runs.
