# Alerting — closing the loop

Everything already gets *recorded*: the `jobs` table knows, Cloud Logging has the line,
the dashboard shows it. Nothing **tells you**. These two policies are what turn a log
into an email.

> ⚠️ Until 2026-08-04 a failed job was logged at **WARNING**, so the `severity>=ERROR`
> policy below would have matched nothing. That is fixed (`jobs/runner.py` logs failures
> at ERROR with structured fields). If you add a new failure path, **log it at ERROR** or
> it is invisible here.

## The two policies, and why both

| File | Fires when | Catches |
|---|---|---|
| `runner-errors.json` | Any runner ERROR | Failed jobs — `auth_expired`, `oom`, `timeout`, `exit_N` — and overdue-schedule warnings |
| `runner-silent.json` | No runner logs for 2 h | The runner, the VM, or the log shipper dying |

The second is not redundant. **A dead runner cannot report its own death.** If the VM is
off or the Ops Agent's shipper wedges, the first policy simply goes quiet — and silence
is indistinguishable from health.

## Why these were rewritten (2026-08-18)

The SILENT policy **worked**. During a six-day logging blackout it fired, on time, and
delivered this:

```
[ALERT - No severity] No runner log lines for 2 hours on foresight-vm foresight-vm
```

It was read as noise and the blackout ran another six days. The monitoring was never the
problem — **the wording was**. That subject line is also the single most useful thing we
learned, because every part of it turns out to be a field we control:

| What you see | Where it comes from | Now set to |
|---|---|---|
| `No severity` | the policy's `severity` field, unset | `ERROR` / `CRITICAL` |
| `No runner log lines for 2 hours` | the **condition's** `displayName` | a sentence naming the consequence |
| `on foresight-vm foresight-vm` | appended by Google | — (not controllable) |

**Which name reaches the subject depends on the condition type** (confirmed by reading
both kinds of real email, 2026-08-19):

| Condition | Subject format |
|---|---|
| `conditionAbsent` (metric) | `[ALERT - <severity>] <condition displayName> on <resource>` |
| `conditionMatchedLog` | `[ALERT - <severity>] <policy displayName> for <resource>` |

So keep **both** names meaningful — you do not get to choose which one Google uses, and
the trailing resource blob is appended either way and is not controllable. Neither is
`documentation.subject`, which both policies deliberately omit (see below).

**Neither policy sets `documentation.subject`, on purpose.** It was tried and removed: a
subject interpolating `${…client}` and `${…job}` renders as *"Foresight: — failed"* for
the half of this policy's traffic that comes from the health check, which binds no job
fields (see below). A subject that is broken half the time is worse than one that is
merely generic, and the condition `displayName` already carries the useful half. It also
avoids depending on a field some `gcloud` versions reject.

For the same reason the error condition is named *"Foresight job failure or overdue
schedule"* rather than *"a job failed"* — both really do trip it, and the subject line is
the one part of the email that must never be wrong.

### The body now names the actual incident

`conditionMatchedLog` supports `labelExtractors`, which pull fields out of the matched
log entry; the documentation then interpolates them as `${log.extracted_label.<key>}`.
The runner binds `client`, `job_label`, `error`, `duration_s`, `log_tail` and `log_file`
on every failure, so the email can say *"Dobra — Blinkit ads scrape failed: Timeout
waiting for campaign table"* instead of a static paragraph about five error kinds that
exist in general.

**The body leads with `summary` (`jsonPayload.record.message`) on purpose.** Two very
different things trip this policy: a failed job, and the hourly health check reporting an
overdue schedule. The health check's ERROR lines come from `jobs/monitor.py` and carry
**none** of the job fields — `client` and `job` would render empty. But its message is
already a good sentence (`HEARTBEAT: 'DOBRA | Blinkit scorecard weekly' … exceeds window
185h`). Leading with the message makes the email readable in both cases; the structured
fields below it are a bonus when present, not the thing the email depends on.

