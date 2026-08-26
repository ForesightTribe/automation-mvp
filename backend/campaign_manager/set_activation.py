"""On-demand single-campaign start/stop (MP-agnostic) — the `cm.set_activation` job.

Starts or stops ONE campaign through the write choke-point (dry-run by default). Used by
the UI's Start / Pause buttons; no rules involved. Mirrors `set_budget.py`'s session +
arm-live + choke-point handling.

Two things make this heavier than `set_budget`:

  - **Resuming re-submits the whole campaign** (see marketplaces/blinkit/restart.py), so a
    start needs a budget. When the caller doesn't supply one we fall back to what the
    campaign was already running at — never a guess, and never zero.
  - **`allow_draft` is True here and only here** (AD8): a human clicking Start on a draft
    means it; a scheduled rule reaching one does not.
"""
import uuid

from campaign_manager import config, logs, repo, writes
from campaign_manager.marketplaces import get_adapter


async def run(tenant_id: uuid.UUID, campaign_id: int, status: str, *,
              budget: float | None = None, dry_run: bool | None = None,
              platform: str = "blinkit") -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = logs.new_run_id()
    logs.run_start(run_id, "set_activation", tenant_id, dry_run=dry_run, platform=platform,
                   campaign_id=campaign_id, target=status,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    if status not in writes.WRITABLE_STATES:
        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id, verdict="error",
                      reason=f"status must be one of {writes.WRITABLE_STATES}, got {status!r}")
        logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    adapter = get_adapter(platform)
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=dry_run)
        logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run, platform=platform)

    if not dry_run:
        try:
            await writes.arm_live(adapter, client, run_id,
                                  await repo.get_advertiser(tenant_id, platform))
        except RuntimeError as e:
            logs.live_refused(run_id, reason=str(e))
            await _close(pw, browser)
            logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    applied = skipped = errors = 0
    try:
        current, current_budget, detail = await adapter.read_campaign(client, campaign_id)
        # Field naming differs per marketplace ("name" vs "campaign_name"), so ask
        # the adapter rather than guessing here.
        name = (adapter.campaign_name(detail)
                if hasattr(adapter, "campaign_name") else detail.get("name"))

        # A restart writes a budget; fall back to what the campaign already had rather than
        # inventing one. `writes.apply_status` rejects the write outright if this is still
        # unusable, so an unknown budget fails loudly instead of guessing.
        # Only a restart carries a budget — a stop is a bodiless DELETE, so passing one
        # there would be a meaningless argument that reads as if it did something.
        # Only a marketplace whose RESUME RE-SUBMITS the campaign needs a budget to
        # start one. Zepto's activate restores the campaign's own, so passing a
        # budget there would be a meaningless argument that reads as if it did
        # something — and demanding one would refuse every legitimate resume.
        resubmits = getattr(adapter, "RESUME_RESUBMITS", True)
        target_budget = ((budget if budget is not None else current_budget)
                         if status == "running" and resubmits else None)
        overwrites = None
        if status == "running" and hasattr(adapter, "resume_overwrites"):
            overwrites = adapter.resume_overwrites(detail, target_budget)

        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      verdict=f"target {status}",
                      reason=f"currently {current}" + (
                          f", budget ₹{target_budget:g}" if status == "running" and target_budget else ""))

        ok = await writes.apply_status(
            adapter, client, run_id=run_id, campaign_id=campaign_id,
            target=status, current=current, dry_run=dry_run, allow_draft=True,
            budget=target_budget, overwrites=overwrites,
            recent_writes=0 if dry_run else await repo.recent_write_count(
                tenant_id, campaign_id,
                window_minutes=config.RATE_WINDOW_MINUTES, kind="activation"),
        )
        applied, skipped = int(ok), int(not ok)
        rows = [_row(tenant_id, platform, run_id, campaign_id, name,
                     "apply" if ok else "skip", current, status, dry_run)]

        # "Start at ₹X" on a campaign that is ALREADY running must still honour the budget.
        # Normally the restart carries it — but there is no restart to make, so the status
        # write is a no-op and the number would be silently dropped.
        #
        # Budget Reset depends on this: on a `stop_after_window` schedule Reset enqueues a
        # start-at-default (the campaign may be stopped, and Reset must undo that too). If
        # the campaign happens to be running, without this the elevated window budget would
        # never come back down — and since Reset also marks the schedule stopped, no later
        # run would ever fix it.
        if status == "running" and not ok and current == "running" and target_budget is not None:
            budget_ok = await writes.apply_budget(
                adapter, client, run_id=run_id, campaign_id=campaign_id,
                target=target_budget, current=current_budget, dry_run=dry_run,
                recent_writes=0 if dry_run else await repo.recent_write_count(
                    tenant_id, campaign_id,
                    window_minutes=config.RATE_WINDOW_MINUTES, kind="budget"),
            )
            applied, skipped = int(budget_ok), int(not budget_ok)
            rows.append(_row(tenant_id, platform, run_id, campaign_id, name,
                             "apply" if budget_ok else "no-op", current, status, dry_run,
                             reason=f"already running · budget {current_budget}→{target_budget:g}",
                             kind="budget"))
    except Exception as e:
        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      verdict="error", reason=str(e))
        errors = 1
        rows = [_row(tenant_id, platform, run_id, campaign_id, None, "error", None, status,
                     dry_run, success=False, reason=str(e))]
    finally:
        await _close(pw, browser)

    await repo.write_run_log(rows)
    logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                     processed=1, applied=applied, skipped=skipped, errors=errors)
    return {"processed": 1, "applied": applied, "skipped": skipped, "errors": errors}


async def _close(pw, browser) -> None:
    if browser is not None:
        await browser.close()
    if pw is not None:
        await pw.stop()


def _row(tenant_id, platform, run_id, cid, cname, action, old, new, dry_run, *,
         success=True, reason="set-activation", kind="activation") -> dict:
    """cm_run_log row. `kind="activation"` keeps status changes filterable in History and
    separate from the budget rows the same campaign produces; a follow-up budget write from
    the already-running path is logged as `budget`, because that is what it is."""
    return {"tenant_id": tenant_id, "platform": platform, "run_id": run_id,
            "kind": kind, "campaign_id": cid, "campaign_name": cname,
            "keyword": None, "action": action, "old_value": None, "new_value": None,
            "reason": f"{reason}: {old}→{new}", "dry_run": dry_run, "success": success}
