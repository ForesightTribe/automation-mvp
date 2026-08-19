"""`cli export` — render stored data to an Excel workbook.

`export public` builds a client's public (marketplace-scraped) report from the
database. `export sample` renders a fixture with no database at all, so the
shared renderer's look can be judged and regressions caught in seconds.

See docs/exports.md.
"""
import asyncio
import uuid
from datetime import date, datetime
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from app.core.database import AsyncSessionLocal
from exports import raw as raw_export
from exports import write_workbook
from exports.build import build_report, client_name, latest_window
from exports.sample import sample_report
from app.schemas.exports import ReportSpec

app = typer.Typer(help="Render Foresight data to Excel workbooks.")
console = Console()

_EXPORT_DIR = Path("out")


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


@app.command()
def public(
    tenant: str = typer.Option(..., "--tenant", "-t", help="Client id (see `cli tenant list`)"),
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: the last 7 days that have data)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD, inclusive"),
    city: str = typer.Option(None, "--city", "-c", help="Restrict to one city"),
    kind: str = typer.Option("main", "--kind", help="main | combo | all"),
    marketplace: str = typer.Option(None, "--marketplace", "-m", help="Restrict to one marketplace"),
    sections: str = typer.Option(None, "--sections", help="Comma-separated section keys (default: all public sections)"),
    label: str = typer.Option("", "--label", help="Optional label printed on the cover"),
    output: str = typer.Option(None, "--output", "-o", help="Output .xlsx path"),
):
    """Build a client's public shelf & search report from stored scrape data."""
    asyncio.run(_public(tenant, date_from, date_to, city, kind, marketplace,
                        sections, label, output))


async def _public(tenant, date_from, date_to, city, kind, marketplace,
                  sections, label, output) -> None:
    try:
        tenant_id = uuid.UUID(tenant)
    except ValueError:
        console.print(f"[red]'{tenant}' is not a valid client id — see `cli tenant list`.[/red]")
        raise typer.Exit(1)

    async with AsyncSessionLocal() as db:
        # Check the client exists before anything else, so an id typo reports
        # itself rather than surfacing as "no scrape data".
        if await client_name(db, tenant_id) is None:
            console.print(f"[red]No client with id {tenant_id} — see `cli tenant list`.[/red]")
            raise typer.Exit(1)

        # Anchor the default window to the data, not to today: public scrapes run
        # weekly, so "the last 7 days from now" can land entirely after the most
        # recent scrape and return an empty report that looks like a bug.
        if date_from and date_to:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        else:
            window = await latest_window(db, tenant_id)
            if window is None:
                console.print("[yellow]No public scrape data for this client at all.[/yellow]")
                raise typer.Exit(1)
            start, end = window
            if date_from:
                start = date.fromisoformat(date_from)
            if date_to:
                end = date.fromisoformat(date_to)
            console.print(f"[dim]No date range given — using the latest week with data: {start} to {end}[/dim]")

        try:
            spec = ReportSpec(
                tenant_id=tenant_id, start=start, end=end,
                marketplace=marketplace, cities=_split(city), kind=kind,
                sections=_split(sections), label=label,
            )
        except ValidationError as e:
            # Pydantic's full rendering (with its docs URL) buries the sentence
            # that actually tells the user what to change.
            for err in e.errors():
                console.print(f"[red]{err['msg'].removeprefix('Value error, ')}[/red]")
            raise typer.Exit(1)

        try:
            report = await build_report(db, spec)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    if not report.sections:
        console.print(
            "[yellow]Nothing to export — no section had data in this window.[/yellow]\n"
            "[dim]Check the window against the last scrape: `cli scrape staged`.[/dim]"
        )
        raise typer.Exit(1)

    path = Path(output) if output else _EXPORT_DIR / f"{report.filename_stem}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_workbook(report, str(path))

    summary = Table(show_header=True, header_style="bold", title=report.title)
    summary.add_column("Sheet")
    summary.add_column("Rows", justify="right")
    for s in report.sections:
        summary.add_row(s.title, f"{len(s.rows):,}" if s.rows else f"{len(s.kpis)} KPIs")
    console.print(summary)
    console.print(f"[green]Saved workbook ->[/green] {path}")


@app.command()
def raw(
    tenant: str = typer.Option(..., "--tenant", "-t", help="Client id"),
    date_from: str = typer.Option(None, "--from", help="Start date YYYY-MM-DD (default: the last 7 days that have data)"),
    date_to: str = typer.Option(None, "--to", help="End date YYYY-MM-DD, inclusive"),
    tables: str = typer.Option(None, "--tables", help=f"Comma-separated: {', '.join(raw_export.TABLES)} (default: all)"),
    city: str = typer.Option(None, "--city", "-c", help="Restrict to one city"),
    marketplace: str = typer.Option(None, "--marketplace", "-m", help="Restrict to one marketplace"),
    limit: int = typer.Option(None, "--limit", help="Cap rows per table — for a quick sample"),
    include_extra: bool = typer.Option(False, "--include-extra", help="Include the scraper's raw `extra` payload (roughly doubles file size)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count the rows and stop — no files written"),
    out: str = typer.Option(None, "--out", "-o", help="Output directory"),
):
    """Dump the underlying rows to CSV — on demand, never bundled into a report.

    One week of a mid-size client runs to hundreds of thousands of rows, which is
    why this is a separate command: the client report stays small enough to hang
    off a download button, and the raw pull is here when someone actually needs it.
    """
    asyncio.run(_raw(tenant, date_from, date_to, tables, city, marketplace,
                     limit, include_extra, dry_run, out))


