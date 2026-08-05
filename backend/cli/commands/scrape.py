import asyncio
from datetime import date as _date, timedelta
from typing import Optional
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from app.core.database import AsyncSessionLocal
from platform_auth import service as auth_service
from platform_auth.errors import AuthError
from scraper.utils.jobs import create_scrape_job, complete_scrape_job, fail_scrape_job
from scraper.platforms.blinkit.dashboard_data.marketing.scraper import scrape
from scraper.platforms.blinkit.dashboard_data.marketing.parser import (
    parse_campaign,
    parse_campaign_daily,
    parse_campaign_detail,
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
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: 7 days ago)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD (default: today)"),
    limit: int = typer.Option(None, "--limit", help="Test mode: only the N most-active campaigns"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to PostgreSQL"),
):
    """Scrape the Blinkit marketing dashboard for a date window.

    One pass fetches the campaign list, each campaign's daily metric series + its
    keyword/recommendation breakdown, plus SOV / collections / plans. Use --from
    to backfill (e.g. --from 30 days ago); the daily run defaults to the last week
    so late metric revisions are picked up. Use --limit to smoke-test a few
    campaigns without the full-volume run.
    """
    asyncio.run(_scrape_blinkit(tenant_id, date_from, date_to, limit, save))


async def _scrape_blinkit(
    tenant_id: str, date_from: str | None, date_to: str | None, limit: int | None, save: bool
) -> None:
    start = _date.fromisoformat(date_from) if date_from else _date.today() - timedelta(days=7)
    end = _date.fromisoformat(date_to) if date_to else _date.today()
    snapshot_date = end.isoformat()

    async with AsyncSessionLocal() as db:
        job_id = None
        try:
            # ensure() = load → probe → refresh → re-login, doing the least work
            # that yields a session known to work. Replaces a bare load, which
            # happily returned a session that had died days earlier and let the
            # scrape fail deep inside Playwright instead.
            storage_state = (await auth_service.ensure(db, tenant_id, "blinkit")).storage_state

            job_id = await create_scrape_job(db, tenant_id, "blinkit_marketing")

            with console.status(f"[cyan]Scraping Blinkit marketing {start}→{end}...[/cyan]"):
                raw = await scrape(storage_state, start, end, limit=limit)

            campaigns = [parse_campaign(c, tenant_id, job_id) for c in raw["campaigns"]]
            type_by_id = {c["id"]: c.get("campaign_type") for c in raw["campaigns"]}

            daily = [
                parse_campaign_daily(row, cid, type_by_id.get(cid), tenant_id, job_id)
                for cid, rows in raw["daily"].items()
                for row in rows
            ]
            detail = [
                d
                for cid, report in raw["detail"].items()
                for d in parse_campaign_detail(
                    report, cid, type_by_id.get(cid), snapshot_date, tenant_id, job_id
                )
            ]
            sov = [
                parse_sponsored_sov(s, tenant_id, job_id, snapshot_date)
                for s in raw["sponsored_sov"]
            ]
            collections = [parse_brand_collection(c, tenant_id, job_id) for c in raw["brand_collections"]]
            plans = [parse_visibility_plan(p, tenant_id, job_id) for p in raw["visibility_plans"]]

            if save:
                await save_scrape_results(db, campaigns, daily, detail, sov, collections, plans)
                await complete_scrape_job(db, job_id)

            console.print(
                f"\n[bold cyan]Blinkit marketing[/bold cyan] ({start}→{end})\n"
                f"  campaigns: {len(campaigns)}\n"
                f"  daily rows: {len(daily)}\n"
                f"  detail rows: {len(detail)}\n"
                f"  sov: {len(sov)}  collections: {len(collections)}  plans: {len(plans)}"
            )
            _print_campaigns(campaigns)
            _print_daily(daily)
            _print_detail(detail)
            _print_sov(sov)
            _print_collections(collections)
            _print_plans(plans)

        except typer.Exit:
            raise
        except AuthError:
            # Must escape the generic handler below. cli/main.py turns AuthError
            # into exit code 3, which the job runner records as `auth_expired` —
            # collapsing it into typer.Exit(1) here would bury every auth failure
            # among anonymous exit_1s, which is exactly how the seller breakage
            # went unnoticed for weeks.
            if job_id:
                await fail_scrape_job(db, job_id, "auth_expired")
            raise
        except Exception as e:
            # For DB errors, e.orig is the short asyncpg message; str(e) would dump
            # the entire (huge) statement + params, flooding the terminal.
            err = getattr(e, "orig", None) or e
            if job_id:
                await fail_scrape_job(db, job_id, str(err))
            console.print(f"[red]Scrape failed: {escape(str(err))}[/red]")
            raise typer.Exit(1)


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
    for c in preview:
        status_style = {"ACTIVE": "green", "PAUSED": "yellow", "STOPPED": "red"}.get(c["status"], "")
        status_text = f"[{status_style}]{c['status']}[/{status_style}]" if status_style else c["status"]
        table.add_row(c["name"], c["type"], status_text)
    console.print(table)


