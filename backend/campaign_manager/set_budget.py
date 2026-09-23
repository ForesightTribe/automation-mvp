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
              dry_run: bool | None = None, platform: str = "blinkit",
              run_id: str | None = None) -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = run_id or logs.new_run_id()
    logs.run_start(run_id, "set_budget", tenant_id, dry_run=dry_run, platform=platform,
                   tenant_name=await repo.get_tenant_name(tenant_id))

    adapter = get_adapter(platform)
    # Read once, up front: every row this run can write — including the ones for a run that
    # never got going — should say which campaign it is about.
    name = await repo.campaign_name(tenant_id, campaign_id, platform)
    mp = platform.title()
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError as e:
        logs.session_expired(run_id, dry_run=dry_run)
        # A person asked for this and is waiting on it. Without a row the job settles with
        # nothing on the page saying the change never happened, or why.
        await _record_blocked(tenant_id, platform, run_id, campaign_id, name, budget, dry_run,
                              f"could not sign in to {mp}, so the budget was not changed", e)
        logs.run_summary(run_id, "set_budget", dry_run=dry_run, unit="campaigns",
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=dry_run, platform=platform)

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
            await _record_blocked(tenant_id, platform, run_id, campaign_id, name, budget,
                                  dry_run, "the ad account could not be confirmed, so the "
                                           "budget was not changed", e)
            logs.run_summary(run_id, "set_budget", dry_run=dry_run, unit="campaigns",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    applied = skipped = errors = 0
    patches: list[dict] = []
    # Why a write did not land, so the History row can say it. Without this the row read
    # "set-budget" whether the budget changed or Blinkit refused it outright.
    outcome: dict = {}
    try:
        current = await adapter.read_budget(client, campaign_id)
        ok = await writes.apply_budget(
            adapter, client, run_id=run_id, campaign_id=campaign_id,
            target=budget, current=current, dry_run=dry_run, recent_writes=0,
            applied=patches, outcome=outcome,
        )
        applied, skipped = int(ok), int(not ok)
        action, success, reason = _verdict(ok, outcome, budget)
        row = _row(tenant_id, platform, run_id, campaign_id, action, current, budget,
                   dry_run, success=success, reason=reason, name=name)
    except Exception as e:
        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      verdict="error", reason=str(e))
        errors = 1
        row = _row(tenant_id, platform, run_id, campaign_id, "error", None, budget,
                   dry_run, success=False, name=name,
                   reason=_detail(f"the budget change to ₹{budget:g} could not be sent to "
                                  f"{mp}", e))
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    await repo.write_run_log([row])
    await repo.record_applied(tenant_id, platform, patches)
    logs.run_summary(run_id, "set_budget", dry_run=dry_run, unit="campaigns",
                     processed=1, applied=applied, skipped=skipped, errors=errors)
    return {"processed": 1, "applied": applied, "skipped": skipped, "errors": errors}


def _reason(ok: bool, outcome: dict, budget: float | None = None) -> str:
    """What to record in History, as a sentence.

    A landed change says what was asked for — it used to say the literal job name,
    "set-budget", which told a client nothing. One that did not land is the whole reason
    anyone opens this screen, so it carries the CAUSE alone, in the marketplace's own words
    when there are any: every surface showing it already says the write did not land (the
    Execution logs' outcome column, the dashboard's "Nothing changed - {reason}"), so a
    "not applied" prefix here would say it twice.
    """
    if ok:
        return (f"the budget was set to ₹{budget:g} on request" if budget is not None
                else "the budget was set on request")
    return outcome.get("reason") or "no reason given"


def _verdict(ok: bool, outcome: dict, budget: float) -> tuple[str, bool, str]:
    """(action, success, reason). A budget that was already right is a successful `no-op`;
    a REFUSED change is an unsuccessful `skip`. Both used to be a successful `skip`, so a
    refusal showed green in the Execution logs.

    The cause alone for both, as in `_reason`: the dashboard's JobLine already frames this
    row as "Nothing changed — {reason}"."""
    if ok:
        return "apply", True, _reason(True, outcome, budget)
    if writes.not_needed(outcome):
        return "no-op", True, outcome["reason"]
    return "skip", False, _reason(False, outcome, budget)


def _detail(what: str, err) -> str:
    """`what`, plus the raw cause squeezed to one short line — a History reason is a table
    cell, and a multi-line API error pasted into it broke the layout (bid._plain)."""
    detail = " ".join(str(err).split())
    if len(detail) > 120:
        detail = detail[:117] + "…"
    return f"{what} ({detail})" if detail else what


async def _record_blocked(tenant_id, platform, run_id, campaign_id, name, budget, dry_run,
                          what: str, err) -> None:
    """The row for a run that never reached the write. Never raises: bookkeeping must not
    mask the fault it is recording (same rule as budget._record_run_blocked)."""
    try:
        await repo.write_run_log([_row(tenant_id, platform, run_id, campaign_id, "error",
                                       None, budget, dry_run, success=False,
                                       reason=_detail(what, err), name=name)])
    except Exception as e:
        logs.note(run_id, f"could not record why the run was blocked: {e}", dry_run=dry_run)


def _row(tenant_id, platform, run_id, cid, action, old, new, dry_run, *,
         success=True, reason="the budget was set on request", name=None) -> dict:
    return {"tenant_id": tenant_id, "platform": platform, "run_id": run_id, "kind": "budget",
            "campaign_id": cid, "campaign_name": name, "keyword": None, "action": action,
            "old_value": old, "new_value": new, "reason": reason,
            "dry_run": dry_run, "success": success}
