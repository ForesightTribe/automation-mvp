"""Config sync: reconcile the DB to a source-of-truth workbook.

One command reads `config.xlsx` (sheets: locations / brands / coverage) and makes
the DB match it — upserting by default, deleting only with --prune. The workbook
is the source of truth; scrapers never read it. Updates are infrequent, so this
replaces the per-row add/remove CLI verbs.

Sheets
  locations : the global Blinkit darkstore catalog (keyed on merchant_id)
              cols: merchant_id, city, state, region, zone, pincode, lat, lon, active
  brands    : per-tenant keywords/aliases (the watchlist)
              cols: tenant, brand, relationship, keywords, aliases
  coverage  : which catalog locations each tenant scrapes
              cols: tenant, city, zone   (blank zone = all zones in the city)
"""
import asyncio

import typer
from openpyxl import Workbook, load_workbook
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from app.core.database import AsyncSessionLocal
from app.models.search import MarketplaceLocation, TenantLocation
from app.models.tenant import Tenant, TenantWatchlist
from scraper.utils.storage import ensure_refs

console = Console()
MP = "blinkit"


# ── cell coercion ────────────────────────────────────────────────────────────

def _str(v) -> str:
    return "" if v is None else str(v).strip()


def _pincode(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v, default=True) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in {"1", "yes", "y", "true", "t", "active"}


def _csv(v) -> list[str]:
    return [x.strip() for x in str(v).split(",") if x.strip()] if v else []


def _read_sheet(wb, name: str) -> list[dict]:
    if name not in wb.sheetnames:
        console.print(f"[yellow]Sheet '{name}' not found — skipping.[/yellow]")
        return []
    rows = list(wb[name].iter_rows(values_only=True))
    if not rows:
        return []
    header = [(_str(c).lower()) for c in rows[0]]
    out = []
    for r in rows[1:]:
        if all(c is None for c in r):
            continue
        out.append({header[i]: r[i] for i in range(len(header)) if header[i]})
    return out


def _read_config(path: str) -> dict:
    wb = load_workbook(path, data_only=True)
    return {
        "locations": _read_sheet(wb, "locations"),
        "brands": _read_sheet(wb, "brands"),
        "coverage": _read_sheet(wb, "coverage"),
    }


# ── reconciliation ───────────────────────────────────────────────────────────

_LOC_FIELDS = ("city", "state", "region", "zone", "pincode", "lat", "lon", "is_active")


async def _sync_locations(db, rows, prune) -> dict:
    desired = {}
    for r in rows:
        mid = _str(r.get("merchant_id"))
        if not mid:
            continue
        desired[mid] = {
            "city": _str(r.get("city")).lower(),
            "state": _str(r.get("state")),
            "region": _str(r.get("region")),
            "zone": _str(r.get("zone")),
            "pincode": _pincode(r.get("pincode")),
            "lat": _float(r.get("lat")),
            "lon": _float(r.get("lon")),
            "is_active": _bool(r.get("active")),
        }
    existing = {
        l.merchant_id: l
        for l in (await db.execute(
            select(MarketplaceLocation).where(MarketplaceLocation.mp_slug == MP)
        )).scalars().all()
    }
    added = updated = deleted = 0
    for mid, vals in desired.items():
        cur = existing.get(mid)
        if cur is None:
            db.add(MarketplaceLocation(mp_slug=MP, merchant_id=mid, **vals))
            added += 1
        elif any(getattr(cur, f) != vals[f] for f in _LOC_FIELDS):
            for f in _LOC_FIELDS:
                setattr(cur, f, vals[f])
            updated += 1
    if prune:
        for mid, cur in existing.items():
            if mid not in desired:
                await db.execute(
                    TenantLocation.__table__.delete().where(TenantLocation.location_id == cur.id)
                )
                await db.delete(cur)
                deleted += 1
    await db.flush()
    return {"added": added, "updated": updated, "deleted": deleted}


async def _sync_brands(db, rows, tenants, prune) -> dict:
    desired = {}
    for r in rows:
        tname = _str(r.get("tenant"))
        brand = _str(r.get("brand")).lower()
        if not tname or not brand:
            continue
        desired[(tenants[tname], brand)] = {
            "relationship": _str(r.get("relationship")).lower() or "own",
            "keywords": _csv(r.get("keywords")),
            "aliases": _csv(r.get("aliases")),
        }
    ref_tenants = {tid for tid, _ in desired}
    existing = {
        (w.tenant_id, w.brand_slug): w
        for w in (await db.execute(
            select(TenantWatchlist).where(TenantWatchlist.tenant_id.in_(ref_tenants or [None]))
        )).scalars().all()
    }
    added = updated = deleted = 0
    for (tid, brand), vals in desired.items():
        await ensure_refs(db, brand, MP)
        cur = existing.get((tid, brand))
        if cur is None:
            db.add(TenantWatchlist(
                tenant_id=tid, brand_slug=brand, cities=[], marketplaces=[MP], **vals
            ))
            added += 1
        elif (cur.relationship, cur.keywords, cur.aliases) != (
            vals["relationship"], vals["keywords"], vals["aliases"]
        ):
            cur.relationship, cur.keywords, cur.aliases = (
                vals["relationship"], vals["keywords"], vals["aliases"]
            )
            updated += 1
    if prune:
        for key, cur in existing.items():
            if key not in desired:
                await db.delete(cur)
                deleted += 1
    await db.flush()
    return {"added": added, "updated": updated, "deleted": deleted}


