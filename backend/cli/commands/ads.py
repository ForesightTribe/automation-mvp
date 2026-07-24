"""CLI commands for ad automation: budget scheduler and bid optimizer."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console

app = typer.Typer(help="Ad automation commands (budget scheduler, bid optimizer).")
console = Console()

_IST = timezone(timedelta(hours=5, minutes=30))


@app.command("budget-scheduler")
def budget_scheduler(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant UUID"),
):
    """Apply budget rules for the current IST time slot (runs as ads.budget_scheduler job)."""
    asyncio.run(_run_budget(tenant_id))


async def _run_budget(tenant_id: str) -> None:
    from ad_campaigns.client import setup
    from ad_campaigns.scheduler import _run_core

    now = datetime.now(_IST)
    pw, browser, client = await setup(tenant_id)
    try:
        await _run_core(client, now)
    finally:
        await browser.close()
        await pw.stop()


@app.command("bid-optimizer")
def bid_optimizer(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant UUID"),
):
    """Run one pass of the bid optimizer (runs as ads.bid_optimizer job)."""
    asyncio.run(_run_optimizer(tenant_id))


async def _run_optimizer(tenant_id: str) -> None:
    from ad_campaigns.bid_optimizer import run as _optimize
    from ad_campaigns.client import setup

    pw, browser, client = await setup(tenant_id)
    try:
        await _optimize(client)
    finally:
        await browser.close()
        await pw.stop()


@app.command("sync-campaign-data")
def sync_campaign_data(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant UUID"),
):
    """Fetch keywords + products for all campaigns and cache in DB. Runs on VM."""
    asyncio.run(_run_sync(tenant_id))


async def _run_sync(tenant_id: str) -> None:
    from ad_campaigns.client import setup
    from app.core.database import AsyncSessionLocal
    from app.models.campaign_manager import CampaignDataCache
    from app.utils.time import now_ist
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    pw, browser, client = await setup(tenant_id)
    try:
        campaigns = await client.get_campaigns(days=90)
        console.print(f"Syncing campaign data for {len(campaigns)} campaigns...")

        for campaign in campaigns:
            campaign_id = campaign.get("campaign_id")
            if not campaign_id:
                continue

            try:
                keywords = await client.get_campaign_keywords(campaign_id)
            except Exception as e:
                console.print(f"[yellow]  keywords failed for {campaign_id}: {e}[/yellow]")
                keywords = []

            try:
                products = await client.get_campaign_products(campaign_id)
            except Exception as e:
                console.print(f"[yellow]  products failed for {campaign_id}: {e}[/yellow]")
                products = []

            async with AsyncSessionLocal() as db:
                stmt = (
                    pg_insert(CampaignDataCache)
                    .values(
                        tenant_id=uuid.UUID(tenant_id),
                        campaign_id=campaign_id,
                        keywords=keywords,
                        products=products,
                        synced_at=now_ist(),
                    )
                    .on_conflict_do_update(
                        index_elements=["tenant_id", "campaign_id"],
                        set_={"keywords": keywords, "products": products, "synced_at": now_ist()},
                    )
                )
                await db.execute(stmt)
                await db.commit()

            console.print(
                f"  [green]✓[/green] campaign {campaign_id}: "
                f"{len(keywords)} keywords, {len(products)} products"
            )

    finally:
        await browser.close()
        await pw.stop()

    console.print("[bold green]Campaign data sync complete.[/bold green]")
