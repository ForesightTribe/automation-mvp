# Scraper VM (GCP, Mumbai)

The box the scrapers run on. Scheduling, the jobs queue, and the **runner** daemon are
a separate concern — design in [jobs.md](jobs.md), operations in
[jobs-runbook.md](jobs-runbook.md). This document is the infrastructure: how the VM is
built, how to operate it, what it costs, and the traps.

---

## Why a VM at all

**Blinkit is India-geo.** Scraping it from a US/EU datacenter is a block risk, and
Render/Vercel give no control over egress region. So the scrapers — and *only* the
scrapers — live on a VM in **Mumbai**.

| Workload | Where | Why |
|---|---|---|
| Frontend | Vercel | Static SPA, no geo constraint |
| Backend API | Render | Always-on, no geo constraint, ~$7/mo beats a 24/7 VM |
| **Scrapers** | **GCP VM, Mumbai** | **Needs an Indian IP** |

Don't consolidate the backend onto the VM without cause: the VM is stoppable (and
should be stopped when idle), an API is not.

## Status

**Validated 2026-07-13.** A real Blinkit marketing scrape ran on the box:
headless Chromium launched on a machine with no display, **Cloudflare did not
block the datacenter IP**, and the DB write landed.

**Unattended since 2026-07-17.** The box now runs the **job runner** as a systemd
service: scheduled scrapes fire on their own, crash recovery is proven, and logs ship
to Cloud Logging. Operate it via [jobs-runbook.md](jobs-runbook.md); design in
[jobs.md](jobs.md). Measured on this hardware: a dashboard scrape peaks at **~920–956
MB**, the runner daemon idles at **76 MB**.

Caveat: the IP geolocates to Mumbai/IN, but its ASN is visibly **Google LLC**
(`*.bc.googleusercontent.com`). That validates the **authed** scrapers (marketing,
seller, explorer — logged in, low suspicion). The **public** scrapers fight
Cloudflare unauthenticated and **have still never run from this box** — they may be
flagged on ASN alone. Test one by hand before scheduling them; proxies remain a
public-scraper-only concern.

⚠️ **The external IP is ephemeral** — stopping the VM releases it and you get a new
one on start. Harmless (still Mumbai/Google ASN, nothing connects inbound, sessions
are cookie-based), but don't be surprised. And a **stopped VM does no work**: a
schedule whose time passes while it's off is skipped unless it has `--catchup`.

## The box

| | | Why |
|---|---|---|
| Name | `foresight-vm` | |
| Zone | `asia-south1-a` (Mumbai) | **The entire point.** Indian IP |
| Machine | `e2-standard-2` — 2 vCPU / 8 GB | Chromium is RAM-hungry; 8 GB fits ~5 concurrent |
| OS | Ubuntu **24.04 LTS** | LTS = 5yr support. A brand-new LTS risks Playwright's `--with-deps` not recognising the distro |
| Disk | 30 GB **Balanced** PD | Playwright's browsers alone are ~2 GB; the 10 GB default is too tight. Standard (HDD) PD is painfully slow |
| Snapshots | **none** | Code is in git, data is in Supabase. The box holds nothing unique — snapshots are pure cost |
| External IP | **ephemeral** | A *reserved* static IP bills ~$2-3/mo **while the VM is stopped**. Nothing depends on a stable address yet |
| Login user | `tech` | |
| Branch | **`main`** | The VM never runs `dev` |

Machine type and disk size are **changeable later** (stop → change → start; disk
grows but never shrinks). Nothing here is a one-way door.

## Provisioning

Two scripts in [`deploy/`](../deploy/), split because a **GitHub deploy key** must be
registered between them.

```bash
bash vm-01-system.sh    # timezone, swap, Python 3.11, ssh-keygen → prints a public key
# → add that key at repo → Settings → Deploy keys (write access OFF)
bash vm-02-app.sh       # clone main, venv, deps, Playwright
```

Then recreate `.env` **by hand** (it is not in git):

```bash
nano ~/automation-mvp/backend/.env
```

