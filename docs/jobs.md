# Jobs, Scheduler & Observability

Everything that runs on the VM — scheduled scrapes, ad-hoc commands, the live bid
optimizer, and (later) UI-triggered runs — goes through **one queue and one runner**.

The problem this solves: the VM works, but every scrape is typed by hand over SSH,
failures are invisible (no terminal, no log surface), and nothing records what ran.

> **Status: LIVE IN PRODUCTION on the VM since 2026-07-17.** Phases 1–3 (queue +
> runner + scheduler + observability) are deployed and validated on real hardware:
> scheduled scrapes fire unattended, crash recovery works, and logs ship to Cloud
> Logging. See [jobs-runbook.md](jobs-runbook.md) to operate it.
>
> **Still open:** the alert policy isn't created yet (so the heartbeat's ERROR reaches
> a log, not your inbox); the **public** scrapers have never run from the VM (the
> Cloudflare/datacenter-ASN question); Phase 4 (API) is unbuilt; `jobs cancel` doesn't
> exist; auto-login is parked.

---

## The core idea

**Every run is a row in the `jobs` table.** A CLI command, a scheduler tick, and a
future UI button all do the same thing: enqueue a job. One **runner** daemon on the VM
drains the queue.

```
cli jobs run …   ─┐
scheduler tick   ─┼─→  jobs (Postgres queue)  ─→  runner (systemd)  ─→  subprocess: python -m cli …
API POST /jobs   ─┘          ↑                        │
   (future UI)          job_schedules                 ├─→ per-run log file
                                                      └─→ job row: status, exit code, peak RSS
```

Three triggers, **one execution path**. The UI phase is then almost free — the tables
and the runner already exist; the API just inserts rows.

In one paragraph: *systemd keeps a **runner** alive on the VM forever. The runner
watches a table in Postgres for rows that say "please scrape this". When it finds one,
it **spawns a subprocess** — literally the same `python -m cli scrape …` command you
would type by hand — and pipes that command's output into a log file. When the
subprocess exits, the runner records whether it worked. Everything else in this
document is making that sentence survive crashes.*

---

## Lanes — why the queue is not a single line

**A 5-hour public scrape and a 30-minute live bidding loop cannot share one queue.**

The bid optimizer is a *live control loop*: it checks keyword positions and adjusts CPM
every 15–30 minutes, and **latency is the product**. Put it in a single sequential queue
behind a batch scrape and it simply will not run for five hours — silently, with the job
row sitting at `pending`, looking perfectly healthy.

So the queue is split into **lanes**. Each lane is sequential *within itself*; lanes run
**in parallel**.

