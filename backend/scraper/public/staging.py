"""Local SQLite staging for the public scrapes — the "extract" half of E→L.

A full public run is ~1.5 hours and ~185k rows. Writing those straight to Supabase
couples the scrape's success to the database being continuously reachable for that
whole window: one pooler blip, home-NAT drop or maintenance restart killed a run that
Blinkit had served perfectly. `pool_pre_ping`, `pool_recycle` and a retry-once on the
write path (see `app/core/database.py`) are all already in place — there is no config
knob left, because this is a coupling problem, not a tuning one.

So the scrape now writes here instead: one SQLite file per run, mirroring the three
public tables field-for-field. `cli scrape load` pushes a file into Postgres later, in
a single all-or-nothing transaction. Consequences:

  * the scrape phase needs **zero** DB connections, so a Supabase outage mid-run is
    survivable and the pooler cap stops bounding `--workers`
  * a failed load is retried without re-scraping anything
  * ~18.5k individual commits collapse into a handful of bulk inserts

`scraped_at` is stamped at SCRAPE time and carried through untouched — loading
tomorrow must not backdate today's trend series.

The handle is a plain dict (house style: functions, not classes), same shape as the
browser session in `blinkit/public_data/scraper.py`.
"""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from app.utils.logger import logger
from app.utils.time import now_ist
from scraper.utils.pack import pack_fields, combo_from_pack

# Kinds mirror ScrapeJob.dashboard so the loader can create the job row verbatim.
KIND_SEARCH = "public_search"
KIND_SKUS = "public_skus"

# Files staged before the multi-marketplace refactor carry no `mp_slug`; every
# reader resolves that NULL to this, so a pre-existing staged run still loads.
DEFAULT_MP = "blinkit"

STAGING_DIR = Path(__file__).resolve().parents[2] / "staging"
KEEP_PER_KIND = 5   # loaded files retained per (tenant, kind); older ones pruned

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    job_id        TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    -- Which marketplace this run scraped. NULL in files staged before the
    -- multi-marketplace refactor — readers default those to 'blinkit'.
    mp_slug       TEXT,
    started_at    TEXT NOT NULL,
    completed_at  TEXT,
    status        TEXT NOT NULL,      -- running | success | failed
    error         TEXT,
    loaded_at     TEXT,               -- NULL until pushed to Postgres
    -- Quality signals, so `cli scrape staged` can show whether a run is worth
    -- loading at all. Nothing here is enforced — only a human can judge "bad"
    -- (a run that died at 500/2059 stores still holds 500 stores of real data).
    stores_total  INTEGER,
    stores_done   INTEGER,
    errors        INTEGER,
    skipped       INTEGER
);

CREATE TABLE IF NOT EXISTS search_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT, job_id TEXT, brand_slug TEXT, mp_slug TEXT, keyword TEXT,
    city          TEXT, zone TEXT, pincode TEXT, lat REAL, lon REAL,
    merchant_id   TEXT, scraped_at TEXT,
    brand_rank    INTEGER, brand_sov REAL, total_results INTEGER
);

CREATE TABLE IF NOT EXISTS search_listings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_local_id INTEGER NOT NULL,   -- local FK; remapped to the real id at load
    tenant_id     TEXT, job_id TEXT, mp_slug TEXT, brand_slug TEXT, keyword TEXT,
    city          TEXT, zone TEXT, pincode TEXT, scraped_at TEXT,
    position      INTEGER, product_name TEXT, is_brand INTEGER,
    price         REAL, mrp REAL, discount_pct REAL,
    pack_raw      TEXT, pack_size REAL, pack_uom TEXT, pack_count INTEGER,
    in_stock      INTEGER, inventory INTEGER, platform_product_id TEXT,
    merchant_id   TEXT, merchant_type TEXT, is_combo INTEGER, extra TEXT
);

