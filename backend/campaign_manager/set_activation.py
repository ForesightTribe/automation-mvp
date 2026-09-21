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
              platform: str = "blinkit", run_id: str | None = None) -> dict:
    dry_run = config.DRY_RUN_DEFAULT if dry_run is None else dry_run
    run_id = run_id or logs.new_run_id()
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
    mp = platform.title()
    verb = _VERBS.get(status, f"set to {status}")
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError as e:
        logs.session_expired(run_id, dry_run=dry_run, platform=platform)
        # A person clicked Start/Stop and is waiting on it — say why nothing happened.
        await _record_blocked(tenant_id, platform, run_id, campaign_id, status, dry_run,
                              f"could not sign in to {mp}, so the campaign was not {verb}", e)
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
            await _record_blocked(tenant_id, platform, run_id, campaign_id, status, dry_run,
                                  f"the ad account could not be confirmed, so the campaign "
                                  f"was not {verb}", e)
            logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                             processed=0, applied=0, skipped=0, errors=1)
            return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    applied = skipped = errors = 0
    patches: list[dict] = []
    # See set_budget._reason: a refused start/stop used to record only "set-activation:
    # running->paused", which says what was asked and never why it did not happen.
    outcome: dict = {}
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
            budget=target_budget, overwrites=overwrites, applied=patches,
            outcome=outcome, hold_reason=writes.hold_reason(adapter, current, detail),
            recent_writes=0 if dry_run else await repo.recent_write_count(
                tenant_id, campaign_id,
                window_minutes=config.RATE_WINDOW_MINUTES, kind="activation"),
        )
        applied, skipped = int(ok), int(not ok)
        done = f"the campaign was {verb} on request" + (
            f" at ₹{target_budget:g}" if ok and status == "running" and target_budget else "")
        action, success, reason = _verdict(ok, outcome, done)
        rows = [_row(tenant_id, platform, run_id, campaign_id, name,
                     action, current, status, dry_run, success=success, reason=reason)]

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
            # Its own outcome: the status write's "already running" must not be mistaken
            # for the budget write's result.
            budget_outcome: dict = {}
            budget_ok = await writes.apply_budget(
                adapter, client, run_id=run_id, campaign_id=campaign_id,
                target=target_budget, current=current_budget, dry_run=dry_run,
                applied=patches, outcome=budget_outcome,
                recent_writes=0 if dry_run else await repo.recent_write_count(
                    tenant_id, campaign_id,
                    window_minutes=config.RATE_WINDOW_MINUTES, kind="budget"),
            )
            applied, skipped = int(budget_ok), int(not budget_ok)
            b_action, b_success, b_reason = _verdict(
                budget_ok, budget_outcome,
                f"the campaign was already running, so only its budget was set to "
                f"₹{target_budget:g}")
            rows.append(_row(tenant_id, platform, run_id, campaign_id, name,
                             b_action, current, status, dry_run, success=b_success,
                             reason=b_reason, kind="budget",
                             old_value=current_budget, new_value=target_budget))
    except Exception as e:
        logs.decision(run_id, dry_run=dry_run, campaign_id=campaign_id,
                      verdict="error", reason=str(e))
        errors = 1
        rows = [_row(tenant_id, platform, run_id, campaign_id,
                     await repo.campaign_name(tenant_id, campaign_id, platform), "error", None,
                     status, dry_run, success=False,
                     reason=_detail(f"the campaign could not be {verb} on {mp}", e))]
    finally:
        await _close(pw, browser)

    await repo.write_run_log(rows)
    await repo.record_applied(tenant_id, platform, patches)
    logs.run_summary(run_id, "set_activation", dry_run=dry_run, unit="campaigns",
                     processed=1, applied=applied, skipped=skipped, errors=errors)
    return {"processed": 1, "applied": applied, "skipped": skipped, "errors": errors}


async def _close(pw, browser) -> None:
    if browser is not None:
        await browser.close()
    if pw is not None:
        await pw.stop()


# What each target status is called in a History sentence.
_VERBS = {"running": "started", "paused": "stopped"}


def _reason(ok: bool, outcome: dict, verb: str) -> str:
    """See set_budget._reason. `verb` is the sentence for a landed change; a refusal is
    replaced by its cause, since the row already carries the transition it was attempting."""
    if ok:
        return verb
    return outcome.get("reason") or "no reason given"


def _verdict(ok: bool, outcome: dict, done: str) -> tuple[str, bool, str]:
    """(action, success, reason) — see set_budget._verdict. "The campaign is already
    running" is a successful `no-op`, not a failure; a refusal is an unsuccessful `skip`."""
    if ok:
        return "apply", True, done
    if writes.not_needed(outcome):
        return "no-op", True, outcome["reason"]
    return "skip", False, _reason(False, outcome, done)


def _detail(what: str, err) -> str:
    """`what` plus the raw cause on one short line — see set_budget._detail."""
    detail = " ".join(str(err).split())
    if len(detail) > 120:
        detail = detail[:117] + "…"
    return f"{what} ({detail})" if detail else what


async def _record_blocked(tenant_id, platform, run_id, campaign_id, status, dry_run,
                          what: str, err) -> None:
    """The row for a run that never reached the write. Never raises."""
    try:
        name = await repo.campaign_name(tenant_id, campaign_id, platform)
        await repo.write_run_log([_row(tenant_id, platform, run_id, campaign_id, name,
                                       "error", None, status, dry_run, success=False,
                                       reason=_detail(what, err))])
    except Exception as e:
        logs.note(run_id, f"could not record why the run was blocked: {e}", dry_run=dry_run)


def _row(tenant_id, platform, run_id, cid, cname, action, old, new, dry_run, *,
         success=True, reason="", kind="activation", old_value=None,
         new_value=None) -> dict:
    """cm_run_log row. `kind="activation"` keeps status changes filterable in History and
    separate from the budget rows the same campaign produces; a follow-up budget write from
    the already-running path is logged as `budget`, because that is what it is.

    `old`/`new` are the states, and are no longer glued onto the reason as "paused→running":
    the reason is the sentence, and a status row has no numeric old/new value to show."""
    return {"tenant_id": tenant_id, "platform": platform, "run_id": run_id,
            "kind": kind, "campaign_id": cid, "campaign_name": cname,
            "keyword": None, "action": action, "old_value": old_value,
            "new_value": new_value, "reason": reason, "dry_run": dry_run,
            "success": success}
