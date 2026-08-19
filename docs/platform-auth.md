# Platform Auth — logging in to marketplace dashboards

> **Not** app-user auth. `app/routes/auth.py` is humans logging into Foresight (JWT).
> This is Foresight logging into Blinkit, Zepto and friends. See the glossary in
> [jobs.md](jobs.md) for the other overloaded terms.

**Status: built, wired and tested locally 2026-08-04** (branch `feature/auto-auth`).
Both Blinkit dashboards log in, probe and refresh over plain HTTP with **no browser**;
unattended login and self-healing are proven end to end. Migration `f3c8d1a5e7b2` applied.
**Not yet on the VM** — see [Open / next](#open--next).

---

## The finding that shaped this

Auto-forwarding made the *secret* machine-readable. The assumption was that we'd then
drive the existing headful login flows headlessly. Recon on 2026-08-04 showed that was
unnecessary — **both Blinkit logins are ordinary REST calls.**

The "Cloudflare blocks httpx" rule that shaped earlier designs is about Blinkit's
**data** endpoints. It does not hold for the login endpoints, which were verified
reachable from plain httpx.

That deletes an entire category of risk: no headless detection, no volatile selectors
(the marketing login modal's classes are generated and explicitly documented as
unstable), no Chromium at login time.

## The two flows

### Blinkit marketing — `brands.blinkit.com`

```
POST /adservice/v1/users/request-magic-link      X-User-Email: <email>, body {}
   -> Blinkit emails a SendGrid-wrapped Firebase action link
POST identitytoolkit …/accounts:signInWithEmailLink?key=<apiKey>   {email, oobCode}
   -> idToken + refreshToken
```

The link is **not** sent by Firebase — Blinkit's own API issues it. Consuming it *is*
stock Firebase, on a Google host, so no Cloudflare is involved. There is no backend
session exchange: the Firebase ID token *is* the credential (`firebase_user_token`).

The API key is public, read at login time from `brands.blinkit.com/config.js` (a
one-line file) so a rotation on Blinkit's side doesn't strand us.

**The session is then synthesized** — we mint the three-layer storage_state
(cookies + localStorage + Firebase IndexedDB) from the REST tokens instead of scraping
it out of a real browser. Cookies are deliberately empty; Chromium earns its own
Cloudflare cookies on first navigation. Verified: a synthesized session scraped 52
campaigns.

> ⚠️ **The link is single-use.** If a mail scanner or a human opens it first, the
> exchange fails with `EXPIRED_OOB_CODE`/`INVALID_OOB_CODE`. Unwrapping stops at the
> redirect that exposes the `oobCode` and never loads `/auth/action`, because that
> page's JS is what consumes it.

### Blinkit seller — `partnersbiz.com`

Not Firebase. A plain REST auth service:

```
POST /auth/api/v1/email/send_otp        email_id=<email>            (form-encoded)
POST /auth/api/v1/email/verify_otp      email_id, verify_code       -> access + refresh
GET  /v1/get-user-entities/                                         -> the entity
POST /auth/api/v1/tokens/rotate         refresh_token               -> fresh pair
```

**The entity is part of the credential.** The old Playwright login clicked a company
card on an "account selection" screen; that selection is pure client state
(`localStorage["myEntity"]`), injected into every data call as `X-Entity-Id` /
`X-Entity-Type` by the app's axios interceptor. Verified: `/v1/*` returns
`403 ERROR_CODE:11 Unauthorised` without those headers and `200` with them.

> **Header spelling differs by service and both are load-bearing:** login calls send
> `app_client: partnersbiz-web`, data calls `partnerbiz-web` (the typo is Blinkit's).

## Session lifetime — why sessions kept dying

The marketing app force-logs-out on a **client-side** check, independent of whether the
Firebase refresh token is still valid:

```js
(persistence === "true" ? lastLoginTime + SEVEN_DAYS : lastLoginTime + ONE_DAY) < Date.now()
```

`lastLoginTime` and `persistence` are localStorage keys, captured into a stored
storage_state and then **frozen** — every restore replays the original login timestamp.
Our scrapers drive the real SPA, so they run straight through this gate.

So a marketing session expires **7 days after capture — or 1 day** if the "Keep me
signed in" click silently failed (it was best-effort, warn-only).

Two consequences, both handled:

- Synthesized sessions always set `persistence=true` and stamp `lastLoginTime` fresh.
- `refresh()` re-stamps it. The Firebase refresh token long outlives the 7-day gate, so
  without this a session dies while its credential is still perfectly good.

Seller has the same shape: a ~7-day window that `tokens/rotate` slides. **Neither
platform ever needs a second secret** as long as it's refreshed periodically.

## Layout

```
platform_auth/
  types.py                      Authenticator contract + AuthSession
  registry.py                   slug -> Authenticator        <- the extension point
  service.py                    login / ensure / refresh     <- what callers use
  store.py                      encrypted persistence
  errors.py                     typed failures
  inbox/{base,imap,manual}.py   where the secret comes from
  marketplaces/blinkit/{marketing,seller}.py
```

**Two levels under `marketplaces/`** because a marketplace is not a login — Blinkit
alone has two unrelated ones. Mirrors `campaign_manager/marketplaces/`. Adding Zepto is
a folder plus one registry entry; nothing above changes. Zepto and Instamart are already
registered `wired=False`, so selecting them fails with a real message instead of
silently doing something else (same trick as `scraper/public/providers.py`).

### AuthSession — three views of one credential

A session is no longer just a storage_state. `AuthSession` carries the **native
credential** (`raw`) plus two projections: `storage_state` for consumers that drive a
browser, and `headers` for those that don't. Callers take whichever they need.

Stored rows are versioned (`__v: 2`). Rows written before this module are bare
storage_states and are read as legacy — **no backfill required**.

### The service ladder

`ensure()` climbs only as far as it must: stored session that probes clean → refresh →
full login. Probing is cheap on both platforms (one API call, no browser).

- **Lazy, never scheduled.** Re-auth fires only when a session is actually dead;
  repeated logins from one datacenter IP look like a bot.
- **Serialized** per `(tenant, platform)` with a Postgres advisory lock. Two concurrent
  OTP requests genuinely cross wires — the second invalidates the first's code.

## Where logins run, and when

Two mechanisms, complementary rather than alternative:

- **On demand — `ensure()`.** Whatever needs a session calls it and gets a working one.
  This is the mechanism; it recovers from expiry.
- **Scheduled — `auth.refresh`.** A daily job that *prevents* expiry. It costs one API
  call per platform, consumes no secret and sends no email, so it cannot lose to a mail
  scanner or forwarding lag the way a full login can.

**Logins themselves are never scheduled** — repeated logins from one datacenter IP are
what looks like a bot. The schedule only refreshes.

**Everything runs on the VM.** Both logins are now plain HTTP that Render *could* make,
but shouldn't: Blinkit is India-geo, so a login from Render's US IP shortly before the
same account is used from Mumbai is exactly what fraud heuristics watch for — and it
would put the mailbox app password into Render's environment too. `AUTH_ALLOW_LOGIN=false`
on Render makes `ensure()` raise `SessionExpired` there instead of silently logging in
from the wrong country. A UI "Reconnect" button should **enqueue** `auth.refresh`.

```bash
python -m cli auth refresh-all -t <tenant>            # what the job runs
python -m cli schedules add auth.refresh -t <tenant> --cron "0 5 * * *"
```

> ⚠️ **`refresh-all` skips entirely if the tenant has any other job active.** Seller
> rotation issues a new token pair and **kills the old one** — verified 2026-08-04: the
> previous access token returns `401 Access token not authenticated` immediately after a
> rotate. Lanes run in parallel, so a refresh firing during a seller scrape would break
> that scrape. Scheduling it at a quiet hour is a hope, not a guarantee; the guard is what
> keeps it correct when someone adds a schedule a year from now.
>
> The guard deliberately ignores `auth.refresh` jobs when counting — otherwise the job
> would see itself and skip forever, the same self-blocking loop that broke
> `monitor.heartbeat` in July.
>
> Skipping is safe: refresh is preventive, sessions still have days left, and `ensure()`
> recovers regardless. For the same reason `refresh-all` exits 0 even when a platform
> fails — a session that could not be refreshed is usually still valid, and failing here
> would page a human for something that self-heals.

## Failure handling

What a scrape sees when the session is dead, rung by rung:

```
load session ─ probe ok? ──────────────────────────► use it
     │ no session          │ probe failed
     ▼                     ▼
   login              take the lock, re-probe (someone else may have fixed it)
                           │ still dead
                           ▼
                       refresh ──ok──► use it
                           │ can't
                           ▼
                     login (≤2 attempts) ──ok──► use it
                           │ failed
                           ▼
              mark_failed → raise → exit 3 → jobs.error='auth_expired'
```

**Retries are selective, not blanket.** Each attempt burns a *new* secret, so retrying
the wrong failure wastes OTP quota and looks like an attack:

| Failure | Retried? | Why |
|---|---|---|
| Mail didn't arrive in time | Yes | Forwarding lag; a fresh request usually lands |
| `EXPIRED_OOB_CODE` / consumed link | Yes | A mail scanner opened the single-use link first — recurring hazard |
| Address is not a user on that platform | No | Config error; a second attempt cannot fix it |
| No credentials / password required | No | Same |
| Manual (`--manual`) logins | No | Don't silently re-prompt a human |

**Circuit breaker.** After `MAX_CONSECUTIVE_FAILURES` (3), auto-login stops attempting
and demands a human. Auto-login that fails forever is worse than the manual state it
replaced: it hammers a login endpoint from one datacenter IP and buries a broken config
in noise. Any successful login clears the counter.

**Failures are always recorded.** Every path exits through `mark_failed`, so
`consecutive_failures` can't drift — an earlier version only recorded
`SecretNotFound`, leaving a login that died at the token-exchange step invisible to
anything built on that counter.

**`auth_expired` is real now.** Jobs run as subprocesses, so a typed exception in the
child cannot reach the runner — only an exit code can. `cli/main.py` catches `AuthError`
and exits **3**; `jobs/runner.py::_classify_failure` maps that to
`jobs.error='auth_expired'`. So auth failures are filterable in Cloud Logging instead of
hiding among anonymous `exit_1`s.

> ⚠️ **The advisory lock holds its own connection, deliberately.** `pg_advisory_lock` is
> scoped to a *connection*, and an `AsyncSession` returns its connection to the pool on
> commit — which this code does several times mid-login. Locking and unlocking through
> the caller's session can therefore land on two different connections: the unlock
> silently no-ops and the lock leaks onto a pooled connection that never closes,
> permanently wedging that `(tenant, platform)`. Same class of bug as the stale `running`
> jobs that needed a reaper. A dedicated connection also gives free crash recovery — if
> the process dies, the connection drops and Postgres releases the lock. `lock_timeout`
> is set so a hung login can't block other callers indefinitely.

## CLI

```bash
python -m cli auth platforms                              # registry + wiring status
python -m cli auth login blinkit -t <uuid> [--email x] [--manual]
python -m cli auth refresh blinkit -t <uuid>              # no email needed
python -m cli auth probe blinkit -t <uuid>                # is it actually alive?
python -m cli auth status -t <uuid>                       # all platforms + health
```

`auth blinkit` / `auth blinkit-seller` still work as aliases. **First login for a tenant
should be `--manual`** — it captures the address and is where anything unexpected
surfaces; every later one can be automatic.

## Credentials — per tenant, per platform

Two tables, deliberately separate. **Credentials are the login input** (long-lived,
human-entered); **sessions are the output** (short-lived, machine-rotated). Merging
them would mean every token refresh rewrites the row holding the password.

`platform_credentials` — unique on `(tenant_id, platform)`:

| Column | Encrypted | Notes |
|---|---|---|
| `login_email` | No | PII, not a secret; must stay readable to render status and decide auto-login eligibility |
| `encrypted_password` | **Yes** (Fernet, same key as sessions) | Null for passwordless platforms |
| `extra` | No | JSON — a sub-account id, a portal code; lets a new marketplace need no schema change |

**Blinkit needs no password** — both dashboards are passwordless by design, which is
exactly why auto-login is tractable: possession of the mailbox *is* the credential.
**Zepto uses email + password**, so `Authenticator.needs_password` gates it and
`resolve_credentials()` refuses to start a login without one rather than failing later
in a way that looks like the platform's fault.

```bash
python -m cli auth credentials set blinkit -t <uuid> --email ops@brand.com
python -m cli auth credentials set zepto   -t <uuid> --email ops@brand.com --password
python -m cli auth credentials list -t <uuid>      # never displays the password
python -m cli auth credentials remove zepto -t <uuid>
```

`--password` prompts with hidden input and confirmation; it is never passed as an
argument (shell history), never echoed, never logged. A `set` that omits `--password`
will not blank an existing one — the common case is updating only the address.

## Config

```env
AUTH_INBOX_USER=foresight-auth@yourdomain.com   # the forwarding mailbox
AUTH_INBOX_APP_PASSWORD=xxxxxxxxxxxxxxxx        # Gmail App Password (16 chars, needs 2FA)
AUTH_INBOX_HOST=imap.gmail.com                  # default — omit unless it differs
AUTH_INBOX_FOLDER=INBOX                         # default
AUTH_INBOX_TIMEOUT_SECONDS=120                  # default; per-platform rules override
```

Only the first two are required. Unset = auto-login is unavailable and login falls back
to prompting a human. Nothing else breaks.

`imaplib` is stdlib, so **no new dependency**. Needs adding to the VM's `.env` (and
Render's only if the API ever triggers a login — today it should only enqueue).

## Mail rules — `platform_auth/mail_rules.py`

Everything the reader knows about *which* email to look for lives in that one file, as
data: senders, subjects, extraction patterns, and timing. Adding a marketplace or fixing
a changed subject line is a one-line edit, never a code change.

Filters run strongest-first, and the order matters more than the individual rules:

1. **Recipient** — the login address must appear in **To/Cc**. The filter that keeps
   tenants apart, and not optional. See the warning below.
2. **Arrival time** — only mail newer than the request can answer it: without it a stale
   OTP from an earlier attempt reads as valid and the login fails a minute later for
   reasons that look unrelated.
3. **Sender** (`from_contains`) — From / Return-Path / Sender. Use full addresses where
   known; a bare domain is too loose when one company runs several products.
4. **Subject** (`subject_contains`) — **required** for verified platforms. Advisory mode
   exists only for platforms whose subjects are still guesses, so an out-of-date guess
   can't veto a login.
5. **Shape** (`body_pattern`) — a message that passes every filter but yields no code is
   not the message.

> ⚠️ **This mailbox receives other people's login mail.** Verified 2026-08-04: `tech@`
> holds "Sign in to Blinkit Brand Central" addressed to three different accounts —
> identical sender, identical subject. Without the recipient check a login consumes
> another tenant's single-use secret: wrong account, or their code silently burned.
> Match **To/Cc, never Delivered-To** — forwarding stamps Delivered-To with the shared
> mailbox on every message, so including it makes the check pass for everything.
>
> Two related traps found in the same scan: `blinkit_seller` matched on `"blinkit"`,
> which caught the *marketing* sender `brands@blinkit.com` (a six-digit pattern would
> happily find an "OTP" in a report); and `brands@blinkit.com` sends "Dashboard Reports"
> and "Ad Campaign Alert" many times a day, so advisory subjects were unsafe.

**Timing is per platform**, because mail is not instant — the platform queues it,
SendGrid relays it, forwarding adds a hop. `initial_delay_seconds` waits before the
first poll rather than burning IMAP round-trips on an empty mailbox:

| Platform | Initial delay | Timeout | Why |
|---|---|---|---|
| `blinkit` | 8 s | 120 s | Magic link, SendGrid-relayed |
| `blinkit_seller` | 12 s | 150 s | OTP has been slower, and a stale OTP is the prime suspect for the one historical login failure |

**Verified 2026-08-04** against the real mailbox — `verified=True` on both Blinkit rules:

| Platform | From | Subject |
|---|---|---|
| `blinkit` | `Blinkit Brand Central <brands@blinkit.com>` | `Sign in to Blinkit Brand Central` |
| `blinkit_seller` | `Partners Biz <noreply@partnersbiz.com>` | `Your OTP for PartnersBiz login` |

Zepto and Instamart are still guesses (`verified=False`, and `wired=False` in the
registry so nothing can reach them). To pin a new platform:

```bash
python -m scripts.inbox_scan --limit 25 --email <tenant login address>
```

Headers only, never bodies — bodies hold live magic links and OTPs. With `--email` it
applies the recipient filter exactly as a real login would, so the verdict column shows
`MATCH`, `OTHER RECIPIENT`, or `rejected, subject` per message.

## Done

- [x] Migration `f3c8d1a5e7b2` — `platform_credentials` + session health columns.
- [x] Mail rules pinned to real messages and marked `verified`.
- [x] Unattended login proven for both platforms (~17 s each, zero human input).
- [x] `ensure()` wired into all three scrape entry points + `campaign_manager` `setup()`.
- [x] Seller scraping is browserless — works on legacy sessions too.
- [x] `auth.refresh` job type + `cli auth refresh-all`, with the busy-skip guard.
- [x] `AUTH_ALLOW_LOGIN` guardrail.
- [x] **Superseded code deleted** — `scraper/platforms/blinkit/auth.py`,
      `.../seller/auth.py`, `ads_service.reconnect_blinkit`, its two schemas,
      `scripts/reconnect_blinkit.py`, and the frontend `ReconnectBlinkit` component /
      hook / api function. The seller `selectors.py` login block went with them.
      `scraper/utils/session.py` **stays** as a re-export — `ads_service` and the inert
      `ad_campaigns/` still import it.

## Open / next

- [ ] **Create the refresh schedule:**
      `cli schedules add auth.refresh -t <tenant> --cron "0 5 * * *"` (before the 9am
      dashboard scrapes).
- [ ] **VM deploy** — merge to `main` (the VM only runs `main`), add `AUTH_INBOX_*` to its
      `.env`, restart the runner.
- [ ] **Set `AUTH_ALLOW_LOGIN=false` in Render's environment.**
- [ ] **Apply the alert policies** — they are written up as reviewable JSON in
      [deploy/alerts/](../deploy/alerts/README.md) with the `gcloud` commands, but have
      **not been created in GCP yet**. Until they are, an auth failure reaches a log and
      not an inbox. The README includes a forced-failure test, because a policy with a
      filter that silently matches nothing is the exact state to avoid.
- [ ] The busy-skip path in `refresh_all` is logic-verified but never exercised against a
      real running job (creating a fake pending job risks the VM runner claiming it).
      Worth watching the first time a schedule overlaps a scrape.
- [ ] Zepto / Instamart authenticators — registered `wired=False`; their mail rules are
      still guesses (`subject_required=False` so they cannot veto).

## Verified 2026-08-04

| Claim | Evidence |
|---|---|
| Marketing login needs no browser | `request-magic-link` 200 → `signInWithEmailLink` 200 over httpx |
| A synthesized session really works | production marketing scrape: **52 campaigns**, 156 SoV rows |
| Seller login needs no browser | `send_otp` / `verify_otp` 200 over httpx |
| Seller rotation works | fresh pair issued, no OTP |
| Entity headers are required | same POST: **200** with them, **403** without |
| Seller scraping needs no browser | production seller scrape: **1326 rows**, then **1043** after a refresh |
| `probe()` discriminates | `True` live token, `False` bogus token |