CREATE TABLE IF NOT EXISTS sku_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT, job_id TEXT, mp_slug TEXT, brand_slug TEXT,
    platform_product_id TEXT, product_name TEXT,
    merchant_id   TEXT, merchant_type TEXT,
    city          TEXT, lat REAL, lon REAL, scraped_at TEXT,
    price         REAL, mrp REAL, discount_pct REAL,
    pack_raw      TEXT, pack_size REAL, pack_uom TEXT, pack_count INTEGER,
    in_stock      INTEGER, inventory INTEGER, rating REAL, is_combo INTEGER,
    -- Marketplace-specific detail, own-brand rows only. This table is 6-17x
    -- smaller than search_listings (own SKUs, not every SERP row), so a JSON
    -- blob costs ~10 MB per national run here against ~85 MB there — which is
    -- why the richness lands on this table and not the keyword one.
    extra         TEXT,
    -- An identity, not detail: Zepto has both a product id and a variant id,
    -- platform_product_id holds only one, and the variant is the dedupe key.
    -- NULL for marketplaces with no variant concept.
    variant_id    TEXT
);

-- Resume reads these: (keyword, lat, lon) for the keyword scrape, (lat, lon) for skus.
CREATE INDEX IF NOT EXISTS ix_snap_resume ON search_snapshots(keyword, lat, lon);
CREATE INDEX IF NOT EXISTS ix_sku_resume  ON sku_snapshots(lat, lon);
CREATE INDEX IF NOT EXISTS ix_listing_snap ON search_listings(snapshot_local_id);
"""


# ── lifecycle ────────────────────────────────────────────────────────────────

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL survives a hard kill with the committed rows intact — the whole point of
    # staging. NORMAL sync is the right trade here: an OS crash could lose the last
    # transaction, but the run is resumable anyway.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    # CREATE TABLE IF NOT EXISTS won't add columns to a file written by an older
    # build, so top them up — a staged run must stay readable (and loadable) across
    # upgrades. A file staged before the pack columns existed gains them here as NULL
    # (i.e. "not yet parsed"), which the loader then COPYs straight through.
    _add_missing(conn, "run",
                 [("stores_total", "INTEGER"), ("stores_done", "INTEGER"),
                  ("errors", "INTEGER"), ("skipped", "INTEGER"),
                  ("mp_slug", "TEXT")])
    _pack_cols = [("pack_raw", "TEXT"), ("pack_size", "REAL"),
                  ("pack_uom", "TEXT"), ("pack_count", "INTEGER")]
    _add_missing(conn, "search_listings", _pack_cols)
    _add_missing(conn, "sku_snapshots", _pack_cols)
    # Same forward-compat rule: a file staged before these existed gains them as
    # NULL, and the loader COPYs that straight through.
    _add_missing(conn, "sku_snapshots",
                 [("extra", "TEXT"), ("variant_id", "TEXT")])
    conn.commit()
    return conn


def _add_missing(conn: sqlite3.Connection, table: str, cols: list[tuple[str, str]]) -> None:
    """Add any of `cols` (name, sqlite_type) not already on `table` — the forward-
    compat top-up for staging files written by an older build."""
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, typ in cols:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def new_run(tenant_id, kind: str, mp_slug: str = DEFAULT_MP,
            job_id: str | None = None) -> dict:
    """Create a staging file for a new run and return its handle.

    `job_id` is generated LOCALLY (no DB round-trip) and only becomes a
    `scrape_jobs` row when the file is loaded — so an unloaded scrape leaves no
    phantom `running` job behind.

    The marketplace is part of the filename as well as a column: with two platforms
    staging into one directory, `cli scrape staged` needs to be readable at a glance.
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    jid = job_id or str(uuid.uuid4())
    tid = str(tenant_id)
    started = now_ist()
    path = STAGING_DIR / f"{kind}_{mp_slug}_{tid[:8]}_{started:%Y%m%d-%H%M%S}.sqlite3"
    conn = _connect(path)
    conn.execute(
        "INSERT INTO run (job_id, tenant_id, kind, mp_slug, started_at, status) "
        "VALUES (?,?,?,?,?,?)",
        (jid, tid, kind, mp_slug, started.isoformat(), "running"),
    )
    conn.commit()
    logger.info(f"staging: new run {kind}/{mp_slug} job={jid} -> {path.name}")
    return {"conn": conn, "path": path, "job_id": jid, "tenant_id": tid,
            "kind": kind, "mp_slug": mp_slug, "lock": asyncio.Lock()}


