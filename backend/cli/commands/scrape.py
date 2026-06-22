import asyncio
from datetime import date as _date, timedelta
from typing import Optional
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from app.core.database import AsyncSessionLocal
from scraper.utils.session import load_session
from scraper.utils.jobs import create_scrape_job, complete_scrape_job, fail_scrape_job
from scraper.platforms.blinkit.dashboard_data.marketing.scraper import scrape
from scraper.platforms.blinkit.dashboard_data.marketing.parser import (
    parse_performance_summary,
    parse_campaign,
    parse_sponsored_sov,
    parse_brand_collection,
    parse_visibility_plan,
)
from scraper.platforms.blinkit.dashboard_data.marketing.storage import save_scrape_results
from scraper.platforms.blinkit.dashboard_data.seller import scraper as seller_scraper
from scraper.platforms.blinkit.dashboard_data.seller.parser import (
    parse_sale_row,
    parse_sales_summary,
    parse_po_row,
    parse_po_item,
    parse_po_summary,
    parse_soh_row,
    parse_scorecard_weekly,
    parse_scorecard_facility,
    parse_scorecard_key_sku,
)
from scraper.platforms.blinkit.dashboard_data.seller.storage import (
    save_scrape_results as seller_save_results,
    save_po_results,
    save_soh_results,
    save_scorecard_results,
)

app = typer.Typer(help="Run scrapers and view results.")
console = Console()