async def _raw(tenant, date_from, date_to, tables, city, marketplace,
               limit, include_extra, dry_run, out) -> None:
    try:
        tenant_id = uuid.UUID(tenant)
    except ValueError:
        console.print(f"[red]'{tenant}' is not a valid client id — see `cli tenant list`.[/red]")
        raise typer.Exit(1)

    wanted = _split(tables) or list(raw_export.TABLES)
    unknown = [t for t in wanted if t not in raw_export.TABLES]
    if unknown:
        console.print(f"[red]Unknown table(s): {', '.join(unknown)}. "
                      f"Available: {', '.join(raw_export.TABLES)}[/red]")
        raise typer.Exit(1)

    async with AsyncSessionLocal() as db:
        client = await client_name(db, tenant_id)
        if client is None:
            console.print(f"[red]No client with id {tenant_id} — see `cli tenant list`.[/red]")
            raise typer.Exit(1)

        if date_from and date_to:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        else:
            window = await latest_window(db, tenant_id)
            if window is None:
                console.print("[yellow]No public scrape data for this client at all.[/yellow]")
                raise typer.Exit(1)
            start, end = window
            if date_from:
                start = date.fromisoformat(date_from)
            if date_to:
                end = date.fromisoformat(date_to)
            console.print(f"[dim]No date range given — using the latest week with data: {start} to {end}[/dim]")

        filters = dict(tenant_id=tenant_id, start=start, end=end,
                       city=city, marketplace=marketplace)

        # Count first, always. The whole point of splitting this out is that the
        # volume is the thing worth knowing before you commit to it.
        counts = {k: await raw_export.count(db, raw_export.TABLES[k], **filters) for k in wanted}

        table = Table(show_header=True, header_style="bold",
                      title=f"{client} — raw rows, {start} to {end}")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        table.add_column("What it is")
        for k in wanted:
            spec = raw_export.TABLES[k]
            shown = f"{min(counts[k], limit):,} of {counts[k]:,}" if limit and counts[k] > limit \
                else f"{counts[k]:,}"
            table.add_row(k, shown, spec.description)
        console.print(table)

        total = sum(min(c, limit) if limit else c for c in counts.values())
        # The store catalogue has no scraped_at, so it survives a window with no
        # scrape data at all. Writing it alone would report "wrote 3,288 rows"
        # for a window that actually holds nothing — the same wrong-dates trap
        # the report guards against. Only let it through if it was asked for.
        windowed = [k for k in wanted if raw_export.TABLES[k].windowed]
        if windowed and not sum(counts[k] for k in windowed):
            console.print(
                f"[yellow]No scrape data between {start} and {end}.[/yellow]\n"
                f"[dim]Only the store catalogue is not date-scoped; run with "
                f"`--tables stores` if that is what you want.[/dim]"
            )
            raise typer.Exit(1)

        if dry_run:
            console.print(f"[dim]Dry run — nothing written. {total:,} rows would be exported.[/dim]")
            return
        if not total:
            console.print("[yellow]Nothing to export — no rows matched.[/yellow]")
            raise typer.Exit(1)

        directory = Path(out) if out else _EXPORT_DIR / f"{client.replace(' ', '_')}_raw_{start}_{end}"
        directory.mkdir(parents=True, exist_ok=True)

        written = {}
        for k in wanted:
            if not counts[k]:
                continue
            spec = raw_export.TABLES[k]
            path = directory / f"{spec.label}.csv"
            with console.status(f"Writing {spec.label}.csv …"):
                written[k] = await raw_export.export_table(
                    db, spec, path, include_extra=include_extra, limit=limit, **filters,
                )

    done = Table(show_header=True, header_style="bold")
    done.add_column("File")
    done.add_column("Rows", justify="right")
    done.add_column("Size", justify="right")
    for k, n in written.items():
        path = directory / f"{raw_export.TABLES[k].label}.csv"
        done.add_row(path.name, f"{n:,}", f"{path.stat().st_size / 1_048_576:.1f} MB")
    console.print(done)
    console.print(f"[green]Wrote {sum(written.values()):,} rows ->[/green] {directory}")


@app.command()
def sections():
    """List the sections available to `export`."""
    from exports import registry
    import exports.sections  # noqa: F401 — triggers registration

    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Group")
    table.add_column("Glossary terms")
    for entry in registry.SECTIONS.values():
        table.add_row(entry["key"], entry["group"], ", ".join(entry["terms"]) or "—")
    console.print(table)


@app.command()
def sample(
    output: str = typer.Option(None, "--output", "-o", help="Output .xlsx path (default: exports/sample_<ts>.xlsx)"),
):
    """Render the fixture workbook — every column type, both colour scales, chips
    and a totals row. No database required."""
    report = sample_report()
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        _EXPORT_DIR.mkdir(exist_ok=True)
        path = _EXPORT_DIR / f"{report.filename_stem}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    write_workbook(report, str(path))

    sheets = len(report.sections) + (1 if report.glossary else 0) + 1
    rows = sum(len(s.rows) for s in report.sections)
    console.print(
        f"[green]Saved workbook ->[/green] {path}\n"
        f"[dim]{sheets} sheets · {rows:,} data rows · {len(report.glossary)} glossary terms[/dim]"
    )
