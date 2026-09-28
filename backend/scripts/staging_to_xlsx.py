"""
Export a public-scrape staging file (SQLite) to an .xlsx for review BEFORE
`cli scrape load` pushes it to Postgres.

The staging file mirrors the three public tables field-for-field, so the sheets
here are exactly what the load would write — nothing is reshaped. Use it to eyeball
a first run on a new marketplace, or a suspicious one on an old marketplace, and
then either load it or `cli scrape discard` it.

Run from backend/:
    python -m scripts.staging_to_xlsx                      # newest staging file
    python -m scripts.staging_to_xlsx 115531               # any part of the filename
    python -m scripts.staging_to_xlsx --all                # every unloaded file

Output: next to the staging file, same name with .xlsx
Sheets: summary · review · own_brand · per_store  (readable)
        run · snapshots · listings · skus            (exact DB mirror)
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

STAGING = Path(__file__).parent.parent / "staging"


def _rows(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    cols = [r[1] for r in conn.execute(f"pragma table_info({table})")]
    return cols, conn.execute(f"select * from {table}").fetchall()


def _sheet(wb, name: str, cols: list[str], rows: list[tuple]) -> None:
    ws = wb.create_sheet(name)
    ws.append(cols)
    for i in range(1, len(cols) + 1):
        ws.cell(1, i).font = Font(bold=True)
    for r in rows:
        ws.append([json.dumps(v) if isinstance(v, (dict, list)) else v for v in r])
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = min(48, max(10, len(c) + 2))
    ws.freeze_panes = "A2"


def export(path: Path) -> Path:
    conn = sqlite3.connect(path)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    for table, sheet in (("run", "run"), ("search_snapshots", "snapshots"),
                         ("search_listings", "listings"), ("sku_snapshots", "skus")):
        cols, rows = _rows(conn, table)
        # `extra` is JSON text in SQLite; expand it into columns so it is readable.
        if "extra" in cols and rows:
            ei = cols.index("extra")
            keys: list[str] = []
            parsed = []
            for r in rows:
                try:
                    d = json.loads(r[ei]) if r[ei] else {}
                except Exception:
                    d = {}
                parsed.append(d)
                for k in d:
                    if k not in keys:
                        keys.append(k)
            cols = cols[:ei] + cols[ei + 1:] + [f"extra.{k}" for k in keys]
            rows = [r[:ei] + r[ei + 1:] + tuple(d.get(k) for k in keys)
                    for r, d in zip(rows, parsed)]
        _sheet(wb, sheet, cols, rows)

    lcols, lrows = _rows(conn, "search_listings")
    ix = {c: i for i, c in enumerate(lcols)}

    # ── review: what a person cross-checks against the app ──────────────────
    # One row per product as it appeared, sorted keyword -> store -> rank, with
    # only the columns you can see on a phone: the raw sheets above stay as the
    # exact database mirror.
    def _extra(r):
        try:
            return json.loads(r[ix["extra"]]) if r[ix["extra"]] else {}
        except Exception:
            return {}
    review_cols = ["keyword", "store_id", "area", "pincode", "rank", "product", "brand",
                   "own?", "ad?", "price", "mrp", "off%", "in stock", "cart limit",
                   "cart limit msg", "confidence", "bestseller", "scraped_at"]
    review = []
    for r in lrows:
        e = _extra(r)
        review.append([
            r[ix["keyword"]], r[ix["merchant_id"]], r[ix["zone"]], r[ix["pincode"]],
            r[ix["position"]], r[ix["product_name"]], r[ix["brand_slug"]],
            "OWN" if r[ix["is_brand"]] else "", "AD" if r[ix["is_ad"]] else "",
            r[ix["price"]], r[ix["mrp"]], r[ix["discount_pct"]],
            "yes" if r[ix["in_stock"]] else "NO",
            e.get("cart_limit"), e.get("cart_limit_msg"), e.get("confidence"),
            "yes" if e.get("bestseller") else "", (r[ix["scraped_at"]] or "")[:19],
        ])
    review.sort(key=lambda x: (x[0], str(x[1]), x[4] or 0))
    _sheet(wb, "review", review_cols, review)
    ws = wb["review"]
    for i, w in enumerate([20, 10, 22, 9, 6, 52, 22, 6, 5, 8, 8, 6, 8, 10, 40, 16, 10, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # own brand only, one line per placement, for the fastest cross-check:
    # "at this store, for this keyword, where are we and are we paying for it?"
    own = [x for x in review if x[7] == "OWN"]
    _sheet(wb, "own_brand", review_cols, own)
    ws = wb["own_brand"]
    for i, w in enumerate([20, 10, 22, 9, 6, 52, 22, 6, 5, 8, 8, 6, 8, 10, 40, 16, 10, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # per store: how many keywords Brik Oven shows up for, and best rank
    scols, srows = _rows(conn, "search_snapshots")
    sx = {c: i for i, c in enumerate(scols)}
    per_store: dict[str, dict] = {}
    for r in srows:
        d = per_store.setdefault(r[sx["merchant_id"]], {
            "area": r[sx["zone"]], "pincode": r[sx["pincode"]], "keywords": 0,
            "with_own": 0, "best": None, "sov": []})
        d["keywords"] += 1
        if r[sx["brand_rank"]]:
            d["with_own"] += 1
            d["best"] = r[sx["brand_rank"]] if d["best"] is None else min(d["best"], r[sx["brand_rank"]])
        if r[sx["brand_sov"]] is not None:
            d["sov"].append(r[sx["brand_sov"]])
    store_rows = [[sid, d["area"], d["pincode"], d["keywords"], d["with_own"],
                   d["best"], round(sum(d["sov"]) / len(d["sov"]), 1) if d["sov"] else None]
                  for sid, d in sorted(per_store.items(), key=lambda kv: kv[1]["area"] or "")]
    _sheet(wb, "per_store", ["store_id", "area", "pincode", "keywords searched",
                             "keywords with own brand", "best own rank", "avg own SoV %"],
           store_rows)

    # ── summary ──────────────────────────────────────────────────────────────
    ws = wb.create_sheet("summary")
    ws.append(["keyword", "stores", "rows", "own rows", "own ads", "competitor rows",
               "stores with own brand", "avg own rank"])
    for i in range(1, 9):
        ws.cell(1, i).font = Font(bold=True)
    by_kw: dict[str, dict] = collections.defaultdict(
        lambda: {"stores": set(), "rows": 0, "own": 0, "ads": 0, "comp": 0,
                 "own_stores": set(), "ranks": []})
    by_brand = collections.Counter()
    for r in lrows:
        k = by_kw[r[ix["keyword"]]]
        k["stores"].add(r[ix["merchant_id"]])
        k["rows"] += 1
        if r[ix["is_brand"]]:
            k["own"] += 1
            k["own_stores"].add(r[ix["merchant_id"]])
            k["ranks"].append(r[ix["position"]] or 0)
            if r[ix["is_ad"]]:
                k["ads"] += 1
        else:
            k["comp"] += 1
        by_brand[r[ix["brand_slug"]]] += 1
    for kw in sorted(by_kw):
        k = by_kw[kw]
        ws.append([kw, len(k["stores"]), k["rows"], k["own"], k["ads"], k["comp"],
                   len(k["own_stores"]),
                   round(sum(k["ranks"]) / len(k["ranks"]), 1) if k["ranks"] else None])
    ws.append([])
    ws.append(["brand_slug", "rows"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for slug, n in by_brand.most_common():
        ws.append([slug, n])
    for i, w in enumerate([24, 8, 8, 10, 9, 16, 22, 13], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    out = path.with_suffix(".xlsx")
    wb.save(out)
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("token", nargs="?", help="part of the staging filename (default: newest)")
    ap.add_argument("--all", action="store_true", help="every unloaded staging file")
    a = ap.parse_args()

    files = sorted(STAGING.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime)
    if a.token:
        files = [p for p in files if a.token in p.name]
    elif not a.all:
        files = files[-1:]
    if a.all:
        files = [p for p in files if not sqlite3.connect(p).execute(
            "select loaded_at from run").fetchone()[0]]
    if not files:
        print("no matching staging file")
        return
    for p in files:
        out = export(p)
        conn = sqlite3.connect(p)
        n_snap = conn.execute("select count(*) from search_snapshots").fetchone()[0]
        n_list = conn.execute("select count(*) from search_listings").fetchone()[0]
        n_sku = conn.execute("select count(*) from sku_snapshots").fetchone()[0]
        print(f"{out.name}: {n_snap} snapshots, {n_list} listings, {n_sku} skus")


if __name__ == "__main__":
    main()
