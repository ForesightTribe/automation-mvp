"""Bid-optimizer orchestration (MP-agnostic).

Load a tenant's bid rules, read each keyword's live position (tiered by state),
compute the new CPM (distance step, HOLD, clamp), and apply through the write
choke-point. Runtime state (`last_*`) is persisted to `cm_bid_runtime` — no JSON.

**V0 scaffold:** loads rules and logs the run; the position sourcing (positions.py)
+ bid math + guardrailed apply land in **V2**.
"""
import uuid

from campaign_manager import config, logs, repo


async def run(tenant_id: uuid.UUID, *, dry_run: bool | None = None,
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "bid_optimizer", tenant_id, dry_run=dry_run, platform=platform)

    rules = await repo.get_bid_rules(tenant_id, platform)

    processed = applied = skipped = errors = 0
    for rule, runtime in rules:
        processed += 1
        # ── V2 goes here ──────────────────────────────────────────────────────
        #   position = await positions.get(...)   # tiered: live scrape / report / snapshot
        #   new_cpm = step(position, rule, runtime)  # distance step + HOLD
        #   ok = await writes.apply_bid(adapter, client, run_id=run_id, ...)
        #   persist runtime (last_cpm/last_position/last_bid_updated_at) to cm_bid_runtime
        skipped += 1

    logs.run_summary(run_id, "bid_optimizer", dry_run=dry_run,
                     processed=processed, applied=applied, skipped=skipped, errors=errors)
    return {"processed": processed, "applied": applied, "skipped": skipped, "errors": errors}
