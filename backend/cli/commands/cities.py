"""Canonical city registry (V7.3) — seed it, and report how well everything maps into it.

The same place is spelled differently on every surface: Blinkit's ads say `Gurugram`, its
seller dashboard says `Gurgaon`, our store catalog says `hr-ncr`, Zepto's says `delhi ncr`.
`cities` is the one list they all point at; `city_aliases` holds the exceptions.

    cli cities seed [--mp blinkit] [--dry-run]   # build/refresh the list + pincode prefixes
    cli cities status [--mp blinkit]             # coverage: what still maps to nothing

Seeding is generated data, which is why it lives in a command and not the config workbook:
the city LIST comes from a marketplace's own directory (a free, curated list of Indian
q-commerce cities, with states), and PINCODE PREFIXES are derived from our own stores. Only
the exceptions are hand-written, in `config.xlsx`'s `city_map` sheet.
"""
import asyncio
import re

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, text
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.search import City, CityAlias, MarketplaceLocation

app = typer.Typer(help="Canonical city registry")
console = Console()

# A pincode prefix is only useful if it identifies ONE city. Start at 3 digits (a postal
# district is usually one city); where two cities share one, retry those at 4 — that is
# exactly the Noida/Ghaziabad case, both inside 201xxx. Still ambiguous → no prefix, and
# the city is then reachable by name only.
_PREFIX_LENGTHS = (3, 4)


def _slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.strip().lower())).strip("-")


async def _any_tenant_with_session(mp: str) -> str | None:
    """Any tenant holding a live session for `mp`. The city directory is account-independent
    reference data, so which tenant's session reads it does not matter."""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT tenant_id FROM platform_sessions WHERE platform = :mp "
            "ORDER BY id DESC LIMIT 1"
        ), {"mp": mp})).first()
        return str(row[0]) if row else None


async def _blinkit_directory(tenant: str) -> list[dict]:
    from campaign_manager.marketplaces.blinkit import client as bk

    pw, browser, cl = await bk.setup(tenant)
    try:
        resp = await cl._fetch("GET", "/adservice/v2/campaigns/config")
        data = (resp or {}).get("data") or {}
    finally:
        await browser.close()
        await pw.stop()

    out = []
    for state in data.get("states_and_cities") or []:
        for c in state.get("cities") or []:
            if c.get("name"):
                out.append({"name": str(c["name"]).strip(),
                            "state": str(state.get("state_name") or "").strip()})
    # Fall back to the flat {id: name} map if the grouped one is absent — it has no state,
    # but a city with no state still resolves.
    if not out:
        out = [{"name": str(v).strip(), "state": ""} for v in (data.get("cities") or {}).values()]
    return out


def _derive_prefixes(store_rows, name_by_slug: dict) -> dict:
    """{city_slug: [prefixes]} from our own stores.

    Only cities whose CATALOG name already equals a canonical name can be derived this way
    — which is the point: those are the unambiguous ones, and they bootstrap the pincode
    rules that later resolve the grouped buckets (`hr-ncr`) that match no name at all.
    """
    for length in _PREFIX_LENGTHS:
        by_prefix: dict[str, set] = {}
        by_city: dict[str, set] = {}
        for city, pincode in store_rows:
            slug = _slug(city or "")
            if slug not in name_by_slug or not pincode or len(pincode) < length:
                continue
            p = pincode[:length]
            by_prefix.setdefault(p, set()).add(slug)
            by_city.setdefault(slug, set()).add(p)
        # Keep only prefixes owned by exactly one city; a shared one would tag stores into
        # whichever city happened to be checked first.
        clean = {
            slug: sorted(p for p in prefixes if len(by_prefix[p]) == 1)
            for slug, prefixes in by_city.items()
        }
        clean = {s: p for s, p in clean.items() if p}
        if length == _PREFIX_LENGTHS[-1] or len(clean) == len(by_city):
            return clean
    return clean


