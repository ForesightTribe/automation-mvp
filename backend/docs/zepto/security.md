# Zepto Private Scraping — Security

What secrets exist, where they live, who can read them, and the ways this system can
hurt the client.

> The client-facing risk here is unusual and worth stating up front: **the most likely
> harm is not a breach, it is logging Brik Oven's own staff out of their dashboard.**
> See §6.

---

## 1. The secrets

| Secret | Lives in | Encrypted? | Scope |
|---|---|---|---|
| Zepto **password** | `platform_credentials.encrypted_password` | ✅ `ENCRYPTION_KEY` | per tenant |
| Zepto **email** | `platform_credentials` | plaintext | per tenant |
| Zepto **JWT** | `platform_sessions.raw` | ✅ `ENCRYPTION_KEY` | per tenant |
| **Mailbox app password** | `.env` → `AUTH_INBOX_APP_PASSWORD` | ❌ file on disk | global |
| **Database URL** | `.env` → `DATABASE_URL` | ❌ file on disk | global |
| **`ENCRYPTION_KEY`** | `.env` | ❌ *it is the key* | global |
| `aws-waf-token` | **nowhere** — never persisted | n/a | anonymous |

### Zepto is the only platform that stores a password

Both Blinkit logins are passwordless — possession of the mailbox *is* the credential.
Zepto wants email + password **and** an emailed OTP, which is why
`Authenticator.needs_password` exists and why `encrypted_password` is finally used.

That makes Zepto's stored secret **materially more valuable than Blinkit's**: a stolen
Blinkit row is useless without the mailbox, whereas a stolen Zepto password plus the
mailbox is a full account takeover. It is also a password the client chose and may
reuse elsewhere.

### The WAF token is not a credential

`aws-waf-token` proves *"a browser exists"*, not *"this is Brik Oven"*. An anonymous
page load with no login mints a valid one. It is deliberately kept out of
`platform_auth` and never written to the database — every job interval outlives its
~5-minute life, so a stored token would be expired essentially every read.

Treat it as disposable. It leaks nothing.

---

## 2. `ENCRYPTION_KEY` — the one that fails quietly

Sessions and passwords are decrypted with `ENCRYPTION_KEY` from the environment. It
**must match byte-for-byte** across every box that touches the shared database:
laptop, VM, Render.

> ⚠️ **A wrong key does not fail loudly.** The box reads the row and simply cannot
> unlock it. There is no "wrong password" message — just auth that never works.

This is also what makes the VM shift cheap: **there is nothing to copy.** Sessions are
not files. Any box with the same `DATABASE_URL` + `ENCRYPTION_KEY` decrypts the session
captured on a laptop and just runs.

The flip side is that the key is a **single point of compromise for every tenant on
every platform**, not just Zepto.

---

## 3. The shared auth inbox

The OTP is read over IMAP from one shared mailbox, using a Gmail **App Password**
(`AUTH_INBOX_APP_PASSWORD` — not the account password).

The mail rule (`platform_auth/mail_rules.py`) is deliberately tight:

```python
from_contains      = ("mailer@zeptonow.com",)     # full address, not bare "zepto"
subject_contains   = ("email otp",)
subject_required   = True
recipient_required = True
body_pattern       = r"(?<!\d)(\d{4})(?!\d)"
timeout_seconds    = 120.0
```

Three security properties here are load-bearing:

- **`from_contains` is a full address.** A bare `"zepto"` is the same too-loose pattern
  that once let `blinkit_seller` match the marketing sender.
- **`recipient_required` is the per-tenant filter.** The `To:` header survives
  forwarding as the tenant's own address, so one shared mailbox cannot cross-wire two
  tenants' OTPs.
- **Four digits, not Blinkit's six.** Materially more collision-prone, so the reader's
  visible-text strip matters *more* here, not less. The real mail is only ~110
  characters of visible text and yields exactly one candidate.

The OTP is valid for **5 minutes** and the code enforces a budget inside that
(`initial_delay 8s`, `timeout 120s`, observed arrival 10–25s).

### The shared mailbox is a concentration risk

Every tenant's OTPs for every platform arrive in one inbox. Anyone with that app
password can authenticate as any tenant on any platform. It is the highest-value
secret in the system after `ENCRYPTION_KEY`.

---

## 4. What is never logged

By construction:

- Passwords are prompted, never passed as an argv value (`--password` takes no value),
  so they do not reach shell history or the process table.
- The OTP is consumed in memory.
- JWTs are not printed. The WAF token logs only its **length**
  (`"Zepto WAF token minted (1234 chars)"`).
- `cli auth credentials list` shows what is stored, not the secrets.

