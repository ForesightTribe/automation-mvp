"""On-demand single-campaign budget set (MP-agnostic) — the `cm.set_budget` job.

Sets ONE campaign's daily budget through the write choke-point (dry-run by default).
Used by the UI "set budget now" action and by budget Reset (set → default_budget). No
rules involved — just read current → guardrailed apply. Mirrors budget.run's session +
arm-live + choke-point handling for a single value.
"""
import uuid

from campaign_manager import config, logs, repo, writes
from campaign_manager.marketplaces import get_adapter


async def run(tenant_id: uuid.UUID, campaign_id: int, budget: float, *,
              dry_run: bool | None = None, platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "set_budget", tenant_id, dry_run=dry_run, platform=platform)

    adapter = get_adapter(platform)
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "set_budget", dry_run=dry_run,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run)

    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            if browser is not None:
                await browser.close()
            if pw is not None:
                await pw.stop()
            logs.run_summary(run_id, "set_budget", dry_run=dry_run,
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    applied = skipped = errors = 0
    try:
        current = await adapter.read_budget(client, campaign_id)
        ok = await writes.apply_budget(
            adapter, client, run_id=run_id, campaign_id=campaign_id,
            target=budget, current=current, dry_run=dry_run, recent_writes=0,
        )
        applied, skipped = int(ok), int(not ok)
        row = _row(tenant_id, platform, run_id, campaign_id,
                   "apply" if ok else "skip", current, budget, dry_run)
    except Exception as e:
        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      verdict="error", reason=str(e))
        errors = 1
        row = _row(tenant_id, platform, run_id, campaign_id, "error", None, budget,
                   dry_run, success=False, reason=str(e))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_run_log([row])
    logs.run_summary(run_id, "set_budget", dry_run=dry_run,
                     processed=1, applied=applied, skipped=skipped, errors=errors)
    return {"processed": 1, "applied": applied, "skipped": skipped, "errors": errors}


def _row(tenant_id, platform, run_id, cid, action, old, new, dry_run, *,
         success=True, reason="set-budget") -> dict:
    return {"tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "budget",
            "campaign_id": cid, "campaign_name": None, "keyword": None, "action": action,
            "old_value": old, "new_value": new, "reason": reason,
            "dry_run": dry_run, "success": success}
