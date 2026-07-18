# Staging — Local SQLite Between Scrape and Database

**Status: built 2026-07-18, manual load.** Applies to the two public scrapes
(`public-run`, `public-skus`) only.

## Why

A full public run is ~1.5 hours and ~185k rows. Writing straight to Supabase coupled
the scrape's success to the database being reachable *continuously for that whole
window* — one pooler blip, home-NAT drop or maintenance restart destroyed a run that
Blinkit had served perfectly.

The standard mitigations were already in place and **still not enough**:

| already done | where |
|---|---|
| `pool_pre_ping=True` (validate at checkout) | [database.py](../backend/app/core/database.py) |
| `pool_recycle=1800` (never reuse a stale connection) | same |
| retry-once on `connection_invalidated` | `storage.py`, `sku_storage.py` |

There is no config knob left, because this is a **coupling** problem, not a tuning
one. So the scrape and the database write were separated — the E and L of ETL.

## How it works

```
scrape ──► staging/<kind>_<tenant8>_<timestamp>.sqlite3 ──► cli scrape load ──► Postgres
   (no DB connection at all)                                (one transaction)
```

- **The scrape phase needs zero DB connections** beyond a brief config read at start.
  Supabase can be down for the entire scrape and the run still succeeds.
- **`cli scrape load` pushes a file in ONE all-or-nothing transaction.** If it fails,
  Postgres rolls back, nothing is written, and re-running is trivially safe.
- **`scraped_at` is stamped at scrape time** and carried through untouched — loading
  tomorrow must not backdate today's trend series.
- **The `scrape_jobs` row is created at LOAD time**, not scrape time, so a run that is
  never loaded leaves no phantom `running` job behind. The `job_id` is generated
  locally at scrape start and carried into the DB unchanged.

### Why all-or-nothing rather than chunk-and-resume

Public data is **append-only — no upsert, no unique constraint**. A *partially*
applied load would silently duplicate rows on the next attempt. Atomicity makes retry
safety free: either everything committed, or nothing did.

Verified safe against this database (2026-07-17):

```
statement_timeout                   = 2min   -- per STATEMENT; our 1000-row chunks are ms
idle_in_transaction_session_timeout = 0      -- nothing kills a long transaction
```

The cost is redoing a failed load from scratch — ~60s, against the ~1.5h scrape it
protects.

## Commands

```bash
python -m cli scrape public-run  --tenant <uuid> [--resume]   # → staging file
python -m cli scrape public-skus --tenant <uuid> [--resume]   # → staging file

python -m cli scrape staged [--pending]      # what's on disk, what's unpushed
python -m cli scrape load --dry-run          # what would be pushed
python -m cli scrape load                    # push (several pending needs --all)
python -m cli scrape load --file 145458      # push one
python -m cli scrape discard --file 145458   # delete one without loading it
```

`--file` takes the short **Ref** from `scrape staged` (the run's start time), a
filename, or a path — anything that matches one file. `staged` looks like:

```
Date         Time    Kind     Stores      Rows   Err   State           Ref
2026-07-18   14:54   skus      10/10       196     0   ok · pending    145458
2026-07-18   09:12   search   500/2,059    100   847   failed · …      091203
```

`Stores` (done/total) and `Err` are the quality signals: the second row covered a
quarter of its stores and threw 847 errors — obviously a bad run.

### Which files does `load` touch?

| | 1 pending | several pending |
|---|---|---|
| `load` | loads it | **refuses**, lists them |
| `load --all` | loads it | loads all, oldest first |
| `load --file X` | loads X | loads X |

**`--all` refuses outright if any pending file did not finish cleanly**, and makes
you choose per file — load it with `--file` or drop it with `discard`. A crashed run
is *not* auto-skipped, because 500 of 2059 stores is still 500 stores of real data;
only a human can judge that. What the guard prevents is a bad run being swept into
the database unnoticed.

**Each file is its own transaction, so `--all` is atomic per file, not across all
of them.** If file 3 of 5 fails, files 1-2 and 4-5 still commit and file 3 stays
`pending` — rerun to retry just that one.

`--resume` now reads the **staging file**, not the database — so resuming works even
while Supabase is down. It continues the newest unloaded, unfinished run for that
tenant+kind.

## Retention

Loaded files are kept — **last 5 per tenant per kind** — then pruned oldest-first on
the next successful load. **Unloaded files are never pruned**: deleting one would
destroy an unpushed scrape.

## The one thing that isn't a straight copy

`search_listings.snapshot_id` points at a Postgres serial that only exists after
insert. So the loader inserts snapshots first, captures the real ids, and remaps each
listing's local parent id. `sku_snapshots` has no such FK and *is* a straight copy.

## Failure modes to know

- **"Scraped but never loaded."** The new failure mode this design introduces. Data
  sitting in a file nobody pushed. `cli scrape staged` lists pending files, and both
  scrapes log a reminder on completion.
- **A failed load leaves the file untouched** — rerun the same command.
- **Files are local to the machine that scraped.** The VM's staging files are on the
  VM. Nothing is synced.
- **`discard` on an unloaded file is irreversible** — those rows exist nowhere else.
  It prints the run's stats and prompts before deleting (`--force` skips the prompt).
- **A file already loaded cannot be loaded twice** — the loader refuses with
  `already loaded at <when>`, so a stray rerun can't duplicate anything.

## Scope / not covered

- Ad-hoc `scrape public --save` (single keyword) still writes **directly** to the DB —
  one search, staging would only add friction.
- Dashboard/seller scrapes are minutes long and unchanged.
- The jobs/runner integration is **not** wired up — a staged run is two phases and the
  runner dispatches one subprocess per job. Deferred until the local flow is proven.

## Files

| file | role |
|---|---|
| [staging.py](../backend/scraper/public/staging.py) | schema, writers, resume helpers, retention |
| [loader.py](../backend/scraper/public/loader.py) | the single-transaction push |
| [scrape.py](../backend/cli/commands/scrape.py) | `scrape staged`, `scrape load` |
