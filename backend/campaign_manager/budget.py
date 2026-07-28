"""Budget-scheduler orchestration (MP-agnostic).

Load a tenant's budget schedules, decide the target budget for *now*, and apply it
through the write choke-point. Dry-run by default.

**V0 scaffold:** loads schedules and logs the run end-to-end; with no schedules it
does nothing (and never touches Blinkit). The rule-matching (which budget applies
now) + the guardrailed apply land in **V1** — the marked spot below.
"""
import uuid

from campaign_manager import config, logs, repo


async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "budget_scheduler", tenant_id, dry_run=dry_run, platform=platform)

    schedules = await repo.get_budget_schedules(tenant_id, platform)

    processed = applied = skipped = errors = 0
    for schedule, rules in schedules:
        processed += 1
        # ── V1 goes here ──────────────────────────────────────────────────────
        #   target = match_rule_for_now(rules) or schedule.default_budget
        #   current = await adapter.read_budget(client, schedule.campaign_id)
        #   ok = await writes.apply_budget(adapter, client, run_id=run_id,
        #            campaign_id=schedule.campaign_id, target=target,
        #            current=current, dry_run=dry_run, recent_writes=...)
        #   applied += int(ok); write the cm_run_log row
        # For now (V0), there is nothing to apply — a schedule exists but the
        # rule-matching isn't built, so we only account for it.
        skipped += 1

    logs.run_summary(run_id, "budget_scheduler", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}
