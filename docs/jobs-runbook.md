# Jobs & Scheduler — Runbook

How to **operate** the job system. For _why_ it's built this way, see [jobs.md](jobs.md).

> **Status: live on the VM since 2026-07-17.** Scheduled scrapes run unattended;
> logs ship to Cloud Logging. **Not yet done:** the alert policy (so failures reach a
> log, not your inbox) and the public-scraper test from the VM.

---

## The 30-second model

One daemon (`cli runner`) does two things at once:

- **Producer** — every 60s: "is any schedule due?" → inserts a `pending` row.
- **Consumer** — every 5s: "any pending job in a lane with a free slot?" → runs it as a
  subprocess (the exact `python -m cli …` you'd type) and writes the outcome + a log file.

Jobs enter the queue three ways — the scheduler, `cli jobs run`, or (later) the API —
and all run identically.

---

## CLI reference

> **`cli` below is shorthand for `python -m cli`** — there is no `cli` binary on PATH.
> Either type it in full, or make the shorthand real (recommended on the VM):
>
> ```bash
> echo "alias cli='python -m cli'" >> ~/.bashrc && source ~/.bashrc
> ```
>
> All examples use the real client **Dobra** = `a870fd8d-7373-47ec-ad69-5dd08ce35542`.
> Get yours with `cli tenant list`. Run everything from `automation-mvp/backend`
> with the venv active (`source venv/bin/activate`).

### The one idea that makes it click

**Trailing `key=value` pairs become flags on the real scrape command.** A job is just a
stored recipe for a `python -m cli scrape …` you'd otherwise type. So:

```bash
cli jobs run scrape.public_keyword -t a870fd8d-… city=bengaluru workers=5
```

…tells the runner to eventually execute:

```bash
python -m cli scrape public-run --tenant a870fd8d-… --city bengaluru --workers 5
```

`cli jobs list` shows you that exact command in the `argv` column — copy-paste it to
reproduce any run by hand.

Params are **positional and unlimited** — no `-p` per pair. Unknown keys are rejected
immediately (`unknown param 'citty'. Valid: city, keyword, cap, workers, resume`), so
typos never reach 3am. `cli jobs types` lists the valid params for every type.

**Values with spaces** — quote them; many real city slugs have spaces:

```bash
cli jobs run scrape.public_keyword -t a870fd8d-… "city=delhi ncr"
```

Only the **first `=`** splits, and the subprocess is spawned with an argv _list_ (no
shell), so spaces survive end to end.

**Multiple values are NOT supported** — `city=delhi,mumbai` would be passed as the
literal slug `delhi,mumbai` and match nothing. `--city` takes exactly one city. To
cover several cities, **omit `city` entirely** (that scrapes them all, which is the
normal production case). And note you _can't_ queue two `public_keyword` jobs for the
same client at once anyway — the overlap guard rejects the second (see #7).

**⚠️ The param name is not always the flag name.** Use the left column:

| Job type                   | `-p` param                  | → becomes                  | Values                                                  |
| -------------------------- | --------------------------- | -------------------------- | ------------------------------------------------------- |
| `scrape.blinkit_marketing` | `date_from`                 | `--from`                   | `YYYY-MM-DD` (default: 7 days ago)                      |
|                            | `date_to`                   | `--to`                     | `YYYY-MM-DD` (default: today)                           |
|                            | `limit`                     | `--limit`                  | integer — only the N most active campaigns (smoke test) |
| `scrape.blinkit_seller`    | `date_from` / `date_to`     | `--from` / `--to`          | `YYYY-MM-DD` (default: yesterday)                       |
|                            | `sales`, `po`, `soh`        | `--sales`, `--po`, `--soh` | **presence = on.** Omit for all three                   |
| `scrape.blinkit_scorecard` | `week`                      | `--week`                   | `YYYY-MM-DD`, **must be a Monday**                      |
| `scrape.public_keyword`    | `city`                      | `--city`                   | city slug, e.g. `bengaluru`                             |
|                            | `keyword`                   | `--keyword`                | a single keyword from the watchlist                     |
|                            | `cap`                       | `--cap`                    | integer — max products per search                       |
|                            | `workers`                   | `--workers`                | integer — concurrent browsers (5 is the sweet spot)     |
|                            | `resume`                    | `--resume`                 | presence = on — continue an interrupted run             |
| `scrape.public_skus`       | `city`, `workers`, `resume` | same as above              |                                                         |
|                            | `brand_cap`                 | `--brand-cap`              | integer — max products in the brand catalog             |
| `maint.log_cleanup`        | `days`                      | `--days`                   | integer (default 14)                                    |
| `monitor.heartbeat`        | `disk_pct`                  | `--disk-pct`               | integer (default 80)                                    |

Omit any param to use the scraper's own default. On/off params accept
`true/false`, `1/0`, `yes/no`, `on/off` — `sales=false` correctly leaves the flag **off**.

### Jobs — run something once, now

```bash
# What can I run? (type, lane, timeout)
cli jobs types

# Simplest possible run — all defaults
cli jobs run scrape.blinkit_marketing -t a870fd8d-7373-47ec-ad69-5dd08ce35542

# Backfill a date window
cli jobs run scrape.blinkit_marketing -t a870fd8d-… date_from=2026-07-01 date_to=2026-07-15

# Smoke test: only the 3 most active campaigns
cli jobs run scrape.blinkit_marketing -t a870fd8d-… limit=3

# Seller: only sales (omit all three flags to get sales+po+soh)
cli jobs run scrape.blinkit_seller -t a870fd8d-… sales=true

# Public keyword scrape, one city, 5 browsers
cli jobs run scrape.public_keyword -t a870fd8d-… city=bengaluru workers=5

# A city slug containing a space — quote the whole pair
cli jobs run scrape.public_keyword -t a870fd8d-… "city=delhi ncr"

# Resume an interrupted public scrape
cli jobs run scrape.public_keyword -t a870fd8d-… resume=true

# Tenant-less jobs need no -t
cli jobs run monitor.heartbeat
cli jobs run maint.log_cleanup days=7

# Jump the queue within a lane (lower number = sooner; default 100)
cli jobs run scrape.blinkit_seller -t a870fd8d-… --priority 10
```

`jobs run` **only queues** — nothing happens until a runner is up. It prints the job id.

```bash
cli jobs list              # recent 20: status, duration, peak RAM, error
cli jobs list -n 50        # more history
cli jobs logs 4795271a     # that run's log (8-char prefix is enough)
cli jobs logs 4795271a -f  # live-tail while it runs (Ctrl+C to stop)
cli jobs logs 4795271a -n 50   # just the last 50 lines
```

### Schedules — run something repeatedly

Same `job_type` / `-t` / trailing params as `jobs run`, plus a `--cron`.

```bash
# Daily 03:00 IST
cli schedules add -n "Dobra marketing daily" --type scrape.blinkit_marketing \
    -t a870fd8d-7373-47ec-ad69-5dd08ce35542 --cron "0 3 * * *"

# Daily 03:30, with catchup (seller only scrapes yesterday — a miss = permanent gap)
cli schedules add -n "Dobra seller daily" --type scrape.blinkit_seller \
    -t a870fd8d-… --cron "30 3 * * *" --catchup

# Weekly Sunday 01:00, with params (trailing key=value)
cli schedules add -n "Dobra public weekly" --type scrape.public_keyword \
    -t a870fd8d-… --cron "0 1 * * 0" workers=5

# Tenant-less
cli schedules add -n "Heartbeat hourly" --type monitor.heartbeat --cron "0 * * * *"
cli schedules add -n "Log cleanup weekly" --type maint.log_cleanup --cron "0 4 * * 1" days=14

# Create it switched off, turn it on later
cli schedules add -n "Experimental" --type scrape.public_skus -t a870fd8d-… \
    --cron "0 5 * * 0" --disabled
```

#### Managing them (CRUD)

|            | Command                                                                        |
| ---------- | ------------------------------------------------------------------------------ |
| **Create** | `cli schedules add -n "…" --type … --cron "…" [-t …] [key=value …]`            |
| **Read**   | `cli schedules list` (all, compact) · `cli schedules show <id>` (one, in full) |
| **Update** | `cli schedules update <id> [--cron …] [--name …] [key=value …]`                |
| **Delete** | `cli schedules remove <id>`                                                    |

```bash
cli schedules list          # id, name, type, cron, enabled, next run, last run
cli schedules show 3        # everything: params, tenant, catchup, priority,
                            # + the exact command it will run
```

`update` changes a schedule **in place**, keeping its id and its link to historical
jobs. Only what you pass changes:

```bash
cli schedules update 3 --cron "0 4 * * *"        # 3am → 4am (re-arms the next run)
cli schedules update 3 --name "Dobra nightly"    # rename
cli schedules update 3 --catchup                 # turn catchup on
cli schedules update 3 --no-catchup              # turn it off
cli schedules update 3 --priority 10             # run sooner within its lane
cli schedules update 3 workers=3 city=bengaluru  # REPLACES all params
cli schedules update 3 --clear-params            # remove all params
```

**Params replace, they don't merge** — run `schedules show <id>` first to see the
current set. **`job_type` can't be changed** (params are tied to it) — remove and re-add.

Validation happens before anything is written, so a bad cron or an unknown param
leaves the schedule **untouched**:

```bash
$ cli schedules update 3 --cron "not a cron"
Wrong number of fields; got 3, expected 5
```

**Turning schedules on and off** (keeps the row, unlike `remove`):

```bash
cli schedules enable 3     # switch on — re-arms next_run_at from now
cli schedules disable 3    # switch off — clears next_run_at; it cannot fire
cli schedules remove 3     # delete. Historical jobs survive; their schedule_id → NULL
```

Editing takes effect within **one producer tick (≤60s)** — no restart needed. The
runner re-reads `job_schedules` every tick.

### Cron — the `--cron` value

Five fields, **always Asia/Kolkata**:

```
┌── minute (0-59)
│ ┌── hour (0-23)
│ │ ┌── day of month (1-31)
│ │ │ ┌── month (1-12)
│ │ │ │ ┌── day of week (0-6, 0 = Sunday)
│ │ │ │ │
0 3 * * *      ← `*` means "every"
```

| Expression       | Meaning                        |
| ---------------- | ------------------------------ |
| `"0 3 * * *"`    | every day at 03:00             |
| `"30 3 * * *"`   | every day at 03:30             |
| `"0 1 * * 0"`    | every **Sunday** at 01:00      |
| `"0 4 * * 1"`    | every **Monday** at 04:00      |
| `"0 * * * *"`    | every hour, on the hour        |
| `"*/15 * * * *"` | every 15 minutes               |
| `"0 3 1 * *"`    | 03:00 on the 1st of each month |

Bad expressions are rejected at `schedules add`, not silently at 3am.

### Runner / maintenance / monitoring

```bash
cli runner start                      # the daemon: producer + consumer, foreground
cli maint log-cleanup --dry-run       # what WOULD be pruned (safe to run anytime)
cli maint log-cleanup --days 7        # actually prune logs older than 7 days
cli monitor heartbeat                 # deadman + disk check; exits non-zero if unhealthy
cli monitor heartbeat --disk-pct 90   # only complain about disk at 90%+
```

### Lanes (why things do/don't wait)

| Lane          | Job types                                      | Character                  |
| ------------- | ---------------------------------------------- | -------------------------- |
| `batch`       | `public_keyword`, `public_skus`, `log_cleanup` | hours; nobody waiting      |
| `dashboard`   | `marketing`, `seller`, `scorecard`             | minutes; scheduled         |
| `interactive` | `heartbeat`                                    | must fire promptly         |
| `live`        | (bid optimizer, later)                         | latency **is** the product |

Lanes run **in parallel**; each is sequential inside itself. So a 5-hour public scrape
delays the _next public scrape_, but never the dashboard scrapes or the heartbeat.

---

## Running it — local

Local is for **development and testing**. You are the supervisor; no systemd needed
because you have a terminal.

```bash
cd automation-mvp/backend

# Terminal 1 — the daemon
python -m cli runner start          # Ctrl+C to stop

# Terminal 2 — drive it
python -m cli jobs types
python -m cli jobs run scrape.blinkit_marketing -t <tenant-uuid>
python -m cli jobs list
python -m cli jobs logs <id> -f
```

**⚠️ Read the "two runners" warning below before starting a runner locally.**

## Running it — VM (production)

systemd replaces you as the babysitter; the Ops Agent replaces your terminal.
**Do it in this order.** Every command is explained.

### Step 0 — get the code onto the box

```bash
# SSH in from the GCP console (or gcloud), then:
cd ~/automation-mvp
git pull                       # the VM tracks `main` — merge your branch first!
```

_Why:_ the VM only ever runs `main`. Nothing on a feature branch exists on the box.

### Step 1 — install the new dependency

```bash
cd ~/automation-mvp/backend
source venv/bin/activate        # activates the virtualenv (you must do this by hand)
pip install -r requirements.txt # psutil is new — the runner needs it
```

_Why:_ `psutil` reads a process tree's memory (`peak_rss_mb`) and checks whether a PID is
alive (the reaper). Without it the runner still works but records 0 MB and can't reap.

**Do NOT run Alembic here.** The Supabase DB is shared and you already migrated it from
your laptop. The VM needs only the code + `.env`.

### Step 2 — sanity-check before daemonising

```bash
python -m cli jobs types        # proves imports + .env + DB all work
python -m cli schedules list    # should connect and print (probably empty)
```

_Why:_ if something's wrong (bad `.env`, missing dep), find out **now** with a terminal in
front of you — not later inside systemd where the error is invisible.

### Step 3 — install the runner as a service

```bash
sudo cp deploy/foresight-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now foresight-runner
```

- `cp … /etc/systemd/system/` — puts the unit file where systemd looks for services.
- `daemon-reload` — tells systemd to re-read unit files. **Required after any edit**, or
  your change is silently ignored.
- `enable --now` — two things at once: **`enable`** = start automatically on every boot;
  **`--now`** = also start it right now. (`enable` alone wouldn't start it today;
  `start` alone wouldn't survive a reboot.)

```bash
systemctl status foresight-runner   # expect: active (running)
journalctl -u foresight-runner -n 50  # its first log lines
```

_Expect to see:_ `runner … starting · lanes={...}` and `scheduler producer started`.

### Step 4 — ship logs to Cloud Logging

```bash
sudo nano /etc/google-cloud-ops-agent/config.yaml   # merge in deploy/ops-agent-logging.yaml
sudo systemctl restart google-cloud-ops-agent
```

- The Ops Agent is **already installed** (it reports CPU/RAM/disk). This adds _log_
  shipping: it tails the runner's log files and sends each line to Cloud Logging.
- `restart` — the agent only reads its config at start.
- **Merge, don't overwrite** — the file already has a `metrics:` section. Add/extend the
  `logging:` block only.

Verify in the browser: **GCP → Logging → Logs Explorer**, filter
`log_id("foresight_runner")`. If lines appear, you never need SSH to read logs again.

### Step 5 — define what runs

Once. It persists in the DB.

```bash
cd ~/automation-mvp/backend && source venv/bin/activate

python -m cli schedules add -n "Dobra marketing daily" --type scrape.blinkit_marketing \
    -t a870fd8d-7373-47ec-ad69-5dd08ce35542 --cron "0 3 * * *"
python -m cli schedules add -n "Dobra seller daily" --type scrape.blinkit_seller \
    -t a870fd8d-… --cron "30 3 * * *" --catchup
python -m cli schedules add -n "Dobra public weekly" --type scrape.public_keyword \
    -t a870fd8d-… --cron "0 1 * * 0"
python -m cli schedules add -n "Heartbeat hourly" --type monitor.heartbeat --cron "0 * * * *"
python -m cli schedules add -n "Log cleanup weekly" --type maint.log_cleanup --cron "0 4 * * 1"

python -m cli schedules list   # confirm the "next run" times look right
```

### Step 6 — prove it works without waiting until 3am

```bash
python -m cli jobs run scrape.blinkit_marketing -t a870fd8d-… -p limit=2
python -m cli jobs list          # pending → running → success
python -m cli jobs logs <id> -f  # watch it
```

_Why:_ queue one job by hand and watch the runner pick it up. If this works, the
scheduled path works — it's the same execution path, just triggered differently.

### Day-to-day

You rarely SSH in. When you do:

| Command                                   | Question                             |
| ----------------------------------------- | ------------------------------------ |
| `systemctl status foresight-runner`       | Is the daemon alive?                 |
| `journalctl -u foresight-runner -f`       | What is the service doing right now? |
| `sudo systemctl restart foresight-runner` | Pick up new code after a `git pull`  |
| `python -m cli schedules list`            | What's scheduled? Next/last run?     |
| `python -m cli jobs list`                 | What ran recently? Peak RAM? Errors? |

**After deploying new code: `git pull` then `sudo systemctl restart foresight-runner`** —
the running process holds the old code in memory until restarted.

---

## Where to view logs

Four surfaces, each answering a different question:

| Surface                                                   | Question it answers                                            | Where                                                                    |
| --------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Cloud Logging** (GCP console → Logging → Logs Explorer) | _Everything, from a browser, no SSH_                           | The normal way on the VM                                                 |
| Per-run log file                                          | _What did that scrape do?_                                     | `logs/jobs/<date>/<job_type>__<job_id>.log` — or `cli jobs logs <id> -f` |
| `logs/runner.log`                                         | _What did the runner decide?_ (claimed X, spawned pid, reaped) | JSON — shipped to Cloud Logging as filterable fields                     |
| `journalctl -u foresight-runner`                          | _Is the service healthy?_ (started/crashed/restarted)          | systemd's own record; survives even if file logging breaks               |

Useful Cloud Logging filters:

```
log_id("foresight_runner") AND severity>=ERROR       ← failures + HEARTBEAT alerts
jsonPayload.record.message =~ "auth_expired"          ← session died
log_id("foresight_jobs")                              ← raw scraper output
```

**Recommended alerts** (GCP → Monitoring → Alerting): log-based alert on
`log_id("foresight_runner") AND severity>=ERROR` → email. That one alert catches the
deadman ("the 3am scrape didn't run"), disk-full, and any runner error.

---

## ⚠️ Things to keep in mind

### 1. Two runners share ONE database — the big one

Local and the VM point at the **same Supabase DB**. The consumer claims _any_ pending
job; it does not care which host queued it. So if you run `cli runner start` on your
laptop while the VM runner is live, **your laptop will steal jobs from the queue and run
scrapes from your home IP.**

- Don't leave a local runner running once the VM is live.
- The atomic claim (`FOR UPDATE SKIP LOCKED`) still guarantees no job runs _twice_ — the
  risk is _which machine_ runs it, not double-execution.
- The reaper is host-scoped (`locked_by` = `hostname:pid`), so hosts never reap each
  other's jobs. That part is safe.

### 2. A crashed job is failed, not resumed

The runner's own state always recovers (reaper on startup). But a scrape killed mid-run
is marked `failed` — it is **not** auto-re-queued. Public scrapes support `--resume`
(skips already-scraped stores), so re-queue with `-p resume=true`. Auto-retry is not
built.

### 3. Session expiry is the likeliest unattended failure

Auto-login is parked. When a Blinkit session dies, scheduled scrapes fail with
`error='auth_expired'` (loud, alertable). Fix by SSHing in once:
`python -m cli auth blinkit --tenant <id> --headless`. Watch the `IndexedDB: N Firebase
items` line — **N=0 means the session will die in an hour; re-login headful.**

### 4. Cron is IST, always

`--cron` is a 5-field crontab interpreted in **Asia/Kolkata**. `"0 3 * * *"` = 03:00 IST
daily. The VM's clock is set to IST by `vm-01-system.sh`.

### 5. `catchup` matters more than it looks

If the VM was off at fire time, a fire >5 min late counts as **missed**:

- `catchup=false` (default) → skip it, wait for the next.
- `catchup=true` → run the missed occurrence **once** on recovery.

**Marketing** re-scrapes the last 7 days each run, so a miss heals itself — default is
fine. **Seller** only scrapes _yesterday_, so a miss is a **permanent data gap** — use
`--catchup`.

### 6. Log growth is only handled if you SCHEDULE the cleanup

Two different mechanisms, and only one is automatic:

| Log                                | Pruned how                                | Automatic?                 |
| ---------------------------------- | ----------------------------------------- | -------------------------- |
| `app.log`                          | loguru rotation 10 MB / retention 30 days | **yes**                    |
| `runner.log`                       | loguru rotation 20 MB / retention 14 days | **yes**                    |
| `logs/jobs/<date>/*.log` (per-run) | the `maint.log_cleanup` job               | **NO — only if scheduled** |

The per-run logs are the ones that actually accumulate (one file per job, forever). So
**add the schedule**, or they grow without bound:

```bash
cli schedules add -n "Log cleanup weekly" --type maint.log_cleanup --cron "0 4 * * 1" days=14
```

Cloud Logging keeps its own copy for 30 days by default (GCP-side setting) — pruning
local files does not delete what's already shipped.

### 7. One active job per (job_type, tenant)

The DB rejects a second pending/running job of the same type for the same client. So if
a scrape is still running when its schedule fires again, the producer logs _"previous run
still active — skipped"_ and moves on. **No pile-up** — this is intentional.

### 8. Alembic has two heads

`alembic upgrade head` **errors**. Always target explicitly:
`alembic upgrade b8e5d1a3f9c2`. The other head (`b7c3d8e2f1a9`, search_results /
daily_budget) is a pre-existing coworker-owned divergence — don't merge it unilaterally.

### 9. Concurrency knobs multiply

`LANE_SLOTS` is **per runner process**, and `--workers` is browsers _inside one scrape_.
Two concurrent jobs at `--workers 5` = 10 Chromiums (~3–7 GB). Raise slots only with
`peak_rss_mb` evidence from `cli jobs list`, and keep `DB_POOL_SIZE` small (3–5) on the
VM — the Supabase pooler caps at 25 across API + runner + every subprocess.

---

## Troubleshooting

| Symptom                                 | Likely cause                                                                                    |
| --------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Job stuck `pending` forever             | Runner not running (`systemctl status foresight-runner`), or its lane is busy with a long job   |
| `ModuleNotFoundError` under systemd     | `ExecStart` must use the **full venv python path** — systemd never runs `activate`              |
| Log file empty until job ends           | `PYTHONUNBUFFERED=1` missing from the unit                                                      |
| Logs written to `/logs/...` or vanish   | `WorkingDirectory` unset, or `LOG_DIR` not absolute                                             |
| Everything `failed` with `auth_expired` | Session died → re-auth (see #3)                                                                 |
| Schedule never fires                    | It's `disabled`, or `SCHEDULER_ENABLED=false`, or `next_run_at` is NULL (re-`enable` to re-arm) |
| `DuplicateActiveJob` on `jobs run`      | A job of that (type, tenant) is already pending/running — check `cli jobs list`                 |
| Jobs run but from the wrong IP          | A local runner is stealing from the queue (see #1)                                              |