def _print_daily(rows: list) -> None:
    if not rows:
        console.print("\n[dim]No daily rows captured.[/dim]")
        return
    preview = rows[:15]
    console.print(f"\n[bold cyan]Campaign Daily[/bold cyan] (showing {len(preview)} of {len(rows)} rows)")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Campaign", style="dim")
    table.add_column("Date")
    table.add_column("Budget", justify="right")
    table.add_column("Impr", justify="right")
    table.add_column("ATC", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Ad Sales", justify="right")
    table.add_column("RoAS", justify="right")
    for r in preview:
        table.add_row(
            str(r["campaign_id"]),
            str(r["date"]),
            f"₹{r['budget_consumed']:,.0f}",
            f"{r['impressions']:,}",
            f"{r['atc']:,}",
            f"{r['quantities_sold']:,}",
            f"₹{r['ad_sales']:,.0f}",
            f"{r['roas']}",
        )
    console.print(table)


def _print_detail(rows: list) -> None:
    if not rows:
        console.print("\n[dim]No detail rows captured.[/dim]")
        return
    preview = rows[:15]
    console.print(f"\n[bold cyan]Campaign Detail[/bold cyan] (showing {len(preview)} of {len(rows)} rows)")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Campaign", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Target")
    table.add_column("Impr", justify="right")
    table.add_column("Budget", justify="right")
    table.add_column("Direct RoAS", justify="right")
    table.add_column("Total RoAS", justify="right")
    for r in preview:
        table.add_row(
            str(r["campaign_id"]),
            r["target_type"],
            r["target"],
            f"{r['impressions']:,}",
            f"₹{r['budget_consumed']:,.0f}",
            f"{r['direct_roas']}",
            f"{r['total_roas']}",
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
    refetch_po_items: bool = typer.Option(
        False, "--refetch-po-items",
        help="Re-fetch line items for every PO in the window (one-time backfill of stale received qty)",
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Save results to MongoDB"),
):
    """Scrape Blinkit seller data. Pass --sales, --po, --soh, or none to run all three."""
    asyncio.run(_scrape_blinkit_seller(tenant_id, date_from, date_to, sales, po, soh, po_days_back, refetch_po_items, save))


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
    refetch_po_items: bool,
    save: bool,
) -> None:
    run_all = not sales_flag and not po_flag and not soh_flag
    run_sales = sales_flag or run_all
    run_po = po_flag or run_all
    run_soh = soh_flag or run_all

    async with AsyncSessionLocal() as db:
        storage_state = (
            await auth_service.ensure(db, tenant_id, "blinkit_seller")
        ).storage_state

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
                # po_number -> (po_state, total_grn_quantity) for the targeted
                # item refetch: a changed GRN or non-terminal state means the
                # line items may have moved and must be re-pulled.
                known_pos: dict[str, tuple[str | None, int | None]] = {}
                if save:
                    import uuid as _uuid
                    from sqlmodel import select as _select
                    from app.models.blinkit_seller import BlinkitPO as _BlinkitPO
                    rows = await db.execute(
                        _select(
                            _BlinkitPO.po_number,
                            _BlinkitPO.po_state,
                            _BlinkitPO.total_grn_quantity,
                        ).where(_BlinkitPO.tenant_id == _uuid.UUID(tenant_id))
                    )
                    known_pos = {pn: (state, grn) for pn, state, grn in rows.all()}
                    detail = (
                        "re-fetching ALL their line items"
                        if refetch_po_items
                        else "re-fetching only changed/in-flight ones"
                    )
                    console.print(
                        f"\n[dim]{len(known_pos)} existing POs in DB — {detail}[/dim]"
                    )

                po_job_id = await create_scrape_job(db, tenant_id, "blinkit_seller_po")

                with console.status("[cyan]Scraping PO data...[/cyan]"):
                    raw_po = await seller_scraper.scrape_po(
                        storage_state,
                        po_days_back=po_days_back,
                        known_pos=known_pos,
                        refetch_all_items=refetch_po_items,
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
            storage_state = (
                await auth_service.ensure(db, tenant_id, "blinkit_seller")
            ).storage_state

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
        except AuthError:
            # See the note in _scrape_blinkit — must not collapse into exit 1.
            if job_id:
                await fail_scrape_job(db, job_id, "auth_expired")
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
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — required to --save (per-tenant storage)"),
    save: bool = typer.Option(False, "--save/--no-save", help="Save results to PostgreSQL (requires --tenant)"),
):
    """Scrape public product search results — no login required.

    Without --save it just scrapes and prints (no tenant needed). With --save it
    writes per-tenant header+detail rows (search_snapshots + search_listings) and
    opens a scrape_job, so --tenant is required.
    """
    alias_list = [a.strip() for a in aliases.split(",")] if aliases else None
    asyncio.run(_scrape_public(keyword, brand, city, platform, all_zones, alias_list, tenant_id, save))


