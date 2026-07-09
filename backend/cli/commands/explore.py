"""`cli explore` — run an on-demand Explorer scrape and write an Excel workbook.

Thin wrapper over the engine: parses argv into an `ExplorerSpec`, calls
`run_explorer` (with a live progress bar), then `build_insights` → `write_workbook`.
Ephemeral + agency-facing: writes nothing to the per-tenant fact tables, only an
`explorer_runs` record + the .xlsx.
"""
import asyncio
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from app.core.database import AsyncSessionLocal
from app.schemas.explorer import ExplorerSpec
from scraper.public.explorer import build_insights, run_explorer, supported_marketplaces
from scraper.utils.search_result import slugify

app = typer.Typer()
console = Console()

_EXPORT_DIR = Path("exports")


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",")] if value else []


def explore(
    brand: str = typer.Option(..., "--brand", "-b", help="Focus brand (name or slug), e.g. 'dobra'"),
    keyword: str = typer.Option(None, "--keyword", "-k", help="Comma-separated category keywords"),
    city: str = typer.Option(None, "--city", "-c", help="Comma-separated cities (default: every catalog city)"),
    competitors: str = typer.Option(None, "--competitors", help="Comma-separated competitor whitelist (default: discover all)"),
    aliases: str = typer.Option(None, "--aliases", help="Comma-separated brand-name variants for matching"),
    marketplace: str = typer.Option("blinkit", "--marketplace", "-m", help="Marketplace to scrape"),
    mode: str = typer.Option("keyword", "--mode", help="keyword | catalog | both"),
    catalog: bool = typer.Option(False, "--catalog", help="Also scrape the own-brand catalog (own price/stock)"),
    sample: int = typer.Option(50, "--sample", help="Locations sampled per city (evenly spread)"),
    full: bool = typer.Option(False, "--full", help="Full census — every catalog location (ignores --sample)"),
    workers: int = typer.Option(5, "--workers", "-w", help="Concurrent browser workers"),
    cap: int = typer.Option(None, "--cap", help="Per-keyword result cap override"),
    brand_cap: int = typer.Option(None, "--brand-cap", help="Catalog-mode brand-query cap override"),
    label: str = typer.Option("", "--label", help="Optional human label for the run"),
    tenant_id: str = typer.Option(None, "--tenant", "-t", help="Optional: attribute the run to a client"),
    output: str = typer.Option(None, "--output", "-o", help="Output .xlsx path (default: exports/<brand>_<ts>.xlsx)"),
):
    """Run a custom scrape across any brand / keywords / cities and export a
    multi-sheet Excel report. No client/tenant required."""
    if marketplace.lower() not in supported_marketplaces():
        console.print(
            f"[red]Marketplace '{marketplace}' is not supported yet "
            f"(available: {', '.join(supported_marketplaces())}).[/red]"
        )
        raise typer.Exit(1)

    if mode not in ("keyword", "catalog", "both"):
        console.print("[red]--mode must be one of: keyword, catalog, both.[/red]")
        raise typer.Exit(1)

    keywords = _split(keyword)
    # --catalog is sugar: fold it into the mode.
    if catalog and mode == "keyword":
        mode = "both" if keywords else "catalog"
    if mode in ("keyword", "both") and not keywords:
        console.print("[red]Keyword mode needs --keyword (comma-separated). Use --mode catalog for own-SKU only.[/red]")
        raise typer.Exit(1)

    spec = ExplorerSpec(
        marketplace=marketplace.lower(),
        brand=brand,
        aliases=_split(aliases),
        competitors=_split(competitors),
        keywords=keywords,
        cities=_split(city),
        mode=mode,
        sample=sample,
        full=full,
        workers=workers,
        cap=cap,
        brand_cap=brand_cap,
        label=label,
        tenant_id=tenant_id,
    )

    if output:
        out_path = Path(output)
    else:
        _EXPORT_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = _EXPORT_DIR / f"{slugify(brand)}_{ts}.xlsx"

    asyncio.run(_run(spec, out_path))


async def _run(spec: ExplorerSpec, out_path: Path) -> None:
    console.print(
        f"[cyan]Explorer[/cyan] · {spec.marketplace} · brand=[bold]{spec.brand}[/bold] · "
        f"mode={spec.mode} · {len(spec.keywords)} keyword(s) · "
        f"{'all cities' if not spec.cities else ', '.join(spec.cities)} · "
        f"{'census' if spec.full else f'sample {spec.sample}/city'}"
    )
    try:
        async with AsyncSessionLocal() as db:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total} locations"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Scraping", total=None)

                def on_progress(done: int, total: int) -> None:
                    progress.update(task, total=total, completed=done)

                result = await run_explorer(db, spec, on_progress=on_progress)
                progress.update(task, total=result.locations, completed=result.locations)
    except Exception as e:
        console.print(f"[red]Explorer run failed: {escape(str(e))}[/red]")
        raise typer.Exit(1)

    if not result.locations:
        console.print("[yellow]No catalog locations matched the requested cities — nothing scraped.[/yellow]")
        raise typer.Exit(1)

    insights = build_insights(result)
    path = str(out_path)
    from scraper.public.explorer import write_workbook
    write_workbook(insights, result, path)

    _print_summary(result, insights, path)


def _print_summary(result, insights, path: str) -> None:
    ov = insights.overview
    console.print(
        f"\n[bold cyan]Explorer complete[/bold cyan] "
        f"[dim](run {result.run_id})[/dim]\n"
        f"  locations: {result.locations}   snapshots: {len(result.snapshots)}   "
        f"listings: {len(result.listings)}   catalog SKUs: {len(result.sku_rows)}   "
        f"errors: {len(result.errors)}"
    )
    headline = Table(show_header=False, box=None, padding=(0, 2))
    headline.add_column(style="dim")
    headline.add_column(style="bold")
    headline.add_row("Overall SoV %", str(ov.overall_sov_pct))
    headline.add_row("Avg rank", str(ov.avg_rank))
    headline.add_row("In-stock % (own)", str(ov.in_stock_pct))
    headline.add_row("Keywords in top-3", str(ov.keywords_top3))
    headline.add_row("Strongest / weakest kw", f"{ov.strongest_keyword or '—'} / {ov.weakest_keyword or '—'}")
    headline.add_row("Competitors discovered", str(ov.total_competitors))
    console.print(headline)

    if insights.keywords:
        table = Table(show_header=True, header_style="bold", title="Keyword Scorecard")
        table.add_column("Keyword")
        table.add_column("SoV %", justify="right")
        table.add_column("Avg Rank", justify="right")
        table.add_column("Best", justify="right")
        table.add_column("Presence %", justify="right")
        table.add_column("Top Competitor")
        for k in insights.keywords[:10]:
            table.add_row(
                k.keyword, str(k.sov_pct), str(k.avg_rank), str(k.best_rank or "—"),
                str(k.presence_pct), k.top_competitor or "—",
            )
        console.print(table)

    console.print(f"\n[green]Saved workbook ->[/green] {path}")