| Lane | Slots | Contains | Character |
|---|---|---|---|
| `batch` | 1 | public keyword + SKU scrapes | Hours long. Nobody is waiting |
| `dashboard` | 1 | marketing, seller, scorecard | Minutes. Scheduled |
| `live` | 1 | bid optimizer (coworker's, later) | **Never blocked.** Latency *is* the feature |
| `interactive` | 1 | Explorer | A human is waiting on it |

A job's lane is a property of its **type**, not something the caller picks. Concurrency
is configured **per lane** (`LANE_SLOTS`), not globally — so "two jobs at once" is really
"one batch + one live", which is what you actually want. Two *batch* jobs at once is
almost never what you want: they'd compete for RAM, and (worse) double the request rate
from a single IP.

> This supersedes an earlier "one global `MAX_CONCURRENT`, strictly sequential" design.
> That was right for scrapers alone and **wrong** the moment a live loop entered the mix.

---

## Glossary — read this first

Several of these words already mean **more than one thing** in this codebase. That
ambiguity is the single biggest source of confusion here, so it is worth being blunt.

### The collisions

**"session" means three unrelated things.**

| Which | What it actually is |
|---|---|
| **Platform session** | The Blinkit *login* — cookies + Firebase IndexedDB, encrypted in `platform_sessions`. "Session expired" = the scraper is logged out |
| **DB session** | `async with AsyncSessionLocal() as session` — SQLAlchemy's term for a conversation with Postgres |
| **Session pooler** | Supabase's connection-pooling *mode*, i.e. the `DATABASE_URL`. Unrelated to either above |

**"worker" was ambiguous, so we renamed ours.**

| Which | What it actually is |
|---|---|
| **`--workers 5`** | Concurrent **browser contexts inside one scrape**. An internal parallelism knob |
| **runner** | The **daemon** that drains the job queue and launches scrapes. One per box, not a browser |

> "One worker running a scrape with 5 workers" is an unreadable sentence — hence **runner**.

**"job" means two things.** `scrape_jobs` (existing) = progress notes taken *while doing*
a scrape, driving `--resume`. `jobs` (new) = the **work order** — what to run, when, and
how it went. Linked by `ref_job_id`.

**"schedule" means two things.** `budget_schedules` is a *domain* concept (what ad budget
to apply at what time of day — the campaign manager, coworker-owned). `job_schedules` is
*infrastructure* (run this job at this cron time). Unrelated; must not be merged.

### The OS vocabulary

**Process** — one running program with its own private memory. Two processes cannot see
each other's variables. That isolation is the entire reason this design uses them.

**Subprocess** — a process started *by* another (Node's `child_process.spawn()`). **Why
it matters:** when Chromium exhausts RAM, Linux's OOM killer shoots a process. If the
scrape is a subprocess, the *child* dies and the runner survives to record the failure.
As an in-process call, the whole daemon would die and nothing would be recorded.

**Daemon** — runs forever in the background with no terminal attached. Today a scrape
launched over SSH is a *child of the SSH session*, so closing the laptop kills it.

**systemd** — Linux's service supervisor (PID 1). **The useful model: systemd is what
Render does for a web service, except configured by hand** — keep it alive, restart on
crash, back after reboot, capture logs.

**cron** — runs a command *at a time*, then sleeps. systemd keeps something *alive*. We
need the latter: the runner must be awake at all times to pick up manual and UI jobs.

**Queue** — no Redis, no RabbitMQ. **The queue is rows in a Postgres table.** A row with
`status='pending'` *is* "in the queue".

**Connection pool** — a reusable set of open DB connections held by an engine. **Each
process has its own pool** — which is why subprocesses are cheap in safety but expensive
in connections. See [Capacity](#capacity--will-the-vm-cope).

---

## Locked decisions

| Fork | Decision | Why |
|---|---|---|
| Scheduling | **Runner daemon + DB queue**, not cron | Cron can't serve the UI trigger, keeps no run record, has no overlap control, and hides schedules in a crontab only reachable by SSH — which is the actual problem |
| Dispatch | **Subprocess** (`venv/bin/python -m cli …`) | Zero refactor of working scrapers; a Chromium OOM kills the child, not the daemon; child stdout *is* the log; memory fully reclaimed on exit; the exact argv is recorded and replayable |
| Queue shape | **Lanes**, not one global concurrency number | A live control loop must never queue behind a 5-hour batch job |
| Schedules live in | **`job_schedules` table**, not a crontab | Editable from the future UI without SSH; that is the whole point |
| Overlap guard | **Partial unique index** in the DB, not runner-side state | Survives runner restarts; a 2h scrape can't be started twice |
| Log viewing | **GCP Cloud Logging** now (Ops Agent already installed), **API + UI** later | No SSH, free under the 50 GiB/mo tier |
| Campaign manager | **Not touched** — coworker owns it | Slots in later as `live`-lane job types. See [Handover](#handover-campaign-manager) |
| Auto-login | **Out of scope** — revisit after the scheduler ships | Until then, an expired platform session is a *loud* failure, not an auto-recovery |
| Scrape volume | **Not decided** — build against current volume, revisit at onboarding | See [Capacity](#capacity--will-the-vm-cope) |
| Timezone | **Asia/Kolkata** everywhere | VM tz set by `vm-01-system.sh`; `now_ist` already exists |

---

## Schema

Two new tables, sitting *above* the existing `scrape_jobs` / `explorer_runs` — those keep
recording what a scrape did *internally* (progress, `--resume` state), untouched. `jobs`
records **what to run, when, and how it went**, and points at the detail row via
`ref_job_id`.

### `jobs` — the queue + run record

| Column | Notes |
|---|---|
| `id` | uuid, PK |
| `job_type` | `scrape.public_keyword`, `scrape.blinkit_marketing`, … |
| `lane` | `batch` / `dashboard` / `live` / `interactive` — derived from `job_type` |
| `tenant_id` | nullable — explorer/maintenance jobs have no client |
| `params` | JSON — the job's inputs; rendered into argv |
| `status` | existing `JobStatus` enum: `pending` / `running` / `success` / `failed` |
| `priority` | int, lower first, **within a lane** (default 100) |
| `scheduled_for` | when it becomes eligible (default now) |
| `schedule_id` | FK `job_schedules.id`, null for manual/API runs |
| `attempts` / `max_attempts` | retry budget (default 1 — scrapers already retry internally) |
| `locked_at` / `locked_by` | runner `hostname:pid`; drives the stale-lock reaper |
| `argv` | the exact command executed — copy-paste to reproduce |
| `exit_code` | subprocess exit status |
| `log_path` | path to this run's log file |
| `peak_rss_mb` | child **and its descendants** — how you size lane slots |
| `ref_job_id` | → `scrape_jobs.id` / `explorer_runs.id` |
| `error` | short reason (`auth_expired`, `oom`, `timeout`, `runner_died`, exception head) |
| `started_at` / `completed_at` / `created_at` | |

**Overlap guard** — the DB refuses to queue a second run of the same job for the same
client while one is pending or running:

```sql
CREATE UNIQUE INDEX uq_jobs_active ON jobs (job_type, tenant_id)
  WHERE status IN ('pending', 'running');
```

(Postgres treats NULLs as distinct, so tenant-less Explorer runs are *not* deduped — which
is what we want.)

**Claim** is atomic and **per lane**, so a lane's slot count is enforced by the database:

```sql
UPDATE jobs SET status='running', locked_at=now(), locked_by=:runner,
                started_at=now(), attempts=attempts+1
WHERE id = (SELECT id FROM jobs
            WHERE status='pending' AND lane=:lane AND scheduled_for <= now()
            ORDER BY priority, scheduled_for
            FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *;
```

### `job_schedules` — recurring work

| Column | Notes |
|---|---|
| `id` | int, PK |
| `name` | human label — "Dobra marketing daily" |
| `job_type` / `tenant_id` / `params` | what to enqueue |
| `cron` | `"0 3 * * *"`, interpreted in Asia/Kolkata |
| `enabled` | bool |
| `catchup` | if the VM was down at the fire time, run once on recovery? See [Missed runs](#missed-runs-and-catchup) |
| `last_enqueued_at` / `next_run_at` | drives the UI ("last run / next run") |

---

## Job types

`params` maps 1:1 onto existing CLI flags — no new scraper code.

| `job_type` | Lane | Command it runs |
|---|---|---|
| `scrape.blinkit_marketing` | `dashboard` | `cli scrape blinkit --tenant … [--from --to]` |
| `scrape.blinkit_seller` | `dashboard` | `cli scrape blinkit-seller --tenant … [--sales --po --soh]` |
| `scrape.blinkit_scorecard` | `dashboard` | `cli scrape blinkit-scorecard --tenant … [--week]` |
| `scrape.public_keyword` | `batch` | `cli scrape public-run --tenant … [--city --cap --workers]` |
| `scrape.public_skus` | `batch` | `cli scrape public-skus --tenant … [--city --brand-cap --workers]` |
| `explore` | `interactive` | `cli explore …` (ExplorerSpec → flags) |
| `maint.log_cleanup` | `batch` | prune `logs/jobs/**` older than N days |
| `monitor.heartbeat` | `interactive` | deadman check — see [Monitoring](#monitoring) |
| *reserved* `campaign.budget_scheduler` | `live` | coworker's, later |
| *reserved* `campaign.bid_optimizer` | `live` | coworker's, later |

---

## Worked example — a week in the life

Client **Dobra**. Dashboards daily, public weekly.

| name | job_type | cron |
|---|---|---|
| Dobra marketing daily | `scrape.blinkit_marketing` | `0 3 * * *` |
| Dobra seller daily | `scrape.blinkit_seller` | `30 3 * * *` |
| Dobra public weekly | `scrape.public_keyword` | `0 1 * * 0` |
| Dobra SKUs weekly | `scrape.public_skus` | `0 5 * * 0` |

### The happy path (a Tuesday)

1. **03:00:00** — the scheduler *inside the runner* fires. It **does not scrape**. It does
   one thing: `INSERT INTO jobs (job_type='scrape.blinkit_marketing', lane='dashboard',
   tenant_id=dobra, status='pending', …)`.
2. **03:00:03** — the runner's consumer loop (polling every ~5s) sees a pending row **in
   the `dashboard` lane**, and that lane has a free slot. It **claims** it: `status='running'`,
   `locked_by='foresight-vm:2041'`.
3. It renders `params` into argv and records it on the row:
   `/home/tech/automation-mvp/backend/venv/bin/python -m cli scrape blinkit --tenant <uuid>`
4. It opens `logs/jobs/2026-07-14/scrape.blinkit_marketing__<job-id>.log` and **spawns the
   subprocess**, stdout **and** stderr redirected into that file. The rich console output
   you normally watch on screen *is* the log.
5. While it runs, the runner samples the child's RSS **plus its descendants** — Chromium
   spawns children of its own, so a naive read misses most of the memory.
6. **03:06** — the child exits `0`. The runner writes `status='success'`, `exit_code=0`,
   `completed_at`, `peak_rss_mb=540`, `log_path`.

The process tree during step 5 — note the runner is tiny and the memory is all in browsers:

```
systemd
└── python -m cli runner            ← the daemon.  ~80 MB.  never dies
    └── python -m cli scrape …      ← the subprocess.  ~200 MB
        ├── chromium (worker 1)     ← ~400 MB
        ├── chromium (worker 2)
        └── … ×5   (--workers 5)
```

### Sunday, when jobs collide

The public keyword scrape starts at 01:00 and runs ~2 hours (much longer at scale). At
**03:00** the daily marketing schedule fires while it is still going.

They are in **different lanes**, so marketing starts immediately — the batch scrape does
not delay it. Had they been in the same lane, marketing would have waited its turn and
started at 03:10 instead: **delayed, never lost.** That is what a queue buys you, and it
is what cron cannot do — cron would have launched a second Chromium fleet on top of the
first and OOM-killed the box.

The `live` lane, meanwhile, is untouched by any of this. That is the whole point of lanes.

---

## Failure scenarios

### The VM is rebooted (planned)

systemd sends `SIGTERM`. The runner stops claiming new work and gives the running child a
grace period. A 2-hour scrape won't finish in it, so it gets killed — and its row is left
stranded at `status='running'`.

On boot, systemd restarts the runner (`Restart=always` + `systemctl enable`). The runner's
**first act is the reaper**: it finds rows marked `running` whose `locked_by` names this
host but whose PID no longer exists, and marks them `failed`, `error='runner_died'`. The
overlap index is released and the next scheduled run proceeds.

### The VM crashes hard (power loss, kernel panic)

No `SIGTERM`, no cleanup. Row stranded at `running`; the reaper handles it identically on
next boot. **This is why the reaper is not optional.** Without it that stranded row would
satisfy the overlap index *forever*, and every future run of that job type would be
rejected as a duplicate — silently, with no error anywhere. The system would work perfectly
until the first crash and then stop working permanently.

### Out of memory during a scrape

Chromium balloons; Linux's OOM killer picks the fattest process — the **scrape subprocess**,
not the runner (~80 MB, never a target).

The child dies. The runner is **still alive**, sees the exit status, and writes
`status='failed'`, `error='oom'`, plus the `peak_rss_mb` it measured. Then it moves on.

That is the entire justification for subprocess dispatch. As an in-process call, the OOM
killer would have taken the **runner** with it — daemon gone, row stuck at `running`
forever, and you'd find out days later.

### A Chromium hangs (no crash, just stuck)

Every job type has a maximum runtime. Exceed it and the runner kills the subprocess and
marks it `failed`, `error='timeout'`, rather than letting a wedged browser hold a lane.

### The Blinkit session expired

The subprocess fails to authenticate and exits non-zero. The runner marks the job `failed`
with `error='auth_expired'` — a *distinct* reason, so it can be alerted on specifically —
and you re-auth with `cli auth blinkit --headless`.

Auto-login is deliberately **out of scope for now**, so this is the failure mode most likely
to bite an unattended run. It must fail *loudly*.

### Something is enqueued twice

The overlap index rejects the insert — whether it came from the scheduler firing while a run
is still going, from `cli jobs run`, or from a double-clicked UI button. One active job per
`(job_type, tenant)`, enforced by the database rather than by hopeful application logic.

---

## Missed runs and catchup

If the VM is **off** at 03:00, nothing fires — no process was alive to insert the row. What
happens next is per-schedule, via `catchup`. **The right answer differs by scraper:**

- **Marketing** re-scrapes **the last 7 days** on every run (to pick up late metric
  revisions). A missed day therefore **heals itself** next run — `catchup=false` is fine.
- **Seller** defaults to **yesterday only**. A missed day is a **permanent data gap**. Set
  `catchup=true`, or give the schedule a wider `--from`/`--to` window.

Invisible until it has already cost you a week of data, which is why it is written down.

---

## The runner

`cli runner` — one process, supervised by systemd, two halves:

- **Producer** — APScheduler (already a dependency), `AsyncIOScheduler(timezone="Asia/Kolkata")`.
  Re-syncs from `job_schedules` every 60s and **enqueues** due jobs. It never executes anything.
- **Consumer** — polls every ~5s, and **for each lane with a free slot** claims a job, spawns
  the subprocess, streams stdout+stderr to the run's log file, samples RSS, and writes the
  outcome back.

Three things it must get right, each otherwise a silent-failure source: the **stale-lock
reaper** (above), **graceful shutdown** on SIGTERM (stop claiming, let the child finish, then
kill and release the lock), and a **timeout ceiling** per job type.

### systemd unit

`/etc/systemd/system/foresight-runner.service`:

```ini
[Unit]
Description=Foresight job runner
After=network.target

[Service]
User=tech
WorkingDirectory=/home/tech/automation-mvp/backend
EnvironmentFile=/home/tech/automation-mvp/backend/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/tech/automation-mvp/backend/venv/bin/python -m cli runner
Restart=always
RestartSec=10
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

Every line is load-bearing. `ExecStart` uses the **full venv interpreter path** — systemd,
like cron, never runs `activate`, so a bare `python` gives `ModuleNotFoundError`.
`WorkingDirectory` is the `cd` systemd would not otherwise do. `EnvironmentFile` loads
`.env`, because systemd starts with a nearly empty environment. `PYTHONUNBUFFERED=1` is why
log lines appear *as they happen* rather than in one dump at the end — Python buffers stdout
when it isn't a terminal. `Restart=always` covers both crashes and reboots.

```bash
sudo systemctl enable foresight-runner    # start at boot
sudo systemctl start foresight-runner     # start now
sudo systemctl status foresight-runner    # alive? recent output?
sudo journalctl -u foresight-runner -f    # tail its logs live
```

---

## Logging

Today `logger.py` writes to a **relative** `logs/app.log`. A relative path resolves against
the process's **current working directory** — which is `backend/` only because you happen to
`cd` there. systemd does not, so the runner would try to write `/logs/app.log` and fail.
**Fix this first**, with an absolute `LOG_DIR`.

Four surfaces, each answering a different question:

| Surface | Answers |
|---|---|
| `logs/jobs/<date>/<job_type>__<job_id>.log` | *What did the scrape do?* — the console output you're used to, one file per run |
| `logs/runner.log` | *What did the runner decide?* — claimed X, spawned PID Y, reaped a stale lock |
| `journalctl -u foresight-runner` | *Is the service healthy?* — systemd's own view: started, crashed, restarted |
| `logs/app.log` | The API's log, unchanged |

`rich` detects it is not a TTY and drops colours (good) — but check that spinners/progress
bars degrade to something readable rather than spamming repeated lines.

**Reading them without a terminal:** point the already-installed **Ops Agent** at
`logs/**/*.log` (`/etc/google-cloud-ops-agent/config.yaml` → files receiver + pipeline). It
tails the files and ships each line to **Cloud Logging**, where you search, filter and alert
from a browser — free under the 50 GiB/mo tier. Emit `runner.log` as **JSON** (loguru does
this natively) so `job_id` / `job_type` / `tenant` become filterable fields; keep per-job logs
as **plain text**, since those are meant to be read.

Disk discipline is not optional — a full disk causes bizarre silent failures, and unrotated
logs grow forever.

---

## Monitoring

The Ops Agent already puts CPU, RAM and disk in the GCP console. What it cannot tell you is
*which job* ate the RAM — hence `peak_rss_mb` per job row. That is what lets you size lane
slots with evidence instead of guessing.

But the alert that matters is not CPU. It is **"the 3am scrape silently didn't run."**

- **Deadman / heartbeat** — a scheduled `monitor.heartbeat` job asserts each expected job type
  has succeeded within its window (26h for a daily, 8d for a weekly). If not → ERROR log →
  Cloud Logging alert → email. This catches the failure mode no resource graph ever will.
- **Disk > 80%** and **VM down** alert policies in GCP.

---

## Capacity — will the VM cope?

Grounded in the real numbers (2026-07-14): **one tenant, 2,216 covered locations, 6
keywords** → **13,296 searches** per public run, ≈5 h.

Projected to **5 brands × 3 marketplaces**:

| Workload | Per cycle |
|---|---|
| Public data | 5 × 3 × 5 h = **~75 hours** |
| Dashboards | ~15 brand-MP pairs × ~2 × 15 min ≈ **7.5 h/day** |
| Explorer | bursty, but *someone is waiting* |
| Bid optimizer | every 15–30 min, forever — **latency-critical** |

**Three walls, in order of severity.**

**1. The queue shape** — solved by [lanes](#lanes--why-the-queue-is-not-a-single-line). This
was the real finding: a single sequential queue would starve the bid optimizer for hours.

**2. The IP — the actual ceiling.** ~200k public search requests per cycle, plus the bid
optimizer's position checks (also public searches), all from **one Google-datacenter IP**
against Cloudflare. This will get blocked. **Proxies become load-bearing, not optional** — see
below. At ~100 KB/response that is ~20 GB/cycle, i.e. **$150–400/mo** of residential proxy at
medium scale. (An earlier "$2/tenant/mo" estimate in conversation was wrong — it assumed ~1,000
requests, not 200,000.)

**3. The box — the least of the problems.** All four lanes hot ≈ 6.5–7.5 GB against 8 GB, and
2 vCPUs driving 7+ Chromiums is real contention. **e2-standard-4** (4 vCPU / 16 GB) ≈ $100–120/mo
vs today's $50–60. Cheapest of the three; do not optimise here first.

### Measured RAM (VM, 2026-07-17) — supersedes the estimates above

| Workload | Peak RSS | Duration |
|---|---|---|
| `runner` daemon (idle) | **76 MB** | — |
| `monitor.heartbeat` | **93 MB** | 5 s |
| `scrape.blinkit_marketing` (full, 45 campaigns) | **~920 MB** (921/916/917 across runs) | ~30 s–5 min |
| `scrape.blinkit_seller` | **~956 MB** | ~1 min |
| `scrape.public_*` | **not yet measured** | ~5 h expected |

**One dashboard scrape costs ~1 GB** — about 2× the old "300–700 MB per Chromium"
guess. This **validates `LANE_SLOTS = 1` per lane** on the 8 GB box: dashboard (1 GB)
+ batch (est. 2–4 GB) + OS/runner (~1 GB) is already 4–6 GB. Raising any lane to 2
risks OOM. The 76 MB runner vs ~920 MB subprocess also confirms why subprocess
dispatch works: the OOM killer targets the fat scrape, never the daemon.

Read `peak_rss_mb` from `cli jobs list` before changing `LANE_SLOTS`.

**Connections are *not* a wall.** The Supabase pooler is set to **25**. Budget: API 5 + runner 3
+ two subprocesses ×6 = **20**, leaving 5 for `psql`/migrations/Studio. Two concurrent lanes fit
today. Note [database.py](../backend/app/core/database.py)'s comment still says the cap is 15 —
**stale, it is 25.** Connection limits scale with Supabase *compute size*, not plan tier, so
upgrading to Pro would not buy concurrency (it buys backups and no project pausing — real, but
different, reasons).

### The highest-leverage lever: do less work

**Locations are the multiplier, not keywords** — 2,216 × 6. Tiering (top N locations weekly,
full sweep monthly) would cut the 75 h *and* the proxy bill by ~5–6×. It is a config change and
costs nothing. **Deferred by decision (2026-07-14)** — build against current volume, revisit when
brands 2–5 are onboarded.

### Open bug: co-located rows are scraped twice

`_locations()` ([orchestrator.py:84](../backend/scraper/public/orchestrator.py#L84)) returns
**2,216** rows, but there are only **1,924 distinct `(lat, lon)`**. The search API selects the
dark store *from the coordinate*, so two catalog rows sharing a lat/lon send an identical request
and get an identical response — **~13% of every public run is duplicate work** (~10 h/cycle at
medium scale). The `--resume` path already keys on `(keyword, lat, lon)` and would skip them; a
fresh run does not. Fix is a `DISTINCT ON (lat, lon)`. **Not yet fixed.**

### The end state

Two boxes: one for `batch` (public, proxied, slow, unattended) and one for `live` (bid optimizer,
its own IP, latency-critical). Different risk profiles want different machines — and because
lanes already exist, splitting them is a config change rather than a rewrite.

---

## Proxies (future)

Not needed yet, and **the first move is not to buy any** — it is to run one public scrape from the
VM and see whether it is even blocked. The *authed* scrapers were validated on the VM's IP
(2026-07-13); the *public* ones, which fight Cloudflare, never have been. That experiment is free
and decides everything.

When they are needed:

- **Type**: skip datacenter proxies (same weakness as the VM's own IP). Start with **ISP / static
  residential** (~$2–5/IP/mo); move to **rotating residential** (~$2–8/GB) if Cloudflare is harsh.
- **Wiring**: Playwright takes a proxy **per browser context**, so each `--worker` can have its own
  exit IP. One optional argument on `create_browser_context()` in `scraper/utils/browser.py`;
  nothing downstream changes.
- **⚠️ Sticky sessions, not per-request rotation.** Cloudflare's clearance cookie is **bound to the
  IP that earned it**. If the proxy rotates mid-scrape the cookie is instantly invalid. Providers
  pin an exit IP via a session id in the username (`user-session-worker3`). Get this wrong and
  proxies make things *worse*, in a confusing way.
- **Per-job-type setting**: private/authed scrapes go **direct** (no proxy, no bandwidth cost);
  only public scrapes route through the proxy. Just another key in the job's `params`.
- **Free stopgap**: run public scrapers from an office/home residential line (hybrid), ₹0.

---

## Known risks

- **Platform-session expiry** — the most likely cause of a failed unattended run while auto-login is
  out of scope. Must fail loudly with a distinct `auth_expired` reason.
- **Connection pools are per-process and lazy** — they look fine until real concurrent load. Keep
  `DB_POOL_SIZE` small (3–5) on the runner and CLI, and re-do the arithmetic above before adding a
  lane slot.
- **`JobStatus` is a native Postgres enum** shared with `scrape_jobs`/`explorer_runs`. Adding a value
  (e.g. `cancelled`) needs an `ALTER TYPE`, so v1 sticks to the existing four and treats cancellation
  as `failed` with a reason.

---

## Handover: campaign manager

The bid optimizer and budget scheduler currently run on an **APScheduler inside the FastAPI
lifespan** ([app/main.py](../backend/app/main.py)), and `run_scheduler_inprocess` drives a real
Playwright browser that **writes budgets to Blinkit**.

Coworker-owned and **not touched by this work**. But when the API deploys to Render, three things
break:

1. **Render has no Chromium** — the build only runs `pip install`. The job crashes every tick.
2. **Wrong IP** — it would hit Blinkit with an authed session from a US datacenter.
3. **Double-firing is a money bug** — if the VM ever runs it too, two schedulers write `daily_budget`
   to live campaigns.

The clean landing: register them as the two reserved **`live`-lane** `campaign.*` job types, and gate
the in-API scheduler behind an env flag that is **off on Render**. The `live` lane exists precisely so
that, once moved, the bid optimizer is never starved by a batch scrape.

---

## Build phases

| Phase | Contents | Outcome |
|---|---|---|
| **1 — Queue + runner** ✅ | `jobs` table (with `lane`), migration `a7f3c2e9d4b1`, `cli runner`, per-lane claim + slots, subprocess dispatch, per-run log files, stale-lock reaper, systemd unit, `cli jobs run/list/logs`. Lives in the top-level `jobs/` package. | No more typing scrapes over SSH; every run is recorded |
| **2 — Scheduler** ✅ | `job_schedules` table, migration `b8e5d1a3f9c2`, cron producer (`jobs/scheduler.py`, runs alongside the consumer), catchup/misfire logic, `cli schedules add/list/enable/disable/remove`. Next-fire computed via APScheduler's CronTrigger against fixed-offset IST. | Scrapes run on time, unattended |
| **3 — Observability** ✅ | absolute `LOG_DIR` (P1), structured JSON `runner.log` (`cli runner start` sink), per-lane log paths, `maint.log_cleanup` + `cli maint log-cleanup`, `monitor.heartbeat` (deadman + disk) + `cli monitor heartbeat`, `cli jobs logs --follow`, Ops Agent config (`deploy/ops-agent-logging.yaml`) shipping to Cloud Logging | Failures are visible from a browser — **alert policy still to create** |
| **4 — API** | `GET /api/jobs`, `/jobs/{id}/log`, `POST /api/jobs`, `GET/POST/PATCH /api/job-schedules` | UI-ready |

### Validated on the VM, 2026-07-17

Everything below was proven on real hardware, not just locally:

- **systemd daemon** — `enabled`, survives SSH death, laptop crash, and reboot.
- **Crash recovery** — `systemctl kill -s KILL` mid-scrape killed the whole cgroup
  (runner + subprocess + **six chrome-headless**, so *no orphaned browsers*); systemd
  restarted after 10 s; the runner logged `reaped 1 stale running job(s)` and the
  stranded row became `failed / runner_died`. A restart that was itself killed 1 s in
  proved the reaper retries on **every** startup.
- **Graceful shutdown** — SIGTERM → producer + consumer stop cleanly → nothing to reap.
- **Scheduler** — real scrapes fired unattended on cron; the `dashboard` lane serialized
  marketing and seller as designed.
- **Cloud Logging** — the Ops Agent ships `runner.log` (JSON → queryable fields, severity
  mapped) and per-lane scraper output; visible in Logs Explorer with no SSH.

**Three bugs only real use could find**, all in the heartbeat (the one component that
*reasons about* the system rather than doing work):
1. **Self-monitoring loop** — it audited its own schedule, so one stale run made it fail
   forever (a failed heartbeat records no success → guarantees the next is stale).
   Fixed by skipping self-monitoring types; the monitor's own liveness must be answered
   *outside* the system (a Cloud Monitoring absence alert).
2. **New-schedule false positive** — "never succeeded" was treated as broken, so a
   freshly-created weekly schedule was flagged days before its first run was due. Fixed
   by measuring age from `last_success or created_at`.
3. The `Queued …` hint printed `cli …`, which isn't a real command (`python -m cli` is).

The deadman window is derived from each schedule's own cron period (× 1.1), so a
daily alerts at ~26h and a weekly at ~8d without any per-schedule config. Heartbeat
runs in the **interactive** lane so it fires promptly, never queued behind a scrape.
Cloud Logging integration (`runner.log` JSON → filterable fields; per-run logs as
plain text) is real but only testable on the VM — see `deploy/ops-agent-logging.yaml`.

> Both migrations branch off the DB's line; head count stays 2 (the divergent
> coworker branch `b7c3d8e2f1a9` is untouched). Apply on this line with an explicit
> target, e.g. `alembic upgrade b8e5d1a3f9c2` — a bare `upgrade head` errors on 2 heads.

Phase 4 is what makes Render safe: **the API only enqueues — it never executes.** All browser work
stays on the VM, on an Indian IP.