def open_run(path: Path | str) -> dict:
    """Re-open an existing staging file (resume, or load)."""
    path = Path(path)
    conn = _connect(path)
    row = conn.execute("SELECT * FROM run LIMIT 1").fetchone()
    if row is None:
        raise ValueError(f"{path.name}: no run row — not a staging file")
    return {"conn": conn, "path": path, "job_id": row["job_id"],
            "tenant_id": row["tenant_id"], "kind": row["kind"],
            "mp_slug": row["mp_slug"] or DEFAULT_MP,
            "lock": asyncio.Lock()}


def update_stats(stg: dict, stats: dict, stores_total: int | None = None) -> None:
    """Record run progress on the file so `scrape staged` can show whether it went
    well. Safe to call repeatedly; the orchestrators call it once at the end."""
    stg["conn"].execute(
        "UPDATE run SET stores_total=?, stores_done=?, errors=?, skipped=? WHERE job_id=?",
        (stores_total, stats.get("processed"), stats.get("errors"),
         stats.get("skipped"), stg["job_id"]),
    )
    stg["conn"].commit()


def finish_run(stg: dict, status: str = "success", error: str | None = None) -> None:
    stg["conn"].execute(
        "UPDATE run SET status=?, error=?, completed_at=? WHERE job_id=?",
        (status, error, now_ist().isoformat(), stg["job_id"]),
    )
    stg["conn"].commit()


def discard(path: Path | str) -> None:
    """Delete a staging file and its WAL sidecars. Irreversible — for an unloaded
    file this destroys scraped data that is nowhere else."""
    path = Path(path)
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if p.exists():
            p.unlink()
    logger.info(f"staging: discarded {path.name}")


def close(stg: dict) -> None:
    try:
        stg["conn"].close()
    except Exception:
        pass


def meta(stg: dict) -> dict:
    return dict(stg["conn"].execute("SELECT * FROM run LIMIT 1").fetchone())


def counts(stg: dict) -> dict:
    c = stg["conn"]
    return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("search_snapshots", "search_listings", "sku_snapshots")}


# ── writes (mirror blinkit/public_data/storage.py + sku_storage.py) ───────────