> ⚠️ **`client`, `job_label`, `log_tail` and `duration_s` only exist once the 2026-08-18
> logging work is deployed to the VM.** Before that they render empty — harmless, and
> `summary`, `reason` and `log_file` work today. Extracting a field that isn't there is
> not an error.

**The SILENT policy cannot do any of this.** `conditionAbsent` is a *metric* condition,
and log labels only exist for log-based conditions — there is no matched log entry to
extract from, which is the whole point of an absence alert. Its documentation is static
by necessity, so it was rewritten to lead with what the reader must do, and to explain
how to tell "only the shipping is broken" from "work is actually being missed" using
`cli status`.

## Applying them

```bash
bash deploy/alerts/apply.sh
```

That is the whole thing. `apply.sh` finds the notification channel and the existing
policies **by display name**, substitutes the channel id itself, and updates in place —
so there is nothing to copy, paste or look up, and re-running it is safe.

It matches the current display name first and then the previous one, which is why it
still works even though this rewrite renamed both policies. When nothing matches it
creates rather than updates, and says so.

> **Never `gcloud alpha monitoring policies create` by hand for these two.** They already
> exist. Creating leaves you with duplicate policies alerting twice on the same log line,
> which is indistinguishable from a flapping alert and takes a while to notice.

### Where to run it

**Locally is best** — install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
once, `gcloud init`, and the script runs straight from the repo with no uploads. That
install also unlocks `gcloud compute ssh foresight-vm --command="…"` and `gcloud compute
scp`, which turn every future VM investigation into a one-liner from your laptop instead
of a browser SSH session. The 2026-07-24 and 2026-08-18 incidents were both diagnosed
blind from the database because this wasn't installed.

**Cloud Shell** (the `>_` icon, top-right of the console) is the no-install fallback:
`gcloud` is pre-installed and authenticated as you. Upload the three files from this
directory (⋮ → Upload) and run the script there.

Either way, use your own credentials — **not** the VM's browser SSH. The VM's service
account generally cannot manage alert policies.

> **If `severity` is rejected** by your `gcloud` version, drop that one field and re-run —
> you lose the `[ALERT - Error]` prefix but nothing else. Everything else here is
> long-standing API surface.

> **`notificationRateLimit` is only legal on log-based policies** (`conditionMatchedLog`).
> The silence policy uses `conditionAbsent`, a *metric* condition, and the API rejects the
> field outright: `INVALID_ARGUMENT: only log-based alert policies may specify a
> notification rate limit`. It uses `autoClose` alone.

## Verifying they actually work

An alert nobody has ever seen fire is an alert you do not have. Force one:

```bash
# on the VM — a job type that fails fast, in a lane nothing else uses
python -m cli jobs run monitor.heartbeat disk_pct=0     # threshold 0 => always "full"
```

That exits non-zero, the runner logs ERROR, and the email should arrive within a few
minutes. **Do this once after every edit**, and read the email rather than just noting it
arrived — the failure being guarded against now is an unreadable alert, not a missing one.

Check specifically that:

- the **subject** names the problem, not the metric
- the severity prefix is no longer `No severity`
- `${log.extracted_label.…}` placeholders have been **replaced by values**, not printed
  literally (a literal `${…}` in the email means the key doesn't match an extractor)

For the silence policy, stopping the runner for >2 h is the honest test but costs real
scrapes; the cheaper check is confirming the metric has data:

```bash
gcloud logging metrics describe foresight_runner_lines
```

## Deliberately not alerted

- **`consecutive_failures` on `platform_sessions`.** Repeated auto-login failure is worth
  knowing about, but it already surfaces as `auth_expired` ERRORs on every affected run,
  and the circuit breaker stops the retries. A second channel for the same fact is noise.
- **Individual scrape row counts.** Data-quality alerting is a different problem and
  belongs on the data, not on the runner.
- **Host memory.** Measured against the 2026-08-11 incident it would not have helped: a
  runaway fluent-bit at 890 MB is 11% of an 8 GB box. **Sustained CPU** is the signal that
  would have caught it (~70% of one core against a near-idle baseline) — a candidate for a
  future policy, not one of these two.
