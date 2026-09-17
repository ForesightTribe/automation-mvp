# Onboarding — self-serve marketplace connections

**Status: built, not merged.** An admin connects a brand's marketplace accounts from
Settings instead of us collecting the login address and setting up forwarding by hand.

Nothing in `platform_auth/` changed — this is an API + UI layer over it.
See [platform-auth.md](platform-auth.md) for the login machinery itself.

---

## 1. The flow

Settings → **Connect** on any account opens one modal:

| # | Step | What happens |
|---|---|---|
| 1 | Before you start | What the two stages are |
| 2 | Forward emails | Gmail / Outlook / other steps for forwarding to the address we hand over |
| 3 | Connect account | Login email (+password where needed) → one button saves and signs in |
| 4 | Finish | The account's status |


Two things decide this shape:

- **A login is a JOB, not a request.** It sends a magic link/OTP and waits on mail
  arriving through a third-party forward — seconds at best, sometimes never. The route
  enqueues `auth.login` and returns a job id; the UI polls it.
- **Forwarding comes before credentials**, because a login cannot succeed until the mail
  reaches our inbox. The step order is the dependency order.

What the step ticks mean, exactly: **Connect** and **Finish** tick only when a live
session exists — the one fact the server can verify. **Forward emails** ticks on the
reader's own claim ("I've set up forwarding"), because nothing here can observe a client's
mail rules; a live session overrides it and locks it. **Before you start** ticks on
progress alone. The modal opens at step 1 with the claim cleared every time, so a tick
never carries from one account to another.

## 2. API (`app/routes/platforms.py`)

Mounted at `/clients/{client_id}/platforms`.

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `` | any user | Registry-driven status per platform: `wired`, `needs_password`, `has_credentials`, `login_email`, `connected`, `connected_at` |
| PUT | `/{platform}/credentials` | admin | Write-only; no endpoint reads a password back |
| POST | `/{platform}/login` | admin | Enqueues `auth.login`; **409** if one is already running |
| DELETE | `/{platform}` | admin | Session **and** credentials — see §4 |

`app/services/platform_service.py` holds `overview()`,
`save_credentials()` (delegates to `platform_auth.store`) and `disconnect()`.

**No migration.** It writes only to `platform_credentials` and `platform_sessions`, both
of which already exist with the columns used.

⚠️ The admin gate on these four routes is the **first** use of `require_admin` on any
endpoint. Roles have existed since 2026-06-24 (`51bc6cf`) but were enforced only in the
UI; every other write route (campaign manager, watchlist) is still open to members.

## 3. Forwarding is arranged by hand

**Decision (2026-09-17): the UI shows no forwarding address.** Whoever runs the onboarding
gives the brand the shared auth mailbox address directly; the flow only explains how to set
forwarding up for "the address your Foresight contact gave you". Setting it up is work in
the CLIENT's mailbox, arranged between two people anyway.



## 4. Disconnect deletes the credentials too

`disconnect()`  also calls
`store.delete_credentials()`, and the confirmation dialog says what that means: data stops
updating, automations stop running, and forwarding itself is NOT switched off (it lives in
the brand's mailbox).

## 5. Known gaps

- **Tenant separation rests on the login email.** The inbox matches a sign-in mail to a
  tenant by the login address in To/Cc (`inbox/imap.py::_addressed_to_us`). Now that the
  address is typed in rather than set by us via the CLI, a tenant could enter another
  tenant's login email and receive their session. Admin-gating narrows this to account
  admins. The cheap fix is rejecting a login email another tenant already uses; the
  structural one is matching on the forwarding address (`Delivered-To` = that tenant's
  `+tag`) instead of To/Cc.
- **Unverified:** that Gmail preserves the `+tag` in `Delivered-To` after a forward. The
  structural fix above depends on it.
- **The login job cannot be polled.** The UI polls
  `GET …/campaign-manager/jobs/{job_id}`, which filters `job_type.startswith("cm.")`
  (`campaign_manager_service.py:548`); `auth.login` is not `cm.*`, so every poll 404s and
  the Connect step never reports success or failure. Needs a job-status endpoint that is
  not campaign-manager specific.
- **No rate limit.** The only guard is "one login at a time per platform"; nothing stops
  repeated attempts, each mailing a magic link to an arbitrary address. On Zepto a login
  also evicts whoever is using that account's dashboard (one session per user).
- **The Gmail instructions forward the whole mailbox.** "Forward a copy of incoming mail"
  should be a filter scoped to the marketplace senders in `mail_rules.py`.

## 6. Per-member client access — not built (deliberate)

Scoping a member to specific clients (so a brand can be given a login to its own dashboard
without seeing the agency's other brands) needs a `user_clients` table, and therefore a
migration. 
What that means today:

- Every user of an account sees all of its clients — unchanged from before.
- A member is **not** read-only: only the onboarding routes are admin-gated.
- So a login must not be given to anyone outside the team until both are addressed.

## 7. Files

| Area | Files |
|---|---|
| API | `app/routes/platforms.py` (4 routes) · `app/schemas/platform.py` · `app/services/platform_service.py` |
| UI | `frontend/src/features/settings/` (SettingsPage + `components/onboarding/`) · `components/ui/Modal.jsx` |