async def _sync_coverage(db, rows, tenants, prune) -> dict:
    # Resolve each (tenant, city, [zone]) to catalog location ids.
    desired = set()
    covered_tenants = set()
    for r in rows:
        tname = _str(r.get("tenant"))
        city = _str(r.get("city")).lower()
        zone = _str(r.get("zone"))
        if not tname or not city:
            continue
        tid = tenants[tname]
        covered_tenants.add(tid)
        q = select(MarketplaceLocation.id).where(
            MarketplaceLocation.mp_slug == MP, MarketplaceLocation.city == city
        )
        if zone:
            q = q.where(MarketplaceLocation.zone == zone)
        for lid in (await db.execute(q)).scalars().all():
            desired.add((tid, lid))

    existing = {
        (t.tenant_id, t.location_id): t
        for t in (await db.execute(
            select(TenantLocation).where(TenantLocation.tenant_id.in_(covered_tenants or [None]))
        )).scalars().all()
    }
    added = deleted = 0
    for (tid, lid) in desired:
        if (tid, lid) not in existing:
            db.add(TenantLocation(tenant_id=tid, mp_slug=MP, location_id=lid))
            added += 1
    if prune:
        for key, cur in existing.items():
            if key not in desired:
                await db.delete(cur)
                deleted += 1
    await db.flush()
    return {"added": added, "deleted": deleted}


async def _do_sync(data, dry_run, prune) -> dict:
    async with AsyncSessionLocal() as db:
        tenants = {t.name: t.id for t in (await db.execute(select(Tenant))).scalars().all()}
        referenced = {_str(r.get("tenant")) for r in data["brands"] + data["coverage"] if _str(r.get("tenant"))}
        unknown = sorted(referenced - set(tenants))
        if unknown:
            raise ValueError(
                f"Unknown tenant(s) in file: {unknown}. Create them with `cli tenant create` first."
            )

        loc = await _sync_locations(db, data["locations"], prune)
        brands = await _sync_brands(db, data["brands"], tenants, prune)
        cov = await _sync_coverage(db, data["coverage"], tenants, prune)

        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return {"locations": loc, "brands": brands, "coverage": cov}


# ── template ─────────────────────────────────────────────────────────────────

def _write_template(path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "locations"
    ws.append(["merchant_id", "city", "state", "region", "zone", "pincode", "lat", "lon", "active"])
    ws.append(["48967", "delhi", "Delhi", "North India", "", "110001", 28.6315, 77.2167, "yes"])

    b = wb.create_sheet("brands")
    b.append(["tenant", "brand", "relationship", "keywords", "aliases"])
    b.append(["Dobra", "dobra", "own", "dobra, soda, goli soda", "dobra"])
    b.append(["Dobra", "bisleri", "competitor", "", "bisleri"])

    c = wb.create_sheet("coverage")
    c.append(["tenant", "city", "zone"])
    c.append(["Dobra", "delhi", ""])

    wb.save(path)


# ── command ──────────────────────────────────────────────────────────────────

def run_sync(
    file: str = typer.Option("config.xlsx", "--file", "-f", help="Path to the config workbook"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing"),
    prune: bool = typer.Option(False, "--prune", help="Also delete DB rows missing from the file"),
    template: bool = typer.Option(False, "--template", help="Write a starter workbook to --file and exit"),
):
    """Reconcile the DB to the config workbook (locations + brands + coverage)."""
    if template:
        _write_template(file)
        console.print(f"[green]Template written to[/green] {file}")
        return

    data = _read_config(file)
    console.print(
        f"[dim]Read {len(data['locations'])} locations, {len(data['brands'])} brands, "
        f"{len(data['coverage'])} coverage rows from {file}[/dim]"
    )
    result = asyncio.run(_do_sync(data, dry_run, prune))

    table = Table(show_header=True, header_style="bold",
                  title="DRY RUN — no changes written" if dry_run else "Synced")
    table.add_column("Section")
    table.add_column("Added", justify="right")
    table.add_column("Updated", justify="right")
    table.add_column("Deleted", justify="right")
    for section in ("locations", "brands", "coverage"):
        s = result[section]
        table.add_row(section, str(s.get("added", 0)), str(s.get("updated", 0)), str(s.get("deleted", 0)))
    console.print(table)
    if not prune:
        console.print("[dim]Deletions disabled (no --prune): rows missing from the file were kept.[/dim]")
