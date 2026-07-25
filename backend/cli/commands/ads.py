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

    pw, browser, client = await setup(tenant_id)
    try:
        now = datetime.now(_IST)  # capture AFTER browser setup so time is fresh
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
    from datetime import timedelta
    from ad_campaigns.client import setup
    from app.core.database import AsyncSessionLocal
    from app.models.blinkit_marketing import BlinkitAdCampaign
    from app.models.campaign_manager import CampaignDataCache
    from app.utils.time import now_ist
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlmodel import select

    # Get campaign IDs from DB (recently scraped) instead of Blinkit API
    async with AsyncSessionLocal() as db:
        latest_scraped = (await db.execute(
            select(func.max(BlinkitAdCampaign.scraped_at))
            .where(BlinkitAdCampaign.tenant_id == uuid.UUID(tenant_id))
        )).scalar()

        if not latest_scraped:
            console.print("[yellow]No campaigns found in DB. Run the campaign scraper first.[/yellow]")
            return

        rows = (await db.execute(
            select(BlinkitAdCampaign.campaign_id, BlinkitAdCampaign.name)
            .where(
                BlinkitAdCampaign.tenant_id == uuid.UUID(tenant_id),
                BlinkitAdCampaign.scraped_at >= latest_scraped - timedelta(hours=2),
            )
        )).all()

    campaigns = [{"campaign_id": r[0], "name": r[1]} for r in rows]
    console.print(f"Syncing campaign data for {len(campaigns)} campaigns...")

    pw, browser, client = await setup(tenant_id)
    try:
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
