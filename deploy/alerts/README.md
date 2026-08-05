# Alerting — closing the loop

Everything already gets *recorded*: the `jobs` table knows, Cloud Logging has the line,
the dashboard shows it. Nothing **tells you**. These two policies are what turn a log
into an email.

This has been the longest-standing open item in the system — since the July 2026
incident, where the heartbeat correctly reported a broken seller session **every hour
for two days** into a void.

> ⚠️ Until 2026-08-04 a failed job was logged at **WARNING**, so the `severity>=ERROR`
> policy below would have matched nothing. That is fixed (`jobs/runner.py` logs failures
> at ERROR with structured fields). If you add a new failure path, **log it at ERROR** or
> it is invisible here.

## The two policies, and why both

| File | Fires when | Catches |
|---|---|---|
| `runner-errors.json` | Any runner ERROR | Failed jobs — `auth_expired`, `oom`, `timeout`, `exit_N` — and heartbeat problems |
| `runner-silent.json` | No runner logs for 2 h | The runner, the VM, or the log shipper dying |

The second is not redundant. **A dead runner cannot report its own death.** If the VM is
off or the Ops Agent's shipper wedges, the first policy simply goes quiet — and silence
is indistinguishable from health. Cloud Logging went dark on 2026-07-23 and nobody
noticed for exactly this reason.

## Applying them

Everything below is idempotent-ish; `gcloud` will refuse duplicates by display name.

### 1. A notification channel (once)

```bash
gcloud beta monitoring channels create \
  --display-name="Foresight ops email" \
  --type=email \
  --channel-labels=email_address=you@foresighttribe.com

# grab the full resource name — projects/foresight-vm/notificationChannels/1234567890
gcloud beta monitoring channels list --format="value(name,displayName)"
```

### 2. A log-based metric — only for the silence policy

`conditionAbsent` needs a *metric* to be absent; it cannot watch raw logs. So count
runner lines into a metric first:

```bash
gcloud logging metrics create foresight_runner_lines \
  --description="Lines emitted by the Foresight job runner (drives the silence alert)" \
  --log-filter='log_id("foresight_runner")'
```

> The metric only starts existing once it has data. Give it ~10 minutes of runner
> activity before creating the silence policy, or the policy will look permanently
> firing/unknown on first sight.

### 3. The policies

Substitute the channel id, then create:

```bash
CHANNEL=projects/foresight-vm/notificationChannels/REPLACE

for f in runner-errors runner-silent; do
  sed "s|REPLACE_WITH_CHANNEL_ID|$CHANNEL|" "$f.json" > "/tmp/$f.json"
  gcloud alpha monitoring policies create --policy-from-file="/tmp/$f.json"
done

gcloud alpha monitoring policies list --format="table(displayName,enabled)"
```

To edit later, change the JSON here and update in place (keeps it reviewable in git):

```bash
gcloud alpha monitoring policies list --format="value(name,displayName)"
gcloud alpha monitoring policies update <POLICY_NAME> --policy-from-file=/tmp/runner-errors.json
```

## Verifying they actually work

An alert nobody has ever seen fire is an alert you do not have. Force one:

```bash
# on the VM — a job type that will fail fast, in a lane nothing else uses
python -m cli jobs run monitor.heartbeat disk_pct=0     # threshold 0 => always "full"
```

That exits non-zero, the runner logs ERROR, and the email should arrive within a few
minutes. **Do this once after setup.** The failure mode being guarded against is a
policy with a typo'd filter that silently matches nothing — which is exactly the state
the system has been in until now.

For the silence policy, stopping the runner for >2 h is the honest test, but that costs
real scrapes; the cheaper check is confirming the metric has data:

```bash
gcloud logging metrics describe foresight_runner_lines
```

## Deliberately not alerted

- **`consecutive_failures` on `platform_sessions`.** Repeated auto-login failure is worth
  knowing about, but it already surfaces as `auth_expired` ERRORs on every affected run,
  and the circuit breaker stops the retries. A second channel for the same fact is noise.
- **Individual scrape row counts.** Data-quality alerting is a different problem and
  belongs on the data, not on the runner.