`ENCRYPTION_KEY` **must match local exactly** — see [Sessions](#sessions--auth) below.

**Getting the scripts onto a fresh box is a chicken-and-egg problem** (they live in
the repo, but script 1 is what enables cloning it). GCP's browser-SSH **file upload
is unreliable** — don't fight it. Paste instead:

```bash
cat > ~/vm-01-system.sh << 'ENDOFSCRIPT'
...paste script contents...
ENDOFSCRIPT
```

## Operating it

```bash
cd ~/automation-mvp/backend
source venv/bin/activate          # Linux equivalent of venv\Scripts\activate
python -m cli scrape blinkit --tenant <uuid> --limit 2 --no-save
```

- **`--no-save` writes nothing to the shared DB** — always the first thing to run on
  a new box or after a code change.
- **Closing SSH kills whatever it started.** For long interactive runs use `tmux`
  (detach, close SSH, re-attach later). For scheduled runs, that's [jobs.md](jobs.md).
- **Stop the VM when idle.** GCP bills uptime; a stopped VM costs only its disk.

## Sessions & auth

**Sessions are not files — they live encrypted in Supabase** (`load_session(db,
tenant_id, platform)`). So there is **nothing to copy to the VM**. Any box with the
same `DATABASE_URL` + `ENCRYPTION_KEY` decrypts the session captured locally and
just runs.

A wrong `ENCRYPTION_KEY` doesn't fail loudly — the box reads the row and can't
unlock it.

**Re-authenticating on the box.** `cli auth blinkit` / `blinkit-seller` take a
`--headless` flag (default off, so local behaviour is unchanged). The human's only
step in both flows is an `input()` **at the terminal** — pasting a magic link or
typing an OTP. Nobody ever touches the browser window, so `headless=False` was only
ever there so a human could watch. With `--headless` you can re-auth over SSH.

> **Open question (2026-07-13):** `blinkit-seller --headless` failed once with a
> timeout after OTP submit — but the OTP was entered 5½ minutes after it was
> requested, so an expired code is the likelier cause than bot detection. Not yet
> retested. `seller/auth.py` now screenshots failures to `logs/auth-failures/`
> (headless otherwise leaves you blind). The magic-link flow (`auth blinkit`) is a
> different mechanism and is the one most likely to work — `reconnect_blinkit()` in
> `ads_service.py` already does headless magic-link capture today.

⚠️ **A headless login can "succeed" while capturing 0 Firebase IndexedDB items — and
it still saves.** That session dies after ~1h. Always check the log line
`IndexedDB: N Firebase items`; **N = 0 means re-login headful immediately.**

Full unattended operation still needs an **inbox reader** (Gmail API / IMAP) to
extract the link/OTP. Design note: re-auth **lazily**, only when a session is
actually dead — repeated logins from a datacenter IP look like a bot.

## Cost

**GCP bills VM uptime, not CPU load.** A box idling at 3% costs the same as one at
95%. So **packing more brands onto one VM is free**, and cost-per-brand falls as you
add brands: ~$62/mo total is $62/brand at one brand and **~$6/brand at ten**.

- Stopping the VM stops compute charges (disk still bills, ~$3/mo).
- But the more you schedule, the less you can stop it. At full scale it runs 24/7 —
  and $62/mo for 10 brands is a good trade.
- Budget alert is set to **₹1000/mo**. It *alerts*, it does not cap.

Watch spend at **Billing → Reports** (costs lag by up to a day; the month-end
forecast is the number to read).

## Capacity

**The scrapers are I/O-bound and self-throttled**, not CPU-bound — the marketing
scraper paces itself at `_THROTTLE_S = 0.6` to stay under Cloudflare's rate limit,
so it spends most of its life asleep. That makes wall-clock time, not vCPU, the
thing to budget.

Rough estimate for 10 brands × 4 marketplaces, private daily: ~8h of *sequential*
work → ~2h wall-clock at 5 workers. **Fits comfortably in a day.**

- **RAM is the binding local constraint** — ~300-700 MB per headless Chromium.
- **But the real ceiling is the IP, not the box.** At full scale, one datacenter IP
  generating machine-regular traffic all day is a far louder fingerprint than a
  single test scrape. Expect to reach for **more IPs / proxies before a bigger VM**.
  The marketing scraper already has an abort guard for sustained blocks
  (`_RATE_LIMIT_ABORT_AFTER`).

Don't trust the arithmetic above — **measure**. Run `htop` in a second SSH session
during a real scrape and read the peak RSS.

## Monitoring

**GCP does not graph RAM out of the box** — the console shows CPU, disk and network
only. Since **RAM is the constraint** and an OOM-killed Chromium is the classic
silent failure, the **Ops Agent** is installed to close that gap (VM → Observability
tab). Free at this scale: agent system metrics aren't billed, and Cloud Logging has
a 50 GiB/mo free tier.

On the box:

```bash
htop            # live CPU + RAM per process — one row per Chromium
free -h         # RAM + whether swap is being touched
df -h /         # disk free — logs grow silently
```

## Gotchas

Everything below cost real time to discover.

- **GCP images ship with zero swap.** Chromium spikes get **hard-killed by the OOM
  killer** — which looks like a scraper that silently vanished mid-run. `vm-01`
  adds a 2 GB swap file as a pressure-release valve.
- **The box boots on UTC.** Every scraper's idea of "today" and every schedule would
  be off by 5h30m. `vm-01` sets `Asia/Kolkata`.
- **`playwright install-deps` needs sudo; `playwright install chromium` must NOT.**
  Run the browser download as root and Chromium lands in *root's* cache, where the
  scraper (running as `tech`) can't find it → a baffling "Executable doesn't exist"
  at scrape time.
- **Ubuntu 24.04 ships Python 3.12, but we run 3.11** (deadsnakes PPA) to match the
  local venv and Render. Keep the three environments on one interpreter.
- **systemd/cron have no terminal and never run `activate`.** Anything scheduled must
  use the **full interpreter path** (`/home/tech/automation-mvp/backend/venv/bin/python`)
  or it dies with `ModuleNotFoundError`. This is why scheduling is a **runner daemon**,
  not a crontab — see [jobs.md](jobs.md). ✅ Handled by
  `deploy/foresight-runner.service` (full path + `WorkingDirectory` + `EnvironmentFile`
  + `PYTHONUNBUFFERED=1`, without which subprocess logs stay empty until a job ends).
- **~~`logger.py` writes to a relative path~~ — FIXED.** It now uses an absolute
  `settings.LOG_DIR` (default `<backend>/logs`), created eagerly. Under systemd a
  relative `logs/app.log` would have resolved to `/logs` and failed silently.
- **Supabase pooler is set to 25 connections** (not 15 — an older note said 15; the
  comment in `database.py` was stale too). Each process gets its own pool, and
  `pool_size` is now configurable via **`DB_POOL_SIZE`** — the runner unit sets it to
  `4`. Budget: API 5 + runner 3 + subprocesses ≈ under 25. See [jobs.md](jobs.md).
- **A full disk causes bizarre, unrelated-looking failures.** ✅ Now handled:
  `app.log`/`runner.log` self-rotate (loguru), and per-run job logs are pruned by the
  **`maint.log_cleanup`** job — *but only if that schedule exists*. `df -h /` still
  worth a glance; `monitor.heartbeat` also alerts at >80%.
- **Dotfiles are hidden.** `ls` won't show `.env` — use `ls -a`.
