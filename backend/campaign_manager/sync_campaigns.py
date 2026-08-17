"""Refresh the campaign catalogue from the live account — the `cm.sync_campaigns` job.

The cheap counterpart to the nightly marketing scrape: this pulls **only** the campaign
list and its statuses, not per-campaign metrics, keywords or products. One browser, two
API calls (enabled campaign types, then the list), seconds rather than the better part of
an hour. Nothing consumer-side is scraped.

It exists for two reasons:

  - **Freshness.** The pickers hide campaigns missing from the latest catalogue sync,
    which is what keeps a migrated-away account's dead campaigns off the write surfaces.
    Without a refresh the catalogue is only as current as last night's scrape, so a
    campaign created this morning is unpickable and a status shown next to a Start/Stop
    toggle can be up to a day stale.
  - **Truth before a write.** Someone about to start or stop a campaign wants to see what
    Blinkit says right now, not what it said at noon.

This is a READ against Blinkit — there is no dry-run/live distinction and no write
choke-point, because it never mutates anything on the marketplace. Its only side effect
is the local catalogue upsert (`repo.upsert_campaign_catalog`).
"""
import uuid

from campaign_manager import logs, repo
from campaign_manager.marketplaces import get_adapter

# Blinkit's campaign list is scoped to a date window, so the window decides which
# campaigns the catalogue contains — and therefore which ones the pickers offer, since
# they show only campaigns from the most recent sync. A NARROW window is the hazard: it
# refreshes a subset, leaving every campaign it omitted with an older timestamp and out of
# the pickers until something syncs wider. The nightly marketing scrape uses 7 days, so a
# generous default keeps this a superset of it; the floor stops `--days 1` from quietly
# emptying the shelf.
DEFAULT_DAYS = 90
MIN_DAYS = 30


async def run(tenant_id: uuid.UUID, *, days: int = DEFAULT_DAYS,
              platform: str = "blinkit") -> dict:
    """Pull the account's campaigns and upsert them into the shared catalogue."""
    days = max(days, MIN_DAYS)
    run_id = logs.new_run_id()
    # dry_run=False throughout: this run genuinely writes (to our DB, never to Blinkit),
    # so tagging its lines [DRY-RUN] would misrepresent what happened.
    logs.run_start(run_id, "sync_campaigns", tenant_id, dry_run=False, platform=platform)

    adapter = get_adapter(platform)
    pw = browser = None
    try:
        pw, browser, client = await adapter.setup(str(tenant_id))
    except RuntimeError:
        logs.session_expired(run_id, dry_run=False)
        logs.run_summary(run_id, "sync_campaigns", dry_run=False,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}
    logs.session_ok(run_id, dry_run=False)

    try:
        campaigns = await adapter.list_campaigns(client, days=days)
    except Exception as e:
        logs.decision(run_id, dry_run=False, campaign_id=None, verdict="error",
                      reason=f"campaign list failed: {e}")
        campaigns = None
    finally:
        if browser is not None:
            await browser.close()
        if pw is not None:
            await pw.stop()

    # An EMPTY list is an error, not an empty account. Blinkit answers a rejected request
    # with `data: null`, which reads as "no campaigns" — and silently storing that would
    # freeze every campaign's `scraped_at`, hiding the whole account from the pickers.
    # Refusing to write leaves the previous catalogue in place.
    if not campaigns:
        logs.decision(run_id, dry_run=False, campaign_id=None, verdict="error",
                      reason="campaign list came back empty — request rejected or the "
                             "session belongs to a different advertiser; catalogue left as-is")
        logs.run_summary(run_id, "sync_campaigns", dry_run=False,
                         processed=0, applied=0, skipped=0, errors=1)
        return {"processed": 0, "applied": 0, "skipped": 0, "errors": 1}

    written = await repo.upsert_campaign_catalog(tenant_id, campaigns, platform)
    logs.decision(run_id, dry_run=False, campaign_id=None, verdict="synced",
                  reason=f"{written} campaigns in the account catalogue")
    logs.run_summary(run_id, "sync_campaigns", dry_run=False,
                     processed=len(campaigns), applied=written, skipped=0, errors=0)
    return {"processed": len(campaigns), "applied": written, "skipped": 0, "errors": 0}