@app.command("seed")
def seed(
    mp: str = typer.Option("blinkit", "--mp", help="Marketplace whose city directory to read"),
    tenant: str = typer.Option(None, "--tenant", "-t", help="Tenant whose session to use"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
):
    """Build/refresh `cities` from a marketplace directory, with pincode prefixes derived
    from our own stores. Idempotent — re-running adds new cities and refreshes prefixes,
    and never deletes (a city that vanishes from the directory may still have stores)."""
    async def _run():
        tid = tenant or await _any_tenant_with_session(mp)
        if not tid:
            raise typer.BadParameter(
                f"no stored {mp} session found — pass --tenant, or log in with "
                f"`cli auth login {mp} -t <uuid>` first")
        directory = await _blinkit_directory(tid)
        console.print(f"[dim]{len(directory)} cities in the {mp} directory[/dim]")

        async with AsyncSessionLocal() as db:
            existing = {c.slug: c for c in (await db.execute(select(City))).scalars().all()}
            added = 0
            for entry in directory:
                slug = _slug(entry["name"])
                if not slug:
                    continue
                if slug not in existing:
                    city = City(slug=slug, name=entry["name"], state=entry["state"])
                    db.add(city)
                    existing[slug] = city
                    added += 1
                elif entry["state"] and not existing[slug].state:
                    existing[slug].state = entry["state"]
            await db.flush()

            store_rows = (await db.execute(text(
                "SELECT city, pincode FROM marketplace_locations "
                "WHERE is_active AND pincode ~ '^[0-9]{6}$'"
            ))).all()
            prefixes = _derive_prefixes(store_rows, existing)
            changed = 0
            for slug, plist in prefixes.items():
                city = existing.get(slug)
                if city is not None and city.pincode_prefixes != plist:
                    city.pincode_prefixes = plist
                    changed += 1

            if dry_run:
                await db.rollback()
            else:
                await db.commit()

        console.print(
            f"[green]{'Would add' if dry_run else 'Added'}[/green] {added} cities; "
            f"pincode prefixes set on {changed} "
            f"({'dry run — nothing written' if dry_run else 'written'})"
        )

    asyncio.run(_run())


@app.command("status")
def status(mp: str = typer.Option("blinkit", "--mp", help="Marketplace to report on")):
    """Coverage report: how many stores resolve to a canonical city, and what does not."""
    async def _run():
        async with AsyncSessionLocal() as db:
            total, tagged = (await db.execute(text(
                "SELECT count(*), count(city_id) FROM marketplace_locations "
                "WHERE mp_slug = :mp AND is_active"
            ), {"mp": mp})).first()
            cities = (await db.execute(select(func.count()).select_from(City))).scalar()
            aliases = (await db.execute(select(func.count()).select_from(CityAlias))).scalar()
            untagged = (await db.execute(text(
                "SELECT city, count(*) FROM marketplace_locations "
                "WHERE mp_slug = :mp AND is_active AND city_id IS NULL "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
            ), {"mp": mp})).all()

        console.print(f"\n[bold]cities[/bold] {cities}   [bold]aliases[/bold] {aliases}")
        pct = (tagged / total * 100) if total else 0
        style = "green" if pct > 99 else "yellow" if pct > 90 else "red"
        console.print(f"[bold]{mp} stores mapped to a city:[/bold] "
                      f"[{style}]{tagged}/{total} ({pct:.1f}%)[/{style}]")
        if untagged:
            t = Table(show_header=True, header_style="bold",
                      title="catalog cities that resolve to nothing")
            t.add_column("catalog city")
            t.add_column("stores", justify="right")
            for city, n in untagged:
                t.add_row(city or "(blank)", str(n))
            console.print(t)
            console.print("[dim]Fix by adding a row to config.xlsx's `city_map` sheet — an "
                          "alias for a 1:1 name, or pincode_prefixes for a grouped one — "
                          "then `cli sync`.[/dim]")

    asyncio.run(_run())