async def _scrape_public(
    keyword: str,
    brand_slug: str,
    city_slug: str,
    platform: str,
    all_zones: bool,
    aliases: list[str] | None,
    tenant_id: str | None,
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

    if save and not tenant_id:
        console.print("[red]--tenant is required with --save (storage is per-tenant).[/red]")
        raise typer.Exit(1)

    async with AsyncSessionLocal() as db:
        job_id = None
        rows_written = 0
        if save:
            job_id = await create_scrape_job(db, tenant_id, "public_search", "blinkit")

        try:
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
                        rows_written += await storage_mod.save(db, result, tenant_id, job_id)

            if save:
                await complete_scrape_job(db, job_id, rows_written)
                console.print(f"\n[green]Saved {rows_written} rows[/green] (job {job_id})")
        except Exception as e:
            if save and job_id:
                await fail_scrape_job(db, job_id, str(e))
            raise


def _validate_marketplace(mp: str) -> str:
    """Normalise + check a --marketplace value against the wired providers.

    Fails fast rather than falling back: a typo'd marketplace silently scraping
    Blinkit would write real rows under the wrong platform.
    """
    from scraper.public import providers

    slug = (mp or "").strip().lower()
    try:
        providers.get_provider(slug)
    except ValueError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)
    return slug


@app.command("public-run")
def public_run(
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — omit with --all"),
    all_tenants: bool = typer.Option(False, "--all", help="Run every active tenant"),
    marketplace: str = typer.Option("blinkit", "--marketplace", "-m", help="Marketplace to scrape (blinkit)"),
    cap: int = typer.Option(None, "--cap", help="Max products per search (default: tenant keyword_cap, else the platform floor)"),
    keyword: str = typer.Option(None, "--keyword", "-k", help="Only this keyword (subset of the watchlist)"),
    city: str = typer.Option(None, "--city", "-c", help="Only locations in this city slug"),
    resume: bool = typer.Option(False, "--resume", help="Continue this tenant's last incomplete run on this marketplace (skip already-scraped stores)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Concurrent browser workers (pool size). ~5–6 is a good balance."),
    no_load: bool = typer.Option(False, "--no-load", help="Stage only; don't push to the database afterwards"),
):
    """Orchestrate a tenant's full watchlist (keywords × locations), all sourced
    from the DB (watchlist + tenant_locations). Writes per-tenant snapshot+listing
    rows under one scrape_job per tenant. --marketplace selects the platform (its
    locations, its engine). --keyword/--city narrow a run to a single keyword or
    city. --resume picks up an interrupted run. --workers sets the concurrent
    browser pool size.
    """
    if not tenant_id and not all_tenants:
        console.print("[red]Provide --tenant <id> or --all.[/red]")
        raise typer.Exit(1)
    if resume and all_tenants:
        console.print("[red]--resume works with a single --tenant, not --all.[/red]")
        raise typer.Exit(1)
    mp = _validate_marketplace(marketplace)
    asyncio.run(_public_run(tenant_id, all_tenants, cap, keyword, city, resume, workers, no_load, mp))