async def save_search(stg: dict, result: dict, tenant_id, job_id=None) -> int:
    """Stage one keyword search: a header row + its listings. Returns rows written.

    Field-for-field identical to what `bl_storage.save` would have INSERTed, so the
    loader is a straight copy (the one exception being `snapshot_id`, which Postgres
    assigns — see `snapshot_local_id`).
    """
    listings = result.get("listings", [])
    scraped_at = now_ist().isoformat()
    tid, jid = str(tenant_id), str(job_id or stg["job_id"])

    async with stg["lock"]:
        conn = stg["conn"]
        cur = conn.execute(
            """INSERT INTO search_snapshots
               (tenant_id, job_id, brand_slug, mp_slug, keyword, city, zone, pincode,
                lat, lon, merchant_id, scraped_at, brand_rank, brand_sov, total_results)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, jid, result["brand_slug"], stg["mp_slug"], result["keyword"],
             result.get("city", ""), result.get("zone", ""), result.get("pincode", ""),
             result.get("lat"), result.get("lon"), result.get("merchant_id", ""),
             scraped_at, result.get("brand_rank"), result.get("brand_sov_pct"),
             result.get("total_results")),
        )
        snap_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO search_listings
               (snapshot_local_id, tenant_id, job_id, mp_slug, brand_slug, keyword,
                city, zone, pincode, scraped_at, position, product_name, is_brand,
                price, mrp, discount_pct, pack_raw, pack_size, pack_uom, pack_count,
                in_stock, inventory, platform_product_id,
                merchant_id, merchant_type, is_combo, extra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(snap_id, tid, jid, stg["mp_slug"], l.get("brand_slug"), result["keyword"],
              result.get("city", ""), result.get("zone", ""), result.get("pincode", ""),
              scraped_at, l.get("position"), l.get("name", ""),
              int(bool(l.get("is_brand", False))), l.get("price"), l.get("mrp"),
              l.get("discount_pct"),
              _pk["pack_raw"], _pk["pack_size"], _pk["pack_uom"], _pk["pack_count"],
              int(bool(l.get("in_stock", True))),
              l.get("inventory"), l.get("product_id") or None,
              l.get("merchant_id") or "", l.get("merchant_type") or "",
              int(combo_from_pack(l.get("name", ""), _pk["pack_count"])),
              json.dumps({"group_id": l.get("group_id"), "unit": l.get("unit"),
                          "ptype": l.get("ptype"), "category": l.get("category"),
                          "match_reason": l.get("match_reason"),
                          "image_url": l.get("image_url")}))
             for l in listings for _pk in (pack_fields(l.get("unit")),)],
        )
        conn.commit()
    return 1 + len(listings)


async def save_skus(stg: dict, listings: list[dict], brand_slug: str, tenant_id,
                    job_id=None, *, merchant_id: str = "", city: str = "",
                    lat: float | None = None, lon: float | None = None) -> int:
    """Stage one store's own-brand listings. Mirrors `bl_sku_storage.save_skus`."""
    scraped_at = now_ist().isoformat()
    tid, jid = str(tenant_id), str(job_id or stg["job_id"])

    async with stg["lock"]:
        conn = stg["conn"]
        conn.executemany(
            """INSERT INTO sku_snapshots
               (tenant_id, job_id, mp_slug, brand_slug, platform_product_id,
                product_name, merchant_id, merchant_type, city, lat, lon, scraped_at,
                price, mrp, discount_pct, pack_raw, pack_size, pack_uom, pack_count,
                in_stock, inventory, rating, is_combo, extra, variant_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(tid, jid, stg["mp_slug"], brand_slug, l.get("product_id") or "",
              l.get("name", ""), l.get("merchant_id") or merchant_id,
              l.get("merchant_type") or "", city, lat, lon, scraped_at,
              l.get("price"), l.get("mrp"), l.get("discount_pct"),
              # pack_raw prefers the marketplace's ORIGINAL string where the
              # engine normalised `unit` into pack.py's grammar — otherwise the
              # audit trail would record our rewrite instead of what was served.
              l.get("unit_raw") or _pk["pack_raw"],
              _pk["pack_size"], _pk["pack_uom"], _pk["pack_count"],
              int(bool(l.get("in_stock", True))), l.get("inventory"), l.get("rating"),
              # `is_combo_hint` is the marketplace's own marker (e.g. Zepto's
              # COMBO uom, or a multiplier the size parse could not use). Falls
              # back to pack_count, then to the name regex.
              int(bool(l.get("is_combo_hint"))
                  or combo_from_pack(l.get("name", ""), _pk["pack_count"])),
              json.dumps(l["extra"]) if l.get("extra") else None,
              l.get("variant_id") or None)
             for l in listings for _pk in (pack_fields(l.get("unit")),)],
        )
        conn.commit()
    return len(listings)


# ── resume ───────────────────────────────────────────────────────────────────

def done_pairs(stg: dict) -> set[tuple]:
    """(keyword, lat, lon) already staged — the keyword scrape's resume set."""
    return {(r["keyword"], r["lat"], r["lon"]) for r in
            stg["conn"].execute("SELECT DISTINCT keyword, lat, lon FROM search_snapshots")}


def done_stores(stg: dict) -> set[tuple]:
    """(lat, lon) already staged — the targeted scrape's resume set."""
    return {(r["lat"], r["lon"]) for r in
            stg["conn"].execute("SELECT DISTINCT lat, lon FROM sku_snapshots")}


# ── discovery / retention ────────────────────────────────────────────────────

def _runs(kind: str | None = None, tenant_id=None, mp_slug: str | None = None) -> list[dict]:
    """Every staging file on disk, newest first, with its run row."""
    if not STAGING_DIR.exists():
        return []
    out = []
    for p in STAGING_DIR.glob("*.sqlite3"):
        try:
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM run LIMIT 1").fetchone()
            cnt = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                   for t in ("search_snapshots", "search_listings", "sku_snapshots")}
            conn.close()
        except Exception as e:
            logger.debug(f"staging: skipping {p.name} ({e})")
            continue
        if row is None:
            continue
        d = dict(row)
        d["path"] = p
        d["counts"] = cnt
        d["rows"] = sum(cnt.values())
        d["mp_slug"] = d.get("mp_slug") or DEFAULT_MP
        if kind and d["kind"] != kind:
            continue
        if tenant_id and d["tenant_id"] != str(tenant_id):
            continue
        if mp_slug and d["mp_slug"] != mp_slug:
            continue
        out.append(d)
    return sorted(out, key=lambda d: d["started_at"], reverse=True)


def list_runs(kind: str | None = None, tenant_id=None, mp_slug: str | None = None) -> list[dict]:
    return _runs(kind, tenant_id, mp_slug)


def pending(kind: str | None = None, tenant_id=None, mp_slug: str | None = None) -> list[dict]:
    """Runs not yet pushed to Postgres, newest first."""
    return [r for r in _runs(kind, tenant_id, mp_slug) if not r["loaded_at"]]


def all_runs(kind: str | None = None, tenant_id=None,
             mp_slug: str | None = None) -> list[dict]:
    """Every staging file with its run row and counts — loaded ones included.

    `pending()` deliberately hides loaded files, which is right for "what is left
    to push" but wrong for "tell me about THIS file": a --file target may well be
    one that is already loaded, and showing it as unknown/empty is worse than
    showing it as loaded.
    """
    return _runs(kind, tenant_id, mp_slug)


def resumable(kind: str, tenant_id, mp_slug: str = DEFAULT_MP) -> dict | None:
    """The newest unloaded, unfinished run for this tenant+kind+marketplace — what
    --resume continues. Mirrors the old `_latest_incomplete_job` DB query.

    The marketplace filter is not optional: without it a `--resume` on one platform
    would happily pick up the other's abandoned run and stage its rows under the
    wrong `mp_slug`.
    """
    for r in _runs(kind, tenant_id, mp_slug):
        if not r["loaded_at"] and r["status"] != "success":
            return r
    return None


def ref(path: Path | str) -> str:
    """The short handle shown in `cli scrape staged` and accepted by --file: the
    run's start time, e.g. `145458`. Date and kind are already columns in that table,
    so the full 45-char filename is redundant to type. `resolve()` substring-matches
    it back to the file."""
    stem = Path(path).name.replace(".sqlite3", "")
    return stem.rsplit("-", 1)[-1]


def resolve(token: str) -> Path:
    """Find a staging file from a full path, a filename, or any unique substring
    (typically the `ref` timestamp). Raises on no match or an ambiguous one."""
    p = Path(token)
    if p.exists():
        return p
    p = STAGING_DIR / token
    if p.exists():
        return p
    hits = [r["path"] for r in _runs() if token in r["path"].name]
    if not hits:
        raise FileNotFoundError(f"no staging file matching '{token}'")
    if len(hits) > 1:
        names = ", ".join(h.name for h in hits)
        raise ValueError(f"'{token}' matches {len(hits)} files: {names}")
    return hits[0]


def mark_loaded(path: Path | str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE run SET loaded_at=?", (now_ist().isoformat(),))
    conn.commit()
    conn.close()


def prune(tenant_id, kind: str, mp_slug: str = DEFAULT_MP,
          keep: int = KEEP_PER_KIND) -> list[Path]:
    """Delete the oldest LOADED files beyond `keep`, per (tenant, kind, marketplace).
    Unloaded files are never touched — losing one would lose an unpushed scrape.

    Scoped per marketplace so retention is `keep` runs of EACH platform, not `keep`
    runs shared between them (which would let a busy platform evict the other's
    history).
    """
    loaded = [r for r in _runs(kind, tenant_id, mp_slug) if r["loaded_at"]]
    removed = []
    for r in loaded[keep:]:
        try:
            r["path"].unlink()
            for suffix in ("-wal", "-shm"):
                sidecar = r["path"].with_name(r["path"].name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            removed.append(r["path"])
        except OSError as e:
            logger.warning(f"staging: could not prune {r['path'].name}: {e}")
    if removed:
        logger.info(f"staging: pruned {len(removed)} old {kind}/{mp_slug} file(s), kept {keep}")
    return removed


def parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
