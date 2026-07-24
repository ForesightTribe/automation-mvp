# Per-unit price — pack-size normalization

**Status: SHIPPED 2026-07-24.** Migration `a1c3e5f7b9d2` applied, both backfills run,
verified end-to-end (DB → API → frontend). See [Verification](#verification-2026-07-24)
and [Aftermath](#aftermath--what-the-backfill-cost) at the bottom.

Our public scrape captures each product's selling price and MRP, but a raw price is
not comparable across pack sizes: a `12 x 250 ml` multipack at ₹206 and a single
`225 ml` bottle at ₹73 sit in the same "cola" search, and averaging or ranking their
rupee prices is meaningless. This feature parses Blinkit's per-product `unit` string
into structured pack fields and derives a **per-unit price** — ₹ per 100 ml / 100 g /
piece — so different pack sizes compare fairly.

It also fixes a latent bug: `is_combo` was derived from the product *name*, which
misses ~13% of multipacks whose title doesn't say "pack of N". The unit string is the
reliable signal.

## The data

Blinkit stamps every product with a `unit` string inside the `cart_item` block — the
scraper has always extracted it (`scraper.py` → `unit`), but it was only ever kept
raw in `search_listings.extra` and dropped entirely for `sku_snapshots`. It is **100%
populated** and follows a tight grammar (validated against 289,873 real staged rows,
100% parsed):

```
unit  := term ( "+" term )*
term  := [ mult ("x"|"*") ] qty uom        # "12 x 250 ml", "225 ml"
```

Forms seen: single (`225 ml`, `13.5 g`, `1.2 ltr`), multiplier (`12 x 250 ml`),
additive (`225 ml + 225 ml + 225 ml`), and mixed (`2 x 225 ml + 225 ml`, a
Buy-2-Get-1).

## The model — four columns, per-unit price derived

On both `search_listings` and `sku_snapshots`:

| Column | Example (`2 x 225 ml + 225 ml`) | Meaning |
|---|---|---|
| `pack_raw` | `"2 x 225 ml + 225 ml"` | the source string, verbatim — the audit trail |
| `pack_size` | `675.0` | total content, normalized to one base unit |
| `pack_uom` | `"ml"` | the base unit — `ml` \| `g` \| `pc` |
| `pack_count` | `3` | number of physical items |

**Per-unit price is derived at read time (`price ÷ pack_size`), never stored** —
storing it would double the columns and go stale against any price correction.

Parsing lives in one place: [`scraper/utils/pack.py`](../backend/scraper/utils/pack.py)
(`parse_pack`, `pack_fields`, `per_unit_price`, `combo_from_pack`). Every writer
(scraper, staging, loader, backfill, explorer) goes through it, so backfilled history
and fresh rows are byte-identical.

### UOM families and the display basis

Tokens normalize into three families so `1 ltr` and `1000 ml` compare directly:

- volume → `ml` (from ml/l/ltr/litre)
- weight → `g` (from g/gm/kg/mg)
- count → `pc` (from pcs/piece/N/pack/…)

Display basis per family — **₹ per 100 ml**, **₹ per 100 g**, **₹ per piece**. Per-100
(not per-ml or per-litre) keeps this catalogue in a readable ~₹6–₹311 band where ₹/ml
underflows to indistinguishable `₹0.06` values and ₹/litre inflates a ₹42 snack to
"₹3,111/kg". It also matches Indian shelf labels. `per_unit_price()` and the frontend
`formatUnitPrice()` mirror the same basis; keep the two in sync.

### Comparability rules

1. **Never compare across `pack_uom`.** A ₹/100 g snack and a ₹/100 ml drink in one
   sorted column is nonsense. In practice a keyword returns one family
   (drinks-with-drinks); services group/label by `pack_uom` and sort per-unit only
   within a UOM.
2. **Heterogeneous combos → NULL size.** `60 g + 100 ml` has no single denominator:
   `parse_pack` returns `(None, "", 2)` — `pack_count` is trustworthy, but
   `pack_size`/`pack_uom` are empty and per-unit price is None. Honest blank over a
   fabricated number.
3. **Unparseable → all NULL but `pack_raw` kept.** A future parser improvement is a
   re-run of the backfill, never a re-scrape.

## Combos — `is_combo` re-derived from `pack_count`

`is_combo` now comes from `combo_from_pack(name, pack_count)`: `pack_count > 1` when
the unit parsed, falling back to the old name regex (`is_combo_name`) only when the
unit is empty/unparseable.

Evidence (cross-tab over 289,873 rows):

| name says combo | unit says multipack | rows |
|---|---|---|
| false | false | 201,601 |
| true | true | 49,609 |
| **false** | **true** | **38,573 ← the name missed these** |
| true | false | 0 |

The unit signal catches **38,573 multipacks the name misses** (e.g. `Bombay Banta
Masala Soda` = `12 x 250 ml`, `Lahori Nimboo Lime Soft Drink` = `24 x 160 ml`) and
disagrees the other way **zero** times — a strict improvement. ⚠️ Re-deriving on the
backfill flips ~13% of historical rows main→combo, so `kind=main` trend series shift
at the backfill boundary. Approved, but noted: it makes the numbers correct.

## What changed

**Schema** — `alembic/versions/a1c3e5f7b9d2_pack_size_columns.py`: adds the four
columns to both tables and **drops `grammage`** (the grams-only float added
2026-07-22, never populated; a single float can't represent the ~93% of this
catalogue measured in ml, nor pack count). Nullable/defaulted adds + one drop of a
wholly-NULL column — no table rewrite. **Applied 2026-07-24; it is the current head.**

**Scrape → load pipeline** — `blinkit/public_data/storage.py` + `sku_storage.py`
populate the columns (and keep `unit` in `extra`, so a future backfill can never be
starved — mirrors the merchant-column lesson in [darkstores.md](darkstores.md)).
`scraper/public/staging.py` mirrors the columns in both staged tables and tops up
files staged by an older build (so the currently-staged runs stay loadable);
`loader.py` COPYs them through.

**Backfill — done, scripts since deleted.** Two one-off scripts backfilled history on
2026-07-24 to 100% coverage on both tables, then were removed as spent (recoverable from
commit `b463535` if ever needed again):
- listings parsed `extra->>'unit'` directly.
- `sku_snapshots` has no local unit, so it was enriched from a `platform_product_id →
  unit` map built off `search_listings` — 100% of rows matched; unmatched ids would have
  stayed NULL rather than be guessed.

Both re-derived `is_combo`, touched only rows with an empty `pack_raw` (idempotent and
resumable, and could never blank a freshly-scraped row), and used temp-table + COPY +
`UPDATE … FROM` (the loader had already proved executemany is a trap). The listings run
died mid-way on a dropped pooler connection at 100k rows and resumed cleanly on re-run —
batches commit independently — which is why per-batch retry was added.

⚠️ **If a staging file predating 2026-07-24 is ever loaded**, its rows land with NULL
pack columns and would need that backfill rewritten. Prefer `cli scrape discard` for such
files unless the history is genuinely wanted.

**API** — additive on every endpoint:
- `reports_service.get_competition_report` — `sp_per_gram` → `unit_price` +
  `pack_size`/`pack_uom`/`pack_count`; competitor sort re-keyed to per-unit price.
  **Also rewritten to dedupe in SQL** (`DISTINCT ON (mp_slug, keyword, product_name)
  ORDER BY …, scraped_at DESC`). The previous shape fetched every matching listing and
  dropped duplicates in Python — **100,510 rows over the wire to build 124** (99.9%
  waste), slow enough that the pooler dropped the connection and the Reports
  → Competition page never loaded. Same semantics, same 124 rows; 0.5 s instead of
  never. This flaw predated the per-unit work; it just became visible once the page
  had live data worth loading.
- `competition_service.get_price_position` — keeps the raw-rupee band (absolute shelf
  price) and **adds** a per-unit band + `unit_uom` (the keyword's dominant UOM via
  `mode()`). Raw-price averaging across pack sizes was the core flaw; the per-unit
  band is the fix.
- `inventory_service.get_pricing` and `product_service.get_public_panel` — per-unit
  min/median/max alongside the rupee band (pack is constant per product, so each
  bound divides by the same `pack_size`).

**Explorer** — `_listing_row`/`_sku_row` carry the pack fields; `insights.py` adds a
per-unit band to the Price and Catalog insights; `export.py` adds per-unit columns to
the **Price & Discount** and **Own Catalog** insight sheets and pack columns to the
two raw sheets (Catalog SKUs had neither `unit` nor pack before).

**Frontend** — new `formatUnitPrice(value, uom)` in `lib/format.js` (2 decimals +
basis suffix; the shared `formatCurrency` is whole-rupees and can't be reused). The
Reports competition table swaps its dead Grammage/SP-per-gram columns for live
Pack/Per-unit and the index badge starts working; the competition Price-positioning
card, inventory Pricing card and product public panel each gain per-unit figures.

## Deployment order (matters — the VM runs `main` on a schedule)

1. Apply migration `a1c3e5f7b9d2` (adds columns, drops `grammage`).
2. Deploy code.
3. Run the backfills (`--apply`) once, after review of the dry-run coverage.

The migration must land **before** the loader code that COPYs into the new columns,
or `cli scrape load` fails on pending files. Staged files created before the code
deploy carry NULL pack columns until step 3.

## Verification (2026-07-24)

Schema: alembic head `a1c3e5f7b9d2`, zero `grammage` columns remaining.

| table | rows | pack_raw / size / uom / count |
|---|---|---|
| `search_listings` | 146,462 | **100%** all four |
| `sku_snapshots` | 35,802 | **100%** all four, 0 unmatched |

Consistency — all zero: rows with size but no uom, uom but no size, `pack_count > 1`
not flagged combo, `pack_count = 1` flagged combo. UOM split: 125,328 ml + 21,134 g.
`is_combo`: 45,952 true / 100,510 false.

All four endpoints exercised against live data, sub-second cold:
`reports/competition` 0.80 s · `competition/price-position` 1.20 s ·
`inventory/pricing` 1.61 s · `products/{id}/public` 0.92 s.

The comparison the feature exists for, now visible on the Reports page:

```
Dobra Blueberry Goli Soda            ₹73   225 ml ×1    ₹32.44 /100ml
Dobra Blueberry Goli Soda Pack of 3  ₹203  675 ml ×3    ₹30.07 /100ml
Lahori Nimboo Lime Soft Drink        ₹240  3840 ml ×24  ₹6.25  /100ml
Bombay Banta Black Jeera Masala      ₹188  3000 ml ×12  ₹6.27  /100ml
```

Dobra's sodas are ~₹33/100 ml against a competitor median of ₹12/100 ml — nearly 3×.
Raw prices hid that behind pack-size differences.

## Aftermath — what the backfill cost

**The backfill nearly filled the 500 MB Supabase free tier.** Postgres is MVCC: the
`UPDATE` on all 146k listings + 36k sku rows wrote a new version of every row and left
the old one dead, so both tables carried a full extra dead copy — on top of a large
pre-existing `DELETE` of pre-19-July data, which also frees nothing. The database hit
463 MB / 500 MB and started reporting "exceeding usage limits".

Reclaimed with `backend/scripts/reclaim_space.py` (REINDEX per index, then
`VACUUM FULL`): **463 MB → 172 MB**, `search_listings` 318 MB → 92 MB. The ordering
rules and traps live in that script's docstring and the Database Patterns section of
[CLAUDE.md](../CLAUDE.md).

**Lesson for the next bulk backfill on this DB:** budget for the table temporarily
doubling, check free space first, and plan the `VACUUM FULL` as part of the job — not
as a surprise afterwards.

## Not done (out of scope)

- Private seller/sales data has **no** pack size; per-unit price reaches sales views
  only through the `sku_map` bridge — separate work.
- `sku_map.unit` is still unpopulated (a freebie left for later).
- `competition_service.get_top_competitors.avg_price` has the same mixed-pack flaw as
  the old price-position band; flagged, not fixed here.