async def _auto_load(summary: dict, no_load: bool) -> None:
    """Push one finished scrape's staging file into Postgres, inline.

    Called right after each tenant's scrape (including inside a --all sweep, via the
    orchestrator's on_tenant_done hook) so a later tenant failing can never strand an
    earlier tenant's data. Deliberately NON-FATAL: the rows are already safe on disk,
    so a load failure leaves the file pending and prints the recovery command rather
    than failing the run.

    Only clean runs auto-load. A crashed/partial run still holds real data, but
    sweeping it in unnoticed is the accident worth avoiding — same rule
    `scrape load --all` follows. See docs/staging.md.
    """
    if no_load:
        return
    name = summary.get("staging_file")
    if not name:
        return
    if summary.get("status") != "success":
        console.print(
            f"[yellow]Not auto-loading {name} — the run didn't finish cleanly.[/yellow] "
            f"Review with [bold]cli scrape staged[/bold], then load or discard it."
        )
        return

    from scraper.public import loader, staging

    try:
        path = staging.resolve(name)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Auto-load skipped:[/red] {escape(str(e))}")
        return

    console.print(f"[dim]Loading {name} into the database…[/dim]")
    try:
        res = await loader.load_with_retry(path)
    except Exception as e:
        err = getattr(e, "orig", None) or e
        console.print(f"[red]Auto-load FAILED:[/red] {escape(str(err))[:300]}")
        console.print(
            f"[dim]Nothing was written; the scrape is safe on disk. Retry with "
            f"[/dim][bold]python -m cli scrape load --file {staging.ref(path)}[/bold]"
        )
        return
    console.print(
        f"[green]Loaded[/green] {res['total']:,} rows "
        f"({res['snapshots']:,} snapshots, {res['listings']:,} listings, "
        f"{res['skus']:,} sku rows)"
    )


