#!/usr/bin/env bash
#
# Apply the alert policies in this directory. Run it from anywhere:
#
#     bash deploy/alerts/apply.sh
#
# Finds each policy by a stable label, updates it in place, and creates it only when it
# genuinely does not exist. Safe to re-run.
#
# ── How policies are identified, and why ──────────────────────────────────────────
# By `userLabels.foresight_policy`, NOT by displayName.
#
# v1 of this script matched on displayName and CREATED DUPLICATES on 2026-08-19. The
# display names contain an em-dash, and gcloud's output renders non-ASCII as `?` in a
# Windows console — so the literal em-dash in the script never matched anything, every
# lookup "found nothing", and it happily created a second copy of both policies. A label
# is ASCII, is ours to set, and survives renaming the policy.
#
# The other half of that bug was the fallback: creating when no match is found is only
# correct if "no match" reliably means "does not exist". So this version REFUSES to act
# when the situation is ambiguous (see the adopt step) rather than guessing. An alerting
# system that silently doubles up is worse than one that stops and asks.
#
# Needs: gcloud, authenticated, with Monitoring Admin on the project. Works in Cloud
# Shell as-is; locally, install the Google Cloud CLI and run `gcloud init`.
#
# Overridable:  PROJECT=... CHANNEL_NAME=... bash deploy/alerts/apply.sh

set -euo pipefail

PROJECT="${PROJECT:-foresight-vm}"
CHANNEL_NAME="${CHANNEL_NAME:-Foresight ops email}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v gcloud >/dev/null 2>&1 || {
  echo "gcloud not found."
  echo "  Cloud Shell has it already; locally, install the Google Cloud CLI and run 'gcloud init'."
  exit 1
}

echo "project: $PROJECT"
gcloud config set project "$PROJECT" >/dev/null

# The channel already exists — reuse it. A second channel with the same address just
# means two copies of every email.
CHANNEL="$(gcloud beta monitoring channels list \
  --filter="displayName=\"$CHANNEL_NAME\"" \
  --format="value(name)" 2>/dev/null | head -1)"
if [ -z "$CHANNEL" ]; then
  echo "No notification channel named '$CHANNEL_NAME'. Existing channels:"
  gcloud beta monitoring channels list --format="table(displayName,type,name)"
  exit 1
fi
echo "channel: $CHANNEL"

apply() {
  local file="$1" label="$2" filter_pat="$3"

  local tmp; tmp="$(mktemp)"
  sed "s|REPLACE_WITH_CHANNEL_ID|$CHANNEL|" "$file" > "$tmp"
  if grep -q REPLACE_WITH_CHANNEL_ID "$tmp"; then
    echo "  ! channel substitution failed in $(basename "$file")"; rm -f "$tmp"; exit 1
  fi

  # 1. The normal path: find it by our own label.
  local existing
  existing="$(gcloud alpha monitoring policies list \
    --filter="userLabels.foresight_policy=$label" \
    --format="value(name)" 2>/dev/null | head -1)"

  # 2. Adoption path, for a policy that predates the label. Match on the condition
  #    FILTER — pure ASCII, and it is what the policy actually does. Updating stamps the
  #    label on, so this branch runs at most once per policy.
  if [ -z "$existing" ]; then
    local candidates count
    candidates="$(gcloud alpha monitoring policies list \
      --format="value(name,conditions.conditionMatchedLog.filter,conditions.conditionAbsent.filter)" \
      2>/dev/null | grep -F -- "$filter_pat" | cut -f1 || true)"
    count="$(printf '%s' "$candidates" | grep -c . || true)"

    if [ "$count" -gt 1 ]; then
      # THE GUARD. More than one policy already does this job — creating another would
      # make it three. Refuse and let a human decide which to keep.
      echo "  ! $label: $count existing policies match '$filter_pat':"
      printf '%s\n' "$candidates" | sed 's/^/      /'
      echo "  ! Refusing to touch them — delete the extras, then re-run."
      rm -f "$tmp"; return 1
    fi
    existing="$candidates"
    [ -n "$existing" ] && echo "  (adopting unlabelled policy $existing)"
  fi

  if [ -n "$existing" ]; then
    echo "updating $label -> $existing"
    gcloud alpha monitoring policies update "$existing" --policy-from-file="$tmp" >/dev/null
  else
    echo "creating $label (nothing existing matched)"
    gcloud alpha monitoring policies create --policy-from-file="$tmp" >/dev/null
  fi
  rm -f "$tmp"
}

rc=0
apply "$DIR/runner-errors.json" runner_errors 'severity>=ERROR'       || rc=1
apply "$DIR/runner-silent.json" runner_silent 'foresight_runner_lines' || rc=1

echo
gcloud alpha monitoring policies list \
  --format="table(displayName,enabled,severity,userLabels.foresight_policy)" 2>/dev/null

if [ "$rc" -ne 0 ]; then
  echo
  echo "Nothing was changed for the policies flagged above. Resolve them and re-run."
  exit 1
fi

echo
echo "Now force one real alert and READ the email:"
echo "    python -m cli jobs run monitor.heartbeat disk_pct=0"