Per-run job logs go to `logs/jobs/<date>/` and ship to Cloud Logging. **Do not add a
debug line that prints `session.raw`** — it would put a live JWT into a retained log
sink.

---

## 5. Where logins are allowed to happen

```
AUTH_ALLOW_LOGIN = true    on the VM (Mumbai)
AUTH_ALLOW_LOGIN = false   on Render (US)
```

With it `false`, `ensure()` raises `SessionExpired` instead of silently logging in from
the wrong country.

Blinkit is India-geo: a login from a US IP minutes before the same account is used from
Mumbai is exactly what fraud heuristics watch for. It also keeps the mailbox app
password out of Render's environment entirely.

Zepto is less geo-sensitive than Blinkit, but the rule is applied uniformly — a UI
"Reconnect" button should **enqueue** a job for the VM, never log in from the API.

---

## 6. ⚠️ Single-session eviction — the real client risk

**Zepto permits one session per user, server-enforced.** Every login we perform
silently kills whoever is on the dashboard, and vice versa.

Consequences, in order of how much they matter:

1. **A nightly `auth.login` job logs the client's own team out.** This is why the
   schedule is documented as `--disabled` and stays that way **until Brik Oven
   provisions a service user**. Enabling it is a business decision, not a technical
   one.
2. **We share `varun@brikoven.com`.** During testing the session was evicted every
   3–4 minutes, and three times in ten minutes on 2026-09-01. Recovery is automatic,
   but each cycle burns a single-use OTP.
3. **The reauth cap exists because of this.** `MAX_REAUTH_PER_RUN = 2` stops an
   unbounded ping-pong with a human from burning a whole day's logins in minutes and
   tripping the circuit breaker.

> **The correct fix is a dedicated service login from Brik Oven.** Everything else is
> containment. This should be raised with the client rather than engineered around.

---

## 7. Tenant isolation

Every one of the eleven tables carries `tenant_id` as a FK to `tenants.id`, and it is
part of every `upsert_key`. Credentials and sessions are keyed on
`(tenant_id, platform)`.

There is **no row-level security in the database** — isolation is enforced in the
application layer. A query that forgets `WHERE tenant_id = …` will happily read another
client's data. Every service function takes `tenant_id` and every index leads with it,
which makes the right thing also the fast thing, but it is a convention, not a
guarantee.

---

## 8. The shared database

⚠️ **One Supabase database sits behind every branch.** Consequences:

- A migration run from one branch changes the database every other branch reads,
  including branches whose code has not pulled it.
- A scrape run from a laptop writes **production** rows. `--no-save` exists for this
  reason and should be the default reflex on any new code path.
- Connection budget is real: the pooler allows 25. API 5 + runner 3 + subprocesses.
  The runner unit pins `DB_POOL_SIZE=4`.

---

## 9. What this system is allowed to do

The three scrapes are **read-only**. They issue GETs and filter-POSTs and never mutate
anything on Zepto.

The write path — budgets, bids, campaign start/stop — is the **Campaign Manager**, a
separate system behind a gated choke-point with a `--live` flag that defaults off. It
shares this transport but nothing in `docs/zepto/` grants write access.

Worth knowing because they share `transport.py`: `retry_writes=False` is passed by
every scrape call precisely so that flag stays honest if one of these paths ever gains
a write.

---

## 10. Handling the client's data

The private tables hold commercially sensitive figures that are **not** public:
cost price (`zepto_po_items.unit_price` — the margin Zepto takes), ad spend, RoAS, and
per-SKU revenue.

- Exports (`scripts/zepto_export_private.py`) write to `backend/out/` — **gitignored,
  and it must stay that way.**
- Do not paste PO or spend figures into tickets, chat or screenshots without checking
  who can see them.
- `.env` is **not in git** and is recreated by hand on each box. Verify with `ls -a` —
  dotfiles do not show in a bare `ls`.

---

## 11. Checklist before putting this on the VM

- [ ] `ENCRYPTION_KEY` on the VM matches local **exactly**
- [ ] `AUTH_INBOX_USER` + `AUTH_INBOX_APP_PASSWORD` present (strip the spaces Google
      shows in the app password)
- [ ] `AUTH_ALLOW_LOGIN=true` on the VM, `false` on Render
- [ ] `sudo systemctl restart foresight-runner` after editing `.env` — systemd reads it
      via `EnvironmentFile` and will not pick up changes otherwise
- [ ] `cli auth probe zepto -t <tenant>` returns healthy **from the VM**
- [ ] `cli scrape zepto-sales -t <tenant> --no-save` completes before anything is
      scheduled
- [ ] Any `auth.login` schedule created `--disabled`
- [ ] Service-user question raised with Brik Oven