async def _public_run(
    tenant_id: str | None, all_tenants: bool, cap: int | None,
    keyword: str | None, city: str | None, resume: bool, workers: int,
    no_load: bool = False, mp_slug: str = "blinkit",
) -> None:
    from scraper.public import orchestrator

    async def _after(summary: dict) -> None:
        await _auto_load(summary, no_load)

    async with AsyncSessionLocal() as db:
        if all_tenants:
            # Load each tenant the moment its scrape finishes, not at the end of the
            # sweep — on a weekly scheduled run, tenant 7 failing must not strand the
            # six already scraped.
            summaries = await orchestrator.run_all(
                db, cap, keyword, city, workers, on_tenant_done=_after, mp_slug=mp_slug
            )
        else:
            summaries = [await orchestrator.run_tenant(
                db, tenant_id, cap, keyword, city, resume, workers, mp_slug=mp_slug
            )]
            await _after(summaries[0])

    if not summaries:
        console.print("[yellow]No active tenants to run.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tenant")
    table.add_column("MP")
    table.add_column("Keywords", justify="right")
    table.add_column("Locations", justify="right")
    table.add_column("Snapshots", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Errors", justify="right")
    for s in summaries:
        table.add_row(
            s["tenant_id"][:8], s.get("mp_slug", mp_slug),
            str(s["keywords"]), str(s["locations"]),
            str(s["snapshots"]), str(s["rows"]), str(s.get("skipped", 0)),
            f"[red]{s['errors']}[/red]" if s["errors"] else "0",
        )
    console.print(table)


@app.command("public-skus")
def public_skus(
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Tenant (client) UUID — omit with --all"),
    all_tenants: bool = typer.Option(False, "--all", help="Run every active tenant"),
    marketplace: str = typer.Option("blinkit", "--marketplace", "-m", help="Marketplace to scrape (blinkit)"),
    cap: int = typer.Option(None, "--brand-cap", help="Override brand_cap for this run (default: per-tenant, else the platform floor)"),
    city: str = typer.Option(None, "--city", "-c", help="Only locations in this city slug"),
    resume: bool = typer.Option(False, "--resume", help="Continue this tenant's last incomplete run on this marketplace (skip scraped stores)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Concurrent browser workers (pool size)."),
    no_load: bool = typer.Option(False, "--no-load", help="Stage only; don't push to the database afterwards"),
):
    """Targeted own-SKU scrape: search each tenant's brand name, paginate its whole
    catalog, and write per-product rows to sku_snapshots (price/mrp/discount/stock/
    inventory/rating), keyed on product_id. Complements `public-run` (which covers
    SoV/rank + competitors). --marketplace selects the platform. --resume picks up
    an interrupted run.
    """
    if not tenant_id and not all_tenants:
        console.print("[red]Provide --tenant <id> or --all.[/red]")
        raise typer.Exit(1)
    if resume and all_tenants:
        console.print("[red]--resume works with a single --tenant, not --all.[/red]")
        raise typer.Exit(1)
    mp = _validate_marketplace(marketplace)
    asyncio.run(_public_skus(tenant_id, all_tenants, cap, city, resume, workers, no_load, mp))


async def _public_skus(
    tenant_id: str | None, all_tenants: bool, cap: int | None,
    city: str | None, resume: bool, workers: int, no_load: bool = False,
    mp_slug: str = "blinkit",
) -> None:
    from scraper.public import targeted

    async def _after(summary: dict) -> None:
        await _auto_load(summary, no_load)

    async with AsyncSessionLocal() as db:
        if all_tenants:
            summaries = await targeted.run_all_targeted(
                db, cap, city, workers, on_tenant_done=_after, mp_slug=mp_slug
            )
        else:
            summaries = [await targeted.run_targeted(
                db, tenant_id, cap, city, resume, workers, mp_slug=mp_slug
            )]
            await _after(summaries[0])

    if not summaries:
        console.print("[yellow]No active tenants to run.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tenant")
    table.add_column("MP")
    table.add_column("Brands", justify="right")
    table.add_column("Locations", justify="right")
    table.add_column("SKU Rows", justify="right")
    table.add_column("Skipped", justify="right")
    table.add_column("Errors", justify="right")
    for s in summaries:
        table.add_row(
            s["tenant_id"][:8], s.get("mp_slug", mp_slug),
            str(s["brands"]), str(s["locations"]),
            str(s["rows"]), str(s.get("skipped", 0)),
            f"[red]{s['errors']}[/red]" if s["errors"] else "0",
        )
    console.print(table)


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


# ── Staging: local SQLite → Postgres ─────────────────────────────────────────

@app.command("staged")
def staged_list(
    pending_only: bool = typer.Option(False, "--pending", help="Only runs not yet loaded"),
    marketplace: str = typer.Option(None, "--marketplace", "-m", help="Only runs from this marketplace"),
):
    """List local staging files from public scrapes (what `scrape load` would push).

    Public scrapes write to a local SQLite file, not straight to Postgres — a long
    run no longer dies with the database. See docs/staging.md.
    """
    from scraper.public import staging

    mp = (marketplace or "").strip().lower() or None
    runs = staging.pending(mp_slug=mp) if pending_only else staging.list_runs(mp_slug=mp)
    if not runs:
        console.print("[dim]No staging files.[/dim]")
        return

    table = Table(show_header=True, header_style="bold",
                  title=f"Staging files — {len(runs)}")
    table.add_column("Date")
    table.add_column("Time")
    table.add_column("MP")
    table.add_column("Kind")
    table.add_column("Stores", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Err", justify="right")
    table.add_column("State")
    table.add_column("Ref", style="dim")
    for r in runs:
        started, loaded = r["started_at"] or "", r["loaded_at"]
        date, _, tm = started.partition("T")
        done, want = r.get("stores_done"), r.get("stores_total")
        stores = f"{done:,}/{want:,}" if done is not None and want else (
            f"{done:,}" if done is not None else "[dim]—[/dim]")
        # A partial run is not automatically bad — 500 of 2059 stores is still 500
        # stores of real data. Flag it, let the human decide.
        if done is not None and want and done < want:
            stores = f"[yellow]{stores}[/yellow]"
        errs = r.get("errors")
        err_txt = "[dim]—[/dim]" if errs is None else (
            f"[red]{errs:,}[/red]" if errs else "0")
        status = {"success": "[green]ok[/green]", "failed": "[red]failed[/red]"} \
            .get(r["status"], f"[yellow]{r['status']}[/yellow]")
        where = "[green]loaded[/green]" if loaded else "[yellow]pending[/yellow]"
        table.add_row(
            date, tm[:5], r["mp_slug"],
            r["kind"].replace("public_", ""),
            stores, f"{r['rows']:,}", err_txt,
            f"{status} · {where}",
            staging.ref(r["path"]),
        )
    console.print(table)
    n_pending = sum(1 for r in runs if not r["loaded_at"])
    n_bad = sum(1 for r in runs if not r["loaded_at"] and r["status"] != "success")
    if n_pending:
        console.print(f"[yellow]{n_pending} file(s) not yet in the database.[/yellow] "
                      f"Push with [bold]python -m cli scrape load[/bold]")
    if n_bad:
        console.print(
            f"[red]{n_bad} pending file(s) did not finish cleanly.[/red] Review before "
            f"loading — drop one with [bold]python -m cli scrape discard --file <name>[/bold]"
        )


@app.command("load")
def load_staged(
    file: str = typer.Option(None, "--file", "-f", help="Which file — the Ref from `scrape staged` (default: all pending, oldest first)"),
    all_pending: bool = typer.Option(False, "--all", help="Load every pending file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be loaded, write nothing"),
    keep: int = typer.Option(None, "--keep", help=f"Loaded files to retain per tenant+kind+marketplace (default {5})"),
):
    """Push staged public-scrape results into Postgres.

    Each file is loaded in ONE all-or-nothing transaction: if the connection drops
    the whole thing rolls back and nothing is written, so re-running is always safe
    (public data is append-only with no upsert — a partial load would duplicate).

    With no --file, loads every pending file oldest-first.
    """
    from scraper.public import staging

    if file:
        try:
            targets = [{"path": staging.resolve(file)}]
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]{escape(str(e))}[/red]")
            console.print("[dim]List them with `python -m cli scrape staged`.[/dim]")
            raise typer.Exit(1)
    else:
        targets = list(reversed(staging.pending()))   # oldest first
        if not targets:
            console.print("[dim]Nothing pending — all staging files are loaded.[/dim]")
            return
        if len(targets) > 1 and not all_pending and not dry_run:
            console.print(
                f"[yellow]{len(targets)} files pending.[/yellow] "
                f"Pass --all to load them all, or --file <name> for one:"
            )
            for t in targets:
                console.print(f"   {t['path'].name}  ({t['rows']:,} rows)")
            raise typer.Exit(1)
        # A run that crashed may still hold data worth keeping, so this is never an
        # automatic skip — but sweeping one into the DB unnoticed via --all is the
        # exact accident worth blocking. Force a deliberate choice.
        unclean = [t for t in targets if t.get("status") != "success"]
        if unclean and not dry_run:
            console.print(
                f"[red]{len(unclean)} pending file(s) did not finish cleanly:[/red]"
            )
            for t in unclean:
                done, want = t.get("stores_done"), t.get("stores_total")
                cover = f", {done}/{want} stores" if done is not None and want else ""
                console.print(
                    f"   [red]{t['status']}[/red]  {t['path'].name}  "
                    f"({t['rows']:,} rows{cover}, {t.get('errors') or 0} errors)"
                )
            console.print(
                "\nPartial data is often still worth loading — but decide per file:\n"
                "  [bold]python -m cli scrape load --file <name>[/bold]     load it anyway\n"
                "  [bold]python -m cli scrape discard --file <name>[/bold]  throw it away"
            )
            raise typer.Exit(1)

    if dry_run:
        table = Table(show_header=True, header_style="bold", title="DRY RUN — nothing written")
        table.add_column("File")
        table.add_column("MP")
        table.add_column("Kind")
        table.add_column("Snapshots", justify="right")
        table.add_column("Listings", justify="right")
        table.add_column("SKU rows", justify="right")
        for t in targets:
            c = t.get("counts") or {}
            table.add_row(t["path"].name, t.get("mp_slug", "?"), t.get("kind", "?"),
                          f"{c.get('search_snapshots', 0):,}",
                          f"{c.get('search_listings', 0):,}",
                          f"{c.get('sku_snapshots', 0):,}")
        console.print(table)
        return

    asyncio.run(_load_staged([t["path"] for t in targets], keep))


async def _load_staged(paths, keep) -> None:
    from scraper.public import loader, staging

    if keep is not None:
        staging.KEEP_PER_KIND = keep

    from sqlalchemy.exc import DBAPIError

    results, failed = [], []
    for p in paths:
        console.print(f"[dim]Loading {p.name} …[/dim]")
        # Retry once on a DB-level failure. Safe by construction: the load is one
        # all-or-nothing transaction, so a failed attempt wrote nothing. Each attempt
        # gets a FRESH session — a dropped connection can't be reused, and the old
        # session's pool entry is poisoned.
        for attempt in (1, 2):
            try:
                async with AsyncSessionLocal() as db:
                    results.append(await loader.load_file(db, p))
                break
            except DBAPIError as e:
                err = getattr(e, "orig", None) or e
                if attempt == 1:
                    console.print(
                        f"[yellow]Connection failed — retrying once:[/yellow] "
                        f"{escape(str(err))[:120]}"
                    )
                    continue
                failed.append((p.name, str(err)))
                console.print(f"[red]FAILED[/red] {p.name}: {escape(str(err))[:300]}")
                console.print("[dim]Nothing was written — rerun the same command to retry.[/dim]")
            except Exception as e:
                failed.append((p.name, str(e)))
                console.print(f"[red]FAILED[/red] {p.name}: {escape(str(e))[:300]}")
                console.print("[dim]Nothing was written — rerun the same command to retry.[/dim]")
                break

    if results:
        table = Table(show_header=True, header_style="bold", title="Loaded")
        table.add_column("File")
        table.add_column("MP")
        table.add_column("Kind")
        table.add_column("Snapshots", justify="right")
        table.add_column("Listings", justify="right")
        table.add_column("SKU rows", justify="right")
        table.add_column("Total", justify="right")
        for r in results:
            table.add_row(r["file"], r["mp_slug"], r["kind"], f"{r['snapshots']:,}",
                          f"{r['listings']:,}", f"{r['skus']:,}", f"{r['total']:,}")
        console.print(table)
        pruned = sum(r["pruned"] for r in results)
        if pruned:
            console.print(f"[dim]Pruned {pruned} old staging file(s).[/dim]")
    if failed:
        console.print(f"[red]{len(failed)} file(s) failed to load.[/red]")
        raise typer.Exit(1)


@app.command("discard")
def discard_staged(
    file: str = typer.Option(..., "--file", "-f", help="Which file — the Ref from `scrape staged`, or a filename/path"),
    force: bool = typer.Option(False, "--force", help="Skip the confirmation prompt"),
):
    """Delete a staging file without loading it.

    For a file that was never loaded this destroys scraped data held nowhere else —
    hence the prompt. Use it to drop a bad run (wrong city, wrong cap, a crash that
    produced nothing useful) so `scrape load --all` can't sweep it into the database.
    """
    from scraper.public import staging

    try:
        path = staging.resolve(file)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        console.print("[dim]List them with `python -m cli scrape staged`.[/dim]")
        raise typer.Exit(1)

    match = next((r for r in staging.list_runs() if r["path"].resolve() == path.resolve()), None)
    if match is None:
        console.print(f"[red]{path.name} is not a readable staging file.[/red]")
        raise typer.Exit(1)

    loaded = match["loaded_at"]
    console.print(
        f"\n  [bold]{path.name}[/bold]\n"
        f"  kind    : {match['kind']}\n"
        f"  scraped : {(match['started_at'] or '').replace('T', ' ')[:16]}\n"
        f"  status  : {match['status']}   errors: {match.get('errors') or 0}\n"
        f"  rows    : {match['rows']:,}\n"
        f"  loaded  : {'yes — ' + loaded[:16].replace('T', ' ') if loaded else 'NO'}\n"
    )
    if loaded:
        console.print("[dim]Already in the database — deleting only removes the local backup.[/dim]")
    else:
        console.print(
            f"[red]NOT loaded.[/red] These {match['rows']:,} rows exist nowhere else — "
            f"deleting is irreversible."
        )
    if not force and not typer.confirm("Delete this file?"):
        console.print("[dim]Cancelled.[/dim]")
        raise typer.Exit(0)

    staging.discard(path)
    console.print(f"[green]Deleted[/green] {path.name}")