@app.command("blinkit")
def scrape_blinkit(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape the Blinkit brands dashboard and display results."""
    asyncio.run(_scrape_blinkit(tenant_id, save))


async def _scrape_blinkit(tenant_id: str, save: bool) -> None:
    async with AsyncSessionLocal() as db:
        job_id = None
        try:
            storage_state = await load_session(db, tenant_id, "blinkit")
            if not storage_state:
                console.print("[red]No session found. Run `cli auth blinkit` first.[/red]")
                raise typer.Exit(1)

            job_id = await create_scrape_job(db, tenant_id, "blinkit_marketing")

            with console.status("[cyan]Scraping Blinkit dashboard...[/cyan]"):
                raw = await scrape(storage_state)

            summary = parse_performance_summary(raw["performance_summary"], tenant_id, job_id)
            campaigns = [parse_campaign(c, tenant_id, job_id) for c in raw["campaigns"]]
            sov = [parse_sponsored_sov(s, tenant_id, job_id) for s in raw["sponsored_sov"]]
            collections = [parse_brand_collection(c, tenant_id, job_id) for c in raw["brand_collections"]]
            plans = [parse_visibility_plan(p, tenant_id, job_id) for p in raw["visibility_plans"]]

            if save:
                await save_scrape_results(db, summary, campaigns, sov, collections, plans)
                await complete_scrape_job(db, job_id)

            _print_summary(summary)
            _print_campaigns(campaigns)
            _print_sov(sov)
            _print_collections(collections)
            _print_plans(plans)

        except typer.Exit:
            raise
        except Exception as e:
            if job_id:
                await fail_scrape_job(db, job_id, str(e))
            console.print(f"[red]Scrape failed: {escape(str(e))}[/red]")
            raise typer.Exit(1)


def _print_summary(summary: dict) -> None:
    console.print("\n[bold cyan]Performance Summary[/bold cyan]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Budget Consumed", f"₹{summary['budget_consumed']:,.0f}")
    table.add_row("Impressions", f"{summary['impressions']:,}")
    console.print(table)

    dist = summary.get("budget_distribution", {})
    if dist:
        console.print("\n[bold cyan]Budget Distribution[/bold cyan]")
        dist_table = Table(show_header=True, header_style="bold")
        dist_table.add_column("Campaign Type")
        dist_table.add_column("Budget Consumed", justify="right")
        dist_table.add_column("Share %", justify="right")
        for campaign_type, values in dist.items():
            dist_table.add_row(
                campaign_type,
                f"₹{values['budget_consumed']:,.0f}",
                f"{values['consumed_percentage']}%",
            )
        console.print(dist_table)


def _print_campaigns(campaigns: list) -> None:
    if not campaigns:
        console.print("\n[dim]No campaigns found.[/dim]")
        return
    preview = campaigns[:5]
    console.print(f"\n[bold cyan]Campaigns[/bold cyan] (showing {len(preview)} of {len(campaigns)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Status")
    table.add_column("Budget", justify="right")
    table.add_column("Impressions", justify="right")
    table.add_column("ATCs", justify="right")
    table.add_column("RoAS", justify="right")
    for c in preview:
        status_style = {"ACTIVE": "green", "PAUSED": "yellow", "STOPPED": "red"}.get(c["status"], "")
        status_text = f"[{status_style}]{c['status']}[/{status_style}]" if status_style else c["status"]
        table.add_row(
            c["name"],
            c["type"],
            status_text,
            f"₹{c['budget_consumed']:,.0f}",
            f"{c['impressions']:,}",
            f"{c['atcs']:,}",
            str(c["roas"]),
        )
    console.print(table)


def _print_sov(sov: list) -> None:
    if not sov:
        return
    preview = sov[:5]
    console.print(f"\n[bold cyan]Sponsored Share of Voice[/bold cyan] (showing {len(preview)} of {len(sov)} keywords)")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Keyword")
    table.add_column("Monthly Searches", justify="right")
    table.add_column("SOV %", justify="right")
    for s in preview:
        table.add_row(s["keyword"], f"{s['monthly_searches']:,}", f"{s['sov']}%")
    console.print(table)


def _print_collections(collections: list) -> None:
    if not collections:
        return
    preview = collections[:5]
    console.print(f"\n[bold cyan]Brand Collections[/bold cyan] (showing {len(preview)} of {len(collections)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Products", justify="right")
    table.add_column("Created On")
    for c in preview:
        collection_type = "DYNAMIC" if c["is_dynamic"] else "STATIC"
        table.add_row(c["name"], collection_type, str(c["number_of_products"]), c.get("created_on", ""))
    console.print(table)


def _print_plans(plans: list) -> None:
    if not plans:
        return
    preview = plans[:5]
    console.print(f"\n[bold cyan]Visibility Plans[/bold cyan] (showing {len(preview)} of {len(plans)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Budget", justify="right")
    table.add_column("Start Date")
    table.add_column("End Date")
    table.add_column("Status")
    for p in preview:
        table.add_row(
            p["name"],
            p["type"],
            f"₹{p['budget']:,.0f}",
            (p.get("start_date") or "")[:10],
            (p.get("end_date") or "")[:10],
            p["status"],
        )
    console.print(table)


# ── Blinkit Seller ─────────────────────────────────────────────────────────────

@app.command("blinkit-seller")
def scrape_blinkit_seller(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: yesterday)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: --from)"),
    sales: bool = typer.Option(False, "--sales", help="Scrape sales data"),
    po: bool = typer.Option(False, "--po", help="Scrape PO data"),
    soh: bool = typer.Option(False, "--soh", help="Scrape stock on hand"),
    po_days_back: int = typer.Option(90, "--po-days-back", help="Rolling window for PO fetch"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape Blinkit seller data. Pass --sales, --po, --soh, or none to run all three."""
    asyncio.run(_scrape_blinkit_seller(tenant_id, date_from, date_to, sales, po, soh, po_days_back, save))


def _date_range(date_from: str | None, date_to: str | None) -> list[str]:
    yesterday = (_date.today() - timedelta(days=1)).isoformat()
    start = _date.fromisoformat(date_from or yesterday)
    end = _date.fromisoformat(date_to or yesterday)
    days = (end - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


async def _scrape_blinkit_seller(
    tenant_id: str,
    date_from: str | None,
    date_to: str | None,
    sales_flag: bool,
    po_flag: bool,
    soh_flag: bool,
    po_days_back: int,
    save: bool,
) -> None:
    run_all = not sales_flag and not po_flag and not soh_flag
    run_sales = sales_flag or run_all
    run_po = po_flag or run_all
    run_soh = soh_flag or run_all

    async with AsyncSessionLocal() as db:
        storage_state = await load_session(db, tenant_id, "blinkit_seller")
        if not storage_state:
            console.print("[red]No session found. Run `cli auth blinkit-seller` first.[/red]")
            raise typer.Exit(1)

        # ── Sales (loops per day) ──────────────────────────────────────────────
        if run_sales:
            days = _date_range(date_from, date_to)
            for day in days:
                job_id = None
                try:
                    job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_sales")

                    with console.status(f"[cyan]Scraping sales {day}...[/cyan]"):
                        raw = await seller_scraper.scrape(storage_state, day)

                    parsed_sales = [parse_sale_row(r, tenant_id, job_id, raw["date"]) for r in raw["sales"]]
                    summary = parse_sales_summary(raw, tenant_id, job_id, raw["date"])

                    if save:
                        await seller_save_results(db, parsed_sales, summary)
                        await complete_scrape_job(db, job_id)

                    _print_seller_summary(summary, len(parsed_sales))
                    _print_seller_sales(parsed_sales)

                except Exception as e:
                    if job_id:
                        await fail_scrape_job(db, job_id, str(e))
                    console.print(f"[red]{day} failed: {escape(str(e))}[/red]")
                    if len(days) == 1:
                        raise typer.Exit(1)

        # ── PO (runs once) ────────────────────────────────────────────────────
        if run_po:
            po_job_id = None
            try:
                known_po_numbers: set[str] = set()
                if save:
                    import uuid as _uuid
                    from sqlmodel import select as _select
                    from app.models.blinkit_seller import BlinkitPO as _BlinkitPO
                    from sqlalchemy import distinct as _distinct
                    rows = await db.execute(
                        _select(_distinct(_BlinkitPO.po_number)).where(
                            _BlinkitPO.tenant_id == _uuid.UUID(tenant_id)
                        )
                    )
                    known_po_numbers = set(rows.scalars().all())
                    console.print(
                        f"\n[dim]{len(known_po_numbers)} existing POs in DB — skipping their SKU fetch[/dim]"
                    )

                po_job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_po")

                with console.status("[cyan]Scraping PO data...[/cyan]"):
                    raw_po = await seller_scraper.scrape_po(
                        storage_state,
                        po_days_back=po_days_back,
                        known_po_numbers=known_po_numbers,
                    )

                pos = [parse_po_row(r, tenant_id, po_job_id) for r in raw_po["pos"]]
                po_items = [
                    parse_po_item(it, r["po_number"], tenant_id, po_job_id)
                    for r in raw_po["pos"]
                    for it in r.get("items", [])
                ]
                snapshot = parse_po_summary(
                    raw_po["po_summary"], tenant_id, po_job_id, raw_po["po_window_start"]
                )

                if save:
                    await save_po_results(db, pos, po_items, snapshot)
                    await complete_scrape_job(db, po_job_id)

                _print_po_snapshot(snapshot, len(pos))
                _print_po_list(pos)

            except Exception as e:
                if po_job_id:
                    await fail_scrape_job(db, po_job_id, str(e))
                console.print(f"[red]PO scrape failed: {escape(str(e))}[/red]")
                raise typer.Exit(1)

        # ── SOH (runs once) ───────────────────────────────────────────────────
        if run_soh:
            soh_job_id = None
            try:
                soh_job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_soh")

                with console.status("[cyan]Scraping stock on hand...[/cyan]"):
                    raw_soh = await seller_scraper.scrape_soh(storage_state)

                rows = [parse_soh_row(r, tenant_id, soh_job_id, raw_soh["date"]) for r in raw_soh["rows"]]

                if save:
                    await save_soh_results(db, rows)
                    await complete_scrape_job(db, soh_job_id)

                _print_soh(rows, raw_soh["date"])

            except Exception as e:
                if soh_job_id:
                    await fail_scrape_job(db, soh_job_id, str(e))
                console.print(f"[red]SOH scrape failed: {escape(str(e))}[/red]")
                raise typer.Exit(1)


# ── Print helpers ─────────────────────────────────────────────────────────────

def _print_seller_summary(summary: dict, total_rows: int) -> None:
    console.print(f"\n[bold cyan]Sales Summary[/bold cyan] ({summary['date']})")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Total Rows", str(total_rows))
    table.add_row("Distinct SKUs", str(summary["distinct_skus"]))
    table.add_row("Distinct Categories", str(summary["distinct_categories"]))
    table.add_row("Max Selling Item", summary["max_sell_item"])
    console.print(table)


def _print_seller_sales(sales: list) -> None:
    if not sales:
        console.print("\n[dim]No sales data found.[/dim]")
        return
    preview = sales[:5]
    console.print(f"\n[bold cyan]Sales[/bold cyan] (showing {len(preview)} of {len(sales)} rows)")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Item")
    table.add_column("Category", style="dim")
    table.add_column("City")
    table.add_column("Qty Sold", justify="right")
    table.add_column("MRP Value", justify="right")
    for r in preview:
        table.add_row(
            r["item_name"],
            r["category"],
            r["city_name"],
            str(r["qty_sold"]),
            f"₹{r['mrp_value']:,.0f}",
        )
    console.print(table)


def _print_po_snapshot(snapshot: dict, total_rows: int) -> None:
    console.print(f"\n[bold cyan]PO Summary[/bold cyan] (window: {snapshot['window_start']} → today)")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Total POs fetched", str(total_rows))
    table.add_row("Total Raised", str(snapshot.get("total_raised", 0)))
    table.add_row("Scheduled", str(snapshot.get("scheduled", 0)))
    table.add_row("Created (unscheduled)", str(snapshot.get("created", 0)))
    table.add_row("Cancelled", str(snapshot.get("cancelled", 0)))
    table.add_row("Expired (unfulfilled)", str(snapshot.get("expired_unfulfilled", 0)))
    table.add_row("Expired (partial GRN)", str(snapshot.get("expired_partial", 0)))
    table.add_row("PO Amount", f"₹{snapshot.get('po_amount', 0):,.0f}")
    table.add_row("Items Delivered", f"{snapshot.get('items_delivered', 0):,}")
    console.print(table)


def _print_po_list(pos: list) -> None:
    if not pos:
        console.print("\n[dim]No PO data found.[/dim]")
        return
    preview = pos[:5]
    console.print(f"\n[bold cyan]POs[/bold cyan] (showing {len(preview)} of {len(pos)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("PO Number")
    table.add_column("State")
    table.add_column("City")
    table.add_column("Facility", style="dim")
    table.add_column("Units", justify="right")
    table.add_column("Amount", justify="right")
    table.add_column("SKUs", justify="right")
    for po in preview:
        state = po.get("po_state", "")
        state_colour = {
            "Fulfilled": "green", "Delivered": "green",
            "Scheduled": "cyan", "Rescheduled": "cyan",
            "Unscheduled": "yellow", "Created": "yellow",
            "Expired": "red", "Cancelled": "red",
            "Cancelled post Creation": "red",
        }.get(state, "")
        state_str = f"[{state_colour}]{state}[/{state_colour}]" if state_colour else state
        table.add_row(
            po.get("po_number", ""),
            state_str,
            po.get("city_name", ""),
            po.get("facility_name", ""),
            str(po.get("total_units_ordered", 0)),
            f"₹{po.get('total_po_amount', 0):,.0f}",
            str(po.get("item_count") or 0),
        )
    console.print(table)


# ── Blinkit Scorecard ──────────────────────────────────────────────────────────

@app.command("blinkit-scorecard")
def scrape_blinkit_scorecard(
    tenant_id: str = typer.Option(..., "--tenant", "-t", help="Tenant ID"),
    week: str = typer.Option(None, "--week", help="Week start date YYYY-MM-DD (must be a Monday, default: last Monday)"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape Blinkit scorecard (fill rates). Data refreshes every Monday."""
    asyncio.run(_scrape_blinkit_scorecard(tenant_id, week, save))


async def _scrape_blinkit_scorecard(tenant_id: str, week: str | None, save: bool) -> None:
    async with AsyncSessionLocal() as db:
        job_id = None
        try:
            storage_state = await load_session(db, tenant_id, "blinkit_seller")
            if not storage_state:
                console.print("[red]No session found. Run `cli auth blinkit-seller` first.[/red]")
                raise typer.Exit(1)

            job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_scorecard")

            with console.status("[cyan]Scraping scorecard...[/cyan]"):
                raw = await seller_scraper.scrape_scorecard(storage_state, week=week)

            manufacturer_id = raw["manufacturer_id"]
            from_date = raw["from_date_ist"]

            weekly = parse_scorecard_weekly(raw, tenant_id, job_id)
            facilities = [
                parse_scorecard_facility(f, tenant_id, job_id, manufacturer_id, from_date)
                for f in raw["facilities"]
            ]
            key_skus = [
                parse_scorecard_key_sku(s, tenant_id, job_id, manufacturer_id, from_date)
                for s in raw["key_skus"]
            ]

            if save:
                await save_scorecard_results(db, weekly, facilities, key_skus)
                await complete_scrape_job(db, job_id)

            _print_scorecard_summary(weekly)
            _print_scorecard_facilities(facilities)
            _print_scorecard_key_skus(key_skus)

        except typer.Exit:
            raise
        except Exception as e:
            if job_id:
                await fail_scrape_job(db, job_id, str(e))
            console.print(f"[red]Scrape failed: {escape(str(e))}[/red]")
            raise typer.Exit(1)


def _print_scorecard_summary(weekly: dict) -> None:
    overall = weekly.get("overall", {})
    best_cat = weekly.get("best_category") or {}
    console.print(f"\n[bold cyan]Scorecard Summary[/bold cyan] (week of {weekly['from_date_ist']})")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Fill Rate", f"{overall.get('fill_rate', 0):.2f}%")
    table.add_row("Weighted Fill Rate", f"{overall.get('weighted_fill_rate_percent', 0):.2f}%")
    table.add_row("PO Quantity", f"{overall.get('total_po_quantity', 0):,}")
    table.add_row("GRN Quantity", f"{overall.get('total_grn_quantity', 0):,}")
    table.add_row("Potential Loss", f"₹{overall.get('potential_loss', 0):,}")
    table.add_row("Total GMV", f"₹{overall.get('total_gmv', 0):,.0f}")
    table.add_row("Overall Rank", str(overall.get("manufacturer_rank", "—")))
    if best_cat:
        table.add_row(
            f"Best Category ({best_cat.get('proxy_category', '')})",
            f"Rank #{best_cat.get('manufacturer_rank', '—')} | {best_cat.get('fill_rate', 0):.2f}%",
        )
    console.print(table)


def _print_scorecard_facilities(facilities: list) -> None:
    if not facilities:
        return
    console.print(f"\n[bold cyan]Facilities[/bold cyan] ({len(facilities)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Facility")
    table.add_column("City", style="dim")
    table.add_column("Fill Rate", justify="right")
    table.add_column("PO Qty", justify="right")
    table.add_column("GRN Qty", justify="right")
    table.add_column("Potential Loss", justify="right")
    table.add_column("Rank", justify="right")
    for f in sorted(facilities, key=lambda x: x.get("fill_rate", 0)):
        fill = f.get("fill_rate", 0)
        colour = "green" if fill >= 90 else ("yellow" if fill >= 70 else "red")
        table.add_row(
            f["facility_name"],
            f.get("city_name", ""),
            f"[{colour}]{fill:.0f}%[/{colour}]",
            f"{f.get('total_po_quantity', 0):,}",
            f"{f.get('total_grn_quantity', 0):,}",
            f"₹{f.get('potential_loss', 0):,}",
            str(f.get("manufacturer_rank", "—")),
        )
    console.print(table)


def _print_scorecard_key_skus(key_skus: list) -> None:
    if not key_skus:
        return
    console.print(f"\n[bold cyan]Key SKUs by Potential Loss[/bold cyan] ({len(key_skus)})")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Item")
    table.add_column("Variant", style="dim")
    table.add_column("Category", style="dim")
    table.add_column("Potential Loss", justify="right")
    for s in sorted(key_skus, key=lambda x: x.get("potential_loss", 0), reverse=True):
        table.add_row(
            s.get("item_name", ""),
            s.get("variant_description", ""),
            s.get("proxy_category", ""),
            f"₹{s.get('potential_loss', 0):,.0f}",
        )
    console.print(table)


# ── Public search scraping ────────────────────────────────────────────────────

@app.command("public")
def scrape_public(
    keyword: str = typer.Option(..., "--keyword", "-k", help="Search keyword (e.g. 'cola', 'sunflower oil')"),
    brand: str = typer.Option(..., "--brand", "-b", help="Brand slug for classification (e.g. 'dobra')"),
    city: str = typer.Option("bengaluru", "--city", "-c", help="City slug (see scraper/utils/cities.py)"),
    platform: str = typer.Option("all", "--platform", "-p", help="Platform: blinkit | zepto | instamart | all"),
    all_zones: bool = typer.Option(False, "--all-zones", help="Scrape all zones defined for the city"),
    aliases: Optional[str] = typer.Option(None, "--aliases", help="Comma-separated brand name aliases (e.g. 'dobra,dobra cola')"),
    save: bool = typer.Option(False, "--save/--no-save", help="Save results to PostgreSQL"),
):
    """Scrape public product search results — no login required."""
    alias_list = [a.strip() for a in aliases.split(",")] if aliases else None
    asyncio.run(_scrape_public(keyword, brand, city, platform, all_zones, alias_list, save))


async def _scrape_public(
    keyword: str,
    brand_slug: str,
    city_slug: str,
    platform: str,
    all_zones: bool,
    aliases: list[str] | None,
    save: bool,
) -> None:
    from scraper.utils.cities import CITIES, PLATFORM_CITIES
    from scraper.platforms.blinkit.public_data import scraper as bl_scraper, parser as bl_parser, storage as bl_storage
    from scraper.platforms.instamart.public_data import scraper as im_scraper, parser as im_parser, storage as im_storage
    from scraper.platforms.zepto.public_data import scraper as ze_scraper, parser as ze_parser, storage as ze_storage

    city = CITIES.get(city_slug)
    if not city:
        console.print(f"[red]Unknown city slug '{city_slug}'. Check scraper/utils/cities.py for valid slugs.[/red]")
        raise typer.Exit(1)

    platforms_to_run = (
        [p for p in ["blinkit", "zepto", "instamart"] if p in city["platforms"]]
        if platform == "all"
        else [platform]
    )
    invalid = [p for p in platforms_to_run if p not in {"blinkit", "zepto", "instamart"}]
    if invalid:
        console.print(f"[red]Unknown platform(s): {', '.join(invalid)}[/red]")
        raise typer.Exit(1)

    scrapers = {
        "blinkit":   (bl_scraper, bl_parser, bl_storage),
        "instamart": (im_scraper, im_parser, im_storage),
        "zepto":     (ze_scraper, ze_parser, ze_storage),
    }

    async with AsyncSessionLocal() as db:
        for plat in platforms_to_run:
            if plat not in city["platforms"]:
                console.print(f"  [dim]{plat} not available in {city['name']}[/dim]")
                continue

            plat_zones = city["platforms"][plat]["zones"] if all_zones else [
                {"zone": "", "pincode": city["pincode"], "lat": city["lat"], "lon": city["lon"]}
            ]

            scraper_mod, parser_mod, storage_mod = scrapers[plat]

            for zone_def in plat_zones:
                zone_label = zone_def.get("zone", "")
                zone_display = f" [{zone_label}]" if zone_label else ""
                console.print(f"\n[bold cyan]{city['name']}{zone_display}[/bold cyan]  [dim]{plat}[/dim]")

                with console.status(f"  [cyan]Scraping {plat}…[/cyan]"):
                    raw = await scraper_mod.scrape(
                        keyword=keyword,
                        brand_slug=brand_slug,
                        city_slug=city_slug,
                        zone=zone_label,
                        pincode=zone_def.get("pincode", city["pincode"]),
                        lat=zone_def.get("lat"),
                        lon=zone_def.get("lon"),
                        aliases=aliases,
                    )
                result = parser_mod.parse(raw)
                _print_public_result(plat, result)

                if save:
                    await storage_mod.save(db, result)


def _print_public_result(platform: str, result: dict) -> None:
    sov = result.get("brand_sov_pct", 0)
    rank = result.get("brand_rank")
    total = result.get("total_results", 0)
    brand_count = result.get("brand_product_count", 0)

    rank_str = f"#{rank}" if rank else "not ranked"
    colour = "green" if sov >= 20 else ("yellow" if sov >= 5 else "red")

    console.print(
        f"  [bold]{platform}[/bold]  "
        f"total={total}  brand={brand_count}  "
        f"rank={rank_str}  sov=[{colour}]{sov}%[/{colour}]"
    )

    brand_prods = result.get("brand_products", [])
    if brand_prods:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("#", style="dim", width=4)
        table.add_column("Product")
        table.add_column("Price", justify="right")
        for p in brand_prods:
            price_str = f"₹{p['price']:.0f}" if p.get("price") else "—"
            table.add_row(str(p.get("position", "")), p.get("name", ""), price_str)
        console.print(table)

    comps = result.get("competitors", [])[:3]
    if comps:
        comp_names = ", ".join(f"{c['name']} ({c['count_in_results']})" for c in comps)
        console.print(f"  [dim]Top competitors: {comp_names}[/dim]")


def _print_soh(rows: list, date: str) -> None:
    console.print(f"\n[bold cyan]Stock on Hand[/bold cyan] ({date}) — {len(rows)} rows")
    if not rows:
        console.print("\n[dim]No SOH data found.[/dim]")
        return

    preview = rows[:10]
    table = Table(show_header=True, header_style="bold")
    table.add_column("Item")
    table.add_column("Facility", style="dim")
    table.add_column("Backend Qty", justify="right")
    table.add_column("Frontend Qty", justify="right")
    for r in preview:
        backend = r.get("backend_inv_qty", 0)
        frontend = r.get("frontend_inv_qty", 0)
        backend_str = f"[red]{backend}[/red]" if backend == 0 else str(backend)
        frontend_str = f"[red]{frontend}[/red]" if frontend == 0 else str(frontend)
        table.add_row(
            r.get("item_name", ""),
            r.get("backend_facility_name", ""),
            backend_str,
            frontend_str,
        )
    console.print(table)
    if len(rows) > 10:
        console.print(f"[dim]... and {len(rows) - 10} more rows[/dim]")
