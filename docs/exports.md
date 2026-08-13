# Exports — Standardized Data → Excel

One way to turn stored Foresight data into a client-ready `.xlsx`. Public data
first; the layer is built so marketing/seller/ads sections slot in later and so a
dashboard **Download Excel** button is wiring, not a rewrite.

> Status: **Phases 1–7 shipped 2026-08-10.** `cli export public` builds a
> complete 13-sheet client workbook from stored data (11 insight sections, all
> cross-checked against the read services), and `cli export raw` dumps the
> underlying rows to CSV as a **separate** command. Explorer now renders through
> the same writer, at **sheet parity** since 2026-08-11 (same dark-store grain,
> same sheet order). Remaining: the download endpoint (Phase 8), and the
> **Marketing & Ads + Sales & Operations reports** — planned below, gated on two
> small renderer additions.

> **Why "Exports" and not "Reports".** `Reports` already means the three rebuilt
> client Excel _views_ (sales pivot / marketing / competition — `/reports/*`,
> `reports_service.py`, [reports-views](dashboard-views.md)). This subsystem is the
> **workbook rendering layer**; those views are one future consumer of it.

---

## What's wrong today

| Today | Problem |
|---|---|
| ~~`build_public_analysis.py`, `build_sku_analysis.py`~~ — **deleted 2026-08-10** | Hardcoded Dobra tenant UUID + hardcoded 14-SKU catalog dicts. Not runnable for a second client. Rebuilt from scratch, not ported. |
| `export_to_excel.py` (backend root, kept for now) | A raw dump of the **private** marketing/seller tables. Out of scope for a public report — retire it only when a private report replaces it. |
| Each script had its own `style_header` / `autofit` / `write_table` | Divergent looks, several places to fix one bug. |
| Each re-derived its own SQL for Reach / SoV / combo split | Free to silently disagree with the dashboard. This is why they couldn't be trusted as client deliverables. |
| [explorer/export.py](../backend/scraper/public/explorer/export.py) is good but welded to a live ad-hoc scrape | Can't export a real client's stored data. |
| No download endpoint anywhere | Nothing for a button to call. |

---

## Locked decisions

| Fork | Decision | Why |
|---|---|---|
| Source | **Stored DB data** for the selected window | Matches the dashboard, exports in seconds, is what a Download button needs. Live ad-hoc scrape → Excel is already **Explorer**; these two stay separate. |
| Numbers | **Reuse the existing read services** — no new SQL in a section | An export that disagrees with the screen is worse than no export. Services already carry store grain, per-unit price, main-vs-combo, the `merchant_id != ''` filter. **One documented exception:** Product Families needs family × store grain, which no service exposes, so it projects `inventory_service._latest_per_store` — the service's own subquery, different columns. No filter or business rule is re-derived. |
| Raw data | **A separate CLI command writing CSV** — never bundled into the report | One 7-day window is ~300k rows / 79 MB. A download button must not ship that, and nobody wants it every time. Decided 2026-08-10. |
| Surface | **CLI now, API later** — one service layer both call | Same path Explorer took; the endpoint becomes wiring. |
| Legacy | **Deleted, rebuilt fresh** — no port, no parity gate | The old scripts carried a hardcoded catalog and their own SQL. Only the _idea_ of the family rollup survives; the code does not. |
| Renderer | **One shared writer**; Explorer refactored onto it | "Standardized" means one look and one bug-fix site, not a second good script. |
| Readability | **A declared design system**, enforced by the writer | Sheet authors declare _semantics_ (this column is a count / a percentage / money); the writer owns every width, format, colour and alignment. Nobody hand-styles a cell. |
| Vocabulary | **Business terms only**, enforced by a generated glossary | See _Clarity rules_ — this is a correctness requirement, not polish. |

---

## Architecture

Mirrors Explorer's proven layering, sourced from the DB instead of a scrape:

```
ReportSpec (Pydantic)                    ← app/schemas/exports.py
   tenant, marketplace, start/end, cities, kind(main|combo|all),
   sections[], label                      doubles as the future POST/GET body
        │
build_report(db, spec) → Report          ← exports/build.py
        │   runs each requested section from the registry; each section calls the
        │   EXISTING read services and returns a typed Section:
        │   title, description, columns[], rows[], notes[]
        ├──────────────────────────────┐
        ▼                              ▼
write_workbook(report, path)      (future) GET …/exports/public → JSON or .xlsx
   exports/workbook.py           the SAME Report object, rendered differently
```

`Report` is renderer-agnostic: a `Section` carries its own title, one-line
description, typed columns and rows. The Excel writer only formats — **no
aggregation in the writer**, same rule Explorer follows.

### Package layout

```
backend/exports/
  workbook.py      # the generic openpyxl renderer — owns ALL styling
  theme.py         # the palette, fonts, number formats, width table (below)
  build.py         # build_report(db, spec) → Report — cover, runner, glossary
  registry.py      # SECTIONS: key → builder fn  (the single extension point)
  glossary.py      # TERMS + LABELS + check_wording (the enforcement)
  sources.py       # memoized service reads, scoped to one run
  text.py          # window / freshness / context-line phrasing
  sections/
    shelf.py       # on-shelf / in-stock / stores / cities / needs-attention
    visibility.py  # SoV, rank matrix, competitors, price vs position
    pricing.py     # price band, per-unit band, store price differences
    families.py    # product-family rollup
  raw.py           # RAW DATA -> streamed CSV. Not a section, not a sheet.
backend/scraper/public/explorer/export.py   # adapter: ExplorerInsights -> Report
backend/app/schemas/exports.py    # ReportSpec, Report, Section, Column (API contracts)
backend/cli/commands/export.py    # cli export public | raw | sections | sample
backend/out/                      # generated artifacts, gitignored
```

Functions, not classes, throughout — sections are module-level async functions in
a dict registry, per [code-standards](code-standards.md).

### The section registry

One entry per sheet. Adding a section — or a whole new report family (marketing,
seller, ads) — is one dict entry, exactly like [jobs/types.py](../backend/jobs/types.py):

```python
register("sku_shelf", group="public", build=sku_shelf,
         terms=("on_shelf", "in_stock", "discount"))
```

A builder is `async (db, spec) -> Section | None`; returning `None` means "no data
in this window" and the sheet is dropped rather than rendered empty. `terms` are
the glossary keys the sheet relies on — they are collected into "How to read
this", so a sheet cannot use a word the glossary does not define. **Registration
order is sheet order**, so modules are imported in reading order.

`--sections` picks a subset; the default is every `public` section. A future
per-view Download button passes exactly one key.

---

## Workbook design system

The reason the old scripts looked like scripts is that each sheet styled itself.
Here a **column declares what it _is_**, and `workbook.py` decides how it looks —
so every sheet in every report lines up without anyone thinking about it.

```python
Column(key="stores_listed", header="Stores stocking it", type="count",
       help="Distinct dark stores where this SKU appeared at all.")
```

`type` drives number format, alignment, width bounds and emphasis. The eight types:
`text · id · count · pct · money · money_fine · rating · date`.

### Palette — subtle by construction

No fill is more saturated than ~10%. It reads as paper with structure, not a
dashboard, and it survives black-and-white printing.

| Role | Hex | Used for |
|---|---|---|
| Ink | `#1F2933` | all primary text |
| Muted | `#6B7280` | descriptions, context line, `—` placeholders |
| Header fill | `#EEF2F6` | header row (dark text on light — **not** white-on-navy) |
| Rule | `#CBD5E1` | the single medium border under the header |
| Hairline | `#E5E7EB` | horizontal row separators only — no vertical borders |
| Band | `#FAFBFC` | alternating row stripe |
| Accent | `#2F5D8C` | sheet titles, insight tab colour, data bars |
| Own-brand tint | `#F2F7FC` | rows that are the client's own product |
| Good / Warn / Bad | `#E7F3EA` / `#FDF3E0` / `#FBEBEA` | status chip fills (text `#2F6B45` / `#8A5A18` / `#9B3E38`) |

### Every sheet has the same skeleton

```
A1   Sheet Title                                    13pt semibold, ink      (row h 22)
A2   One plain-English line saying what this is.    10pt, muted             (row h 16)
A3   1–7 Aug 2026 · Main SKUs · 5,090 stores observed   9.5pt, muted        (row h 14)
A4   (spacer)                                                               (row h 6)
A5   HEADER ROW — wrapped, frozen                                           (row h 30)
A6+  data
```

Plus a `← Contents` hyperlink parked at the right end of row 1, and the
freeze split at `B6` when column A is the row label — so the SKU name stays
visible while scrolling right through 15 metric columns.

### The rules the writer enforces

- **Gridlines off** (`sheet_view.showGridLines = False`) on every sheet. This is
  the single biggest lever on perceived quality — the hairlines carry the
  structure instead.
- **Widths are computed, then clamped per type.** Width = `clamp(max(len(header),
  p90(len(values))) + 3, min, max)`. Using the **90th percentile, not the max**,
  means one 90-character product name no longer blows a column to the cap and
  pushes everything else off-screen.

  | type | min | max | align |
  |---|---|---|---|
  | `text` | 18 | 42 | left |
  | `id` | 12 | 16 | left |
  | `count` | 10 | 14 | right |
  | `pct` | 10 | 13 | right |
  | `money` | 11 | 14 | right |
  | `money_fine` | 11 | 15 | right |
  | `rating` | 9 | 11 | right |
  | `date` | 12 | 12 | centre |

- **Headers align with their data** — a right-aligned number column gets a
  right-aligned header. Mismatched alignment is what makes a table look wonky.
- **Number formats**: `#,##0` counts · `0.0"%"` percentages (values are already
  0–100, so the format shows the sign without a silent ×100) · `₹#,##0` money ·
  `₹#,##0.00` per-unit money · `0.0` rank/rating · `dd mmm yyyy` dates.
- **Empty is `—`, not blank.** A muted em dash says "no data"; an empty cell reads
  as zero. This is a clarity rule, not a cosmetic one.
- **Emphasis without traffic lights.** Light-blue **data bars** on count columns,
  a **two-colour** scale (white → soft green, or white → soft red) on percentage
  columns — no harsh red-yellow-green. The three-colour scale appears exactly once,
  on the Rank by Keyword × City grid, because finding weak cells is that sheet's
  entire job.
- **Banded rows** at `#FAFBFC`, and own-brand rows tinted `#F2F7FC`.
- **AutoFilter on every table header**, so a client can slice without asking us.
- **Totals go in a bold, top-bordered last row** labelled `Overall` — never
  floating mid-table.
- **Print-ready**: landscape, fit-to-width 1 page, header row repeated on every
  printed page, footer `Sheet name · Page X of Y`, 0.4" margins. Clients print these.
- **Tab colours group the workbook**: cover + glossary slate `#1F2933`, insight
  sheets accent `#2F5D8C`.
- **Sheet names are sanitized** — ≤31 chars, Excel's illegal `[]:*?/\` stripped,
  duplicates suffixed. A crash at `wb.save()` over a sheet name is a stupid way to
  lose a five-minute report.

### Seeing it without a database

`cli export sample -o preview.xlsx` renders a fixture `Report` exercising every
column type, both colour scales, a totals row, a status chip and an empty cell —
no DB, no scrape. The visual design gets iterated in seconds instead of minutes,
and it doubles as the renderer's regression check.

### What the first real render taught us

Findings from rendering the fixture and opening it in Excel — each of these was a
visible defect, not a theory:

- **A wrapped header needs a taller row than you think.** At the original 30pt,
  Excel silently clipped the second line and headers read as truncated ("Stores
  with st"). Header rows are 34pt, and the numeric width caps went up ~2 so the
  **autofilter dropdown** stops eating the last characters of a header.
- **`wrap_text` alone does nothing to row height.** Excel auto-fits a wrapped row
  only when it computes the height itself, which it never does for rows openpyxl
  wrote — so a wrap column clips. Heights are set explicitly, and only when the
  text *actually* overflows: an Excel width unit is the width of `0`, and
  lowercase prose is ~15% narrower per character, so a naive character count
  claims a second line for text that plainly fits.
- **Excel right-aligns numbers by default**, which left the cover's `5,090`
  floating away from the text values above it. Cover values are force-aligned.
- **A `datetime` skipped the number format** (the guard only tested `int/float`),
  so date columns showed `2026-08-01 00:00:00`. Dates are now formatted.
- **A totals row must blank its non-applicable cells, not dash them.** A `—`
  under Product ID implies missing data; a total simply has no product id.
- **Highlighting every row says nothing.** The own-brand tint was originally on
  the own-SKU sheet, where all rows are own. It belongs on mixed lists
  (competitors), and the fixture demonstrates it there.
- **A fixed header height clips two-line headers**, and a clipped header reads as
  a different metric — "Stores with none left" rendered as "Stores with none l".
  Header height is now derived from how many lines each header needs at its
  computed width. Prefer a short header with the precision in the hover help:
  "Out of stock" beats a wrapped sentence.

Verified end to end: the workbook opens in real Excel with **no repair prompt**,
lands on Contents, and every sheet renders with gridlines off, frozen headers,
working internal hyperlinks and header hover-comments.

### What building the real sections taught us

Two of these were live defects caught by cross-checking the workbook against the
services rather than by reading the code:

- **Do not re-derive a metric you can ask for.** Search Visibility originally
  rolled position up from the keyword × city grid, weighted by each cell's search
  count. Wrong denominator: the service averages position over the searches where
  the brand *appeared*, while the grid's count includes searches where it did not.
  On high-visibility terms the two agreed, which is what makes it dangerous — the
  error only showed on the weak terms, reporting 12.2 against a true 11.81 for
  "soda". It now calls `get_share_of_voice` per term and matches exactly.
- **A heatmap needs ONE scale across the whole grid.** Applying the colour rule
  per column rescales to each column's own min and max, so an average position of
  5 renders green in a city ranging 1–35 and red in one ranging 1–5. On a "where
  am I weak" map that inverts the message. `_heat_block` now writes a single rule
  over the whole block.
- **The same query behind two sheets is two queries.** Shelf Summary and Product
  Shelf Presence both need `get_distribution`; Search Visibility and the grid both
  need `get_rank_matrix`. `sources.py` memoizes on the session's `info` dict —
  created and discarded with the session, so nothing survives to go stale. Full
  build went 40 s → 29 s.
- **Percentages are 0–100 in these services, not fractions.** `brand_sov` of 3.3
  with 30 results means 3.3%. The `pct` type's `0.0"%"` format matches that; using
  Excel's native `0.0%` would have reported 330%.
- **Blank is a real answer.** Four of nine search terms have no competitor price
  at all in the window, so "Price vs Competitors" shows `—` rather than a zero or
  a fabricated band.

---

## The public workbook

**Cover — "Report"**
Client, marketplace, date window (the _selected_ dates), cities, Main/Combo filter,
**data freshness** ("scraped 3 days ago, 2026-08-07"), stores observed, SKUs
observed, keywords covered — then a contents list, one line per sheet, each an
internal hyperlink.
Freshness is mandatory: public data is weekly, and a client will otherwise read a
stale number as live.

**How to read this** — the generated glossary (below).

**Insight sheets**

| # | Sheet (as it ships) | Source |
|---|---|---|
| 1 | **Shelf Summary** ✅ — headline KPIs, each with the counts behind it | `get_distribution` |
| 2 | **Product Shelf Presence** ✅ — per product: stores carrying it, in stock, out of stock, price, discount | `get_distribution` |
| 3 | **City Shelf Presence** ✅ — the same lenses per city | `get_cities` |
| 4 | **Store Shelf Presence** ✅ — per store (id, name, tier, city), worst first | `get_stores` |
| 5 | **Needs Attention** ✅ — every gap, with a Problem chip naming which team owns it | `get_actions` ×2 |
| 6 | **Availability Trend** ✅ — weekly in-stock % | `get_availability_history` |
| 7 | **Price Spread** ✅ — per product: cheapest / typical / dearest store + per-unit band | `get_pricing` |
| 8 | **Search Visibility** ✅ — per term: share of search, average position, strongest/weakest city | `get_share_of_voice` + `get_rank_matrix` |
| 9 | **Position by Search Term and City** ✅ — the weakness grid | `get_rank_matrix` |
| 10 | **Top Competitors** ✅ — who keeps appearing in your searches | `get_top_competitors` |
| 11 | **Price vs Competitors** ✅ — your band against the market band, per term | `get_price_position` |
| 12 | **Product Families** ✅ — singles + their multipacks counted as one product | projects `_latest_per_store` |

Three names drifted from the original plan, deliberately:

- **"Price Spread"**, never "price distribution" — in this codebase *distribution*
  means the in-stock rate, and the wording guard rejects the word outright.
- **"Product Shelf Presence"**, not "SKU" — *SKU* is our word, not the client's.
- **Needs Attention is one filterable table with a Problem chip**, not two stacked
  blocks. Same information, and it suits how the sheet is actually used: sort and
  filter. The note and the chip colours keep the two problems distinct, and the
  sheet says explicitly never to add them together.

**No raw sheets.** The underlying rows are a separate command — see *Raw data*.

---

## Raw data (`cli export raw`)

The rows behind the report, streamed to **CSV**, on demand only.

Why it is not in the workbook: one 7-day window of one client is **300,861 rows /
79 MB** (194k search listings, 85k own-product readings, 18k searches, 3k stores).
Bundling that into the report would make the eventual Download button ship eighty
megabytes nobody asked for, every time. The report is a readable deliverable; this
is a data dump. Different shape, different format, different audience.

| Key | File | What it is |
|---|---|---|
| `sku` | `own_products_by_store.csv` | One row per own product per dark store per scrape — price, stock, pack |
| `listings` | `search_listings.csv` | Every product seen in a search, yours and competitors'. The biggest table |
| `searches` | `searches.csv` | One row per search at one probe point — rank, share of search, result count |
| `stores` | `store_catalogue.csv` | The dark-store catalogue: id, name, city, coordinates |

**CSV, not xlsx, deliberately.** At this volume a styled workbook is the wrong
container: openpyxl holds every cell in memory, none of the design system means
anything on a raw dump, and Excel opens CSV natively. Supporting `.xlsx` here
would mean a second Excel writer — the exact thing this subsystem exists to avoid.
Use `--limit` for a sample small enough to eyeball.

Implementation notes that matter:

- **Keyset paging, not a server-side cursor.** Rows are read in 10k chunks with
  `WHERE id > last ORDER BY id LIMIT n`. Every table has a monotonic integer key,
  and keyset paging behaves identically through a connection pooler, where
  streaming cursors can quietly fail. Verified against the database: exact row
  counts on every table, zero duplicates, zero gaps.
- **`utf-8-sig`, not plain UTF-8.** Excel on Windows assumes the system codepage
  for a BOM-less `.csv`, which turns ₹ and every accented product name into
  mojibake.
- **`extra` is excluded by default** (`--include-extra` to include it). It is the
  scraper's untyped payload — ~284 bytes a row, over half of each listing, mostly
  an image URL. Including it roughly triples the file.
- **Counts print before anything is written**, and `--dry-run` stops there. The
  volume is the thing worth knowing before you commit to it.
- **The store catalogue is not date-scoped**, so it survives a window with no
  scrape data at all. Writing it alone would report "wrote 3,288 rows" for an
  empty window, so that is refused unless `--tables stores` asked for it.

---

## Explorer shares the writer

`explorer/export.py` no longer draws anything: it maps `ExplorerInsights` onto a
`Report` and calls the same `write_workbook`. One writer, so a fix to widths,
colours or print setup lands in both, and the vocabulary guard applies to both.

Two things the shared layer forced, and both were improvements:

- **Explorer's old sheets said "SoV %" and "Reach %".** `check_wording` rejects
  them, so they now read "Share of search %" and "On shelf %". That drift between
  two of our own workbooks is exactly what a shared writer is for.
- **Explorer counts LOCATIONS, not stores.** It samples probe points and never
  resolves them to dark stores, so the client report's store wording would be
  false there. `collect(..., core=())` lets it opt out of "Stores observed" and
  "Freshness" (it is scraped live) and take a `Location` term instead.

Explorer was brought to **sheet parity** on 2026-08-11 — same grain (dark
stores), same sheet order, same vocabulary, 12 insight sheets against the client
report's 11. It cannot have Availability Trend: one run is one point in time. Its
denominator differs and says so — Explorer samples, so "stores seen in this run",
not "every store that answered". See [explorer.md](explorer.md).

`Section.dense` was added for Explorer's captured sheets: skip per-cell banding,
borders and conditional formatting on a long sheet, keeping headers, widths and
freeze. It is a **rendering-cost** switch, not the raw-data concept returning —
5,000 captured rows render in 2.5 s with it.

---

## Clarity rules (the "clear terms" requirement)

Enforced in `glossary.py` and the column definitions, not left to whoever writes a
sheet:

1. **Never print "Reach" or "Distribution".** In FMCG, _numeric distribution_
   means breadth — the **opposite** of this codebase's `distribution_pct`
   (in-stock rate). A sales reader reads both headline metrics backwards. Sheets
   say **"On shelf"** (breadth) and **"In stock"** (health). The API keeps its
   field names; the mapping lives in one place.
2. **Never a bare percentage** — the counts sit beside it as their own sortable
   columns: `Stores stocking it | Stores observed | On shelf %`.
3. **Never mix units in one KPI block** — store counts and store×SKU gap counts in
   the same strip read as a contradiction.
4. **Every sheet carries a one-line description** under its title, in the client's
   language, and a formula where one exists.
5. **Every column carries a `help` string**, surfaced as an Excel cell comment on
   the header and as a row on the glossary sheet. Hovering a header answers "what
   is this?" without leaving the file.
6. **The caveats ship with the numbers.** The glossary states _"absent is not out
   of stock"_ (a missing SKU may be not-carried **or** past the scrape cap — from
   outside they're indistinguishable), that `N` is stores **observed** and never
   the full catalogue, and that the trend sheet is anchored to now while every
   other sheet uses the selected window.
7. **One wording source.** Glossary text is lifted from
   [public-glossary.md](public-glossary.md) so the doc, the UI and the workbook
   can't drift. It lives in `exports/glossary.py`, and the fixture reads
   the same dict — there is no second copy to fall out of date.
8. **The rules are enforced, not merely written down.** `glossary.check_wording`
   runs over every section before it renders and **raises** if a title,
   description, KPI label or column header says *reach*, *distribution*, *SoV*
   or *merchant*, naming the replacement. A leak is a correctness bug — a reader
   who sees "distribution" understands the opposite of what the number means —
   so it fails the build rather than warning. `LABELS` holds the single
   translation from internal field name to client wording.

---

## Product families

Multipacks and promo variants roll up to the core product ("Nimbu Masala Soda"
single + Pack of 2 + Pack of 3 + B2G1 = one flavour). This matters because the
catalog has largely migrated singles → multipacks: per-SKU numbers alone make a
healthy brand look like it's losing shelf.

Built fresh, without a hardcoded catalog (`sections/families.py`):

- **Derived from the product name**, with promo and pack wording stripped ("Buy 2
  Get 1 Free", "Pack of 3", "2 x", "value pack"), the brand prefix removed, and
  `Chips / Crisps` folded together with `Chips /Crisps`.
- **The derived grouping is printed** in a "What was grouped" column, so a wrong
  call is visible and challengeable rather than silent.
- **Multi-flavour bundles are excluded, not merged** — "Nimbu Masala + Blueberry
  Combo" is not a variant of either flavour, and folding it in would credit one
  flavour with a sale of two. They are counted in a note instead. The bundle test
  runs *after* the promo wording is stripped, so "Buy 2 Get 1 Free" (one flavour)
  is never mistaken for one.
- **This sheet always reads every product, singles and multipacks**, whatever
  `--kind` the rest of the report uses. Honouring a `main`-only filter would hide
  the multipacks and defeat the entire sheet — a promo multipack is `is_combo`.
- **Stores are unioned, never summed.** A store carrying both the single and the
  2-pack is one store on the shelf. Verified on Dobra: the Nimbu Masala family
  shows 2,023 stores carrying any against 2,028 store-product listings — five
  stores carry both, and summing would have invented five stores.
- **Override later, only if needed.** If auto-derivation proves wrong in practice,
  the fix is a `families` sheet in `config.xlsx` applied by `cli sync` — matching
  the existing config-workbook pattern. That needs a table + migration, so it is
  **not** in the first cut and would be confirmed before running.

> **On today's Dobra catalogue this sheet is nearly a no-op, and says so.** Of 33
> products there are 15 singles and 18 combos, but 17 of those combos are
> multi-flavour bundles; only one ("Buy 2 Get 1 Free") is a same-flavour
> multipack. So 14 of 15 families have exactly one variant, and the sheet prints a
> warning to that effect rather than implying it did something. It earns its keep
> when the catalogue repacks — which it did as recently as July.

---

## Next: Marketing & Sales exports (PLANNED)

Two reports, not one. They answer different questions for different people —
"is my spend working" is a marketing conversation, "what sold and can we supply
it" is a commercial/ops one — and merging them produces a workbook where neither
reader finds their half.

Both are **daily and current** (ads and seller data ran to 10–11 Aug while public
was a week stale), so they default differently from the public report and must
never be presented as sharing an as-of date.

### Locked decisions

| Fork | Decision | Why |
|---|---|---|
| Split | **Two reports** — `export ads`, `export sales` | Different audiences, different cadences. |
| Money | **Indian grouping** — `₹23,03,950` | The audience reads in lakh/crore. The public report never hit this because its numbers were ₹40–₹80; at ₹23 lakh a week Western grouping invites misreading the magnitude. |
| Window | **Last 28 days**, anchored to the latest data date | Daily data: a week is noisy and hides slow-burn campaigns. Anchored to the data, not to today — same rule as the public report. |
| Comparison | **KPI deltas vs the previous equal-length window** | `get_summary` / `get_overview` already return `{value, prev, delta_pct}`. RoAS 3.42 means nothing alone; "3.42, down 13.5%" is the story. |
| Scorecard | **Inside Sales & Operations** | Fill rate and PO-vs-GRN are ops questions for the same reader; 6 weekly rows + 33 facilities is too thin to stand alone. |
| Marketplace | **One `ads` / `sales` group now**, split per marketplace when a platform's private data has a different shape | Every private table already carries a `platform` column and every service takes `marketplaces: list[str]`, so the services are marketplace-parameterised today. **Trigger for splitting:** Zepto arriving with its own tables/semantics (different scorecard, perhaps no PO concept) — then add `ads_zepto`, don't bend one section over two schemas. |
| Field selection | **Explicit allow-lists per sheet**, never "dump the service's dict" | Several services return ORM rows carrying `tenant_id`, `id`, `scrape_job_id`, `upsert_key` — and PO rows carry a named person's phone and email. See *Gotchas*. |

### Phase A — renderer prerequisites

Neither report can start until these close. Both also improve the public report.

**A1. KPI deltas.** `Kpi` gains:

| Field | Type | Meaning |
|---|---|---|
| `prev` | `Any` | The same metric over the previous equal-length window |
| `delta_pct` | `float \| None` | Signed fractional change, as the services return it (`0.1359` = +13.6%) |
| `good` | `"high" \| "low" \| "neutral"` | Which direction is good — **per metric, not universal**: RoAS up is good, ACoS up is bad, spend up is neither |

Rendering: value as now, then a delta line — `▲ 13.6%` / `▼ 13.5%` in `GOOD_INK`
or `BAD_INK` per `good`, `MUTED` when `neutral` or when `prev` is absent. The KPI
block gets a caption naming the comparison window ("vs 16 Jun – 13 Jul").

**A2. Indian number grouping.** `FMT_MONEY` becomes a three-part conditional
format: crores, then lakhs, then plain — so ₹2,30,39,500 / ₹23,03,950 / ₹9,500.
Safe to change globally — below ₹1 lakh it renders identically, so every existing
public sheet is untouched. `FMT_MONEY_FINE` (per-unit prices) stays as-is; it is
never large.

**A3. Do counts need it too?** No. Impressions run to millions but `#,##0` is
correct for counts in either convention. Only currency changes.

---

### Marketing & Ads — `cli export ads`

Registry group `ads`. Section keys in sheet order.

**1. `ads_summary` — Ad Performance Summary** · `get_summary` · KPI block

| KPI | Field | Type | Good |
|---|---|---|---|
| Spend | `ad_spend` | money | neutral |
| Ad-driven sales | `ad_sales` | money | high |
| RoAS | `roas` | rating | high |
| ACoS | `acos` | pct | **low** |
| Impressions | `impressions` | count | high |
| Add to carts | `atc` | count | high |
| Units sold | `units_sold` | count | high |
| Active campaigns | `active_campaigns` | count | neutral |

Each carries `prev` + `delta_pct` from the service. Note `acos` and `roas` arrive
as a fraction and a multiple respectively — confirm scaling before formatting
(`0.2922` is 29.2%, `3.4222` is 3.42×).

**2. `ads_daily` — Daily Performance** · `get_performance` · ~28 rows

| Header | Field | Type | Emphasis |
|---|---|---|---|
| Date | `date` | date | — |
| Spend | `budget_consumed` | money | bar |
| Impressions | `impressions` | count | — |
| Ad-driven sales | `ad_sales` | money | bar |
| RoAS | `roas` | rating | good_high |

**3. `ads_campaigns` — Campaigns** · `get_campaigns` · 240 rows

| Header | Field | Type | Emphasis |
|---|---|---|---|
| Campaign | `name` | text | frozen label |
| Campaign ID | `campaign_id` | id | — |
| Type | `type` | text | — |
| Status | `status` | text | chips: ACTIVE→good, PAUSED→warn |
| Daily budget | `daily_budget` | money | — |
| Spend | `budget_consumed` | money | bar |
| Impressions | `impressions` | count | — |
| Add to carts | `atc` | count | — |
| Units sold | `quantities_sold` | count | — |
| Ad-driven sales | `ad_sales` | money | bar |
| RoAS | `roas` | rating | good_high |

Sorted by spend descending. Totals row: spend, sales, impressions summed; RoAS
**recomputed** as total sales ÷ total spend, never averaged.

**4. `ads_types` — Campaign Types** · `get_budget_split` · 3 rows

Type `campaign_type`, Spend `budget_consumed` (money, bar), Ad-driven sales
`ad_sales` (money), RoAS `roas` (rating, good_high). Same totals rule.

**5. `ads_keywords` — Keyword & Asset Performance** · `get_keywords` · **capped**

| Header | Field | Type |
|---|---|---|
| Target | `target` | text (frozen) |
| Target type | `target_type` | text |
| Match type | `match_type` | text |
| Campaign ID | `campaign_id` | id |
| Campaign type | `campaign_type` | text |
| Impressions | `impressions` | count |
| Spend | `budget_consumed` | money (bar) |
| CPM | `cpm` | money |
| Direct add to carts | `direct_atc` | count |
| Indirect add to carts | `indirect_atc` | count |
| Direct sales | `direct_sales` | money |
| Indirect sales | `indirect_sales` | money |
| New customers | `new_users_acquired` | count |
| Best position seen | `most_viewed_position` | rating (good_low) |
| Direct RoAS | `direct_roas` | rating (good_high) |
| Total RoAS | `total_roas` | rating (good_high) |
| As of | `snapshot_date` | date |

**Top 300 by spend**, with a note stating the cut and the true total. The source
table holds 30,809 rows; uncapped this stops being a report.

**6. `ads_sponsored` — Sponsored Share of Search** · `get_sponsored_sov` · ~198 rows

Allow-list **only**: Date `date`, Search term `keyword`, Monthly searches
`monthly_searches` (count), Searches `searches` (count), Sponsored share %
`sov` (pct, good_high). Everything else the service returns is plumbing.

**7. `ads_marketplaces` — By Marketplace** · `get_marketplace_breakdown` · 1–2 rows

Marketplace `name`, Connected `connected` (chips: true→good, false→warn), Spend,
Ad-driven sales, RoAS, Impressions. **Drop `color`** — a UI concern with no
meaning on paper.

**8. `ads_placements` — Visibility Plans & Collections** · `get_visibility_plans`
+ `get_collections` · 5 + 32 rows

Two small tables, or one sheet with a `Kind` column. Allow-list: plans → Name
`name`, Type `type`, Plan ID `plan_id`, Budget `budget` (money), Status,
Start/End dates. Collections → Name `name`, Collection ID `collection_id`,
Products `number_of_products` (count), Dynamic `is_dynamic`, Created `created_on`.

---

### Sales & Operations — `cli export sales`

Registry group `sales`.

**1. `sales_summary` — Sales Summary** · `get_overview` · KPI block

| KPI | Field | Type | Good |
|---|---|---|---|
| Revenue | `revenue` | money | high |
| Organic revenue | `organic_revenue` | money | high |
| Ad-driven sales | `ad_sales` | money | neutral |
| Units sold | `units_sold` | count | high |
| Products sold | `distinct_skus` | count | high |
| Ad spend | `ad_spend` | money | neutral |
| RoAS | `roas` | rating | high |

`get_overview` also returns `visibility` and `avg_rank` (public-data metrics).
**Leave them out** — this report is the private/commercial view, and mixing in a
week-stale public number beside current sales invites a false comparison.

**2. `sales_daily` — Daily Revenue** · `get_revenue_series` · ~28 rows

Date `date`, Revenue `revenue` (money, bar), Units `units_sold` (count).

**3. `sales_products` — Top Products** · `get_top_skus` (raise `limit`)

Product `item_name` (frozen), Item ID `item_id`, Revenue (money, bar), Units
(count). Add a computed **Revenue share %** so a reader sees concentration.

**4. `sales_cities` — Sales by City** · `get_sales_by_city` · 349 rows

City, Revenue (money, bar), Units, Revenue share %. Totals row.

**5. `sales_categories` — Sales by Category** · `get_sales_by_category` · 3 rows

Category, Revenue, Units, Revenue share %.

**6. `stock_on_hand` — Stock on Hand** · `inventory_service.get_soh`

Product `item_name` (frozen), Item ID `item_id`, Warehouse stock `backend_qty`
(count, good_high), Store stock `frontend_qty` (count, good_high), Facilities
`facilities` (count), As of `date`. **Cap and sort lowest-stock first** — this is
a "what runs out next" sheet, not a full inventory dump.

**7. `fill_rate` — Fill Rate** · `get_fill_rate` · KPI block

Ordered `total_po_quantity`, Received `total_grn_quantity`, Fill rate `fill_rate`
(pct, good_high), Potential loss `potential_loss` (money, good_low), Facilities
`facilities_count`. Caption with `from_date` — this figure has its **own** window
and does not follow the report's.

**8. `purchase_orders` — Purchase Orders** · `po_service.list_pos` · 1,172 rows

`list_pos` returns **38 fields**. Allow-list: PO number, State (chips), Vendor
`vendor_name`, Facility `facility_name`, City `city_name`, Ordered
`total_units_ordered`, Received `total_grn_quantity`, Fill % (computed), Value
`total_po_amount` (money), Issue/Delivery dates. **Excluded on purpose:** the
three report URLs, and `pm_name` / `pm_phone` / `pm_email` — see *Gotchas*.

**9. `scorecard_weekly` — Scorecard Trend** · `get_trend` · 6 rows

Week `from_date`, Fill rate (pct, good_high), Weighted fill rate
`weighted_fill_rate_percent` (pct, good_high), Potential loss (money, good_low),
GMV `total_gmv` (money), Ordered, Received, Rank `manufacturer_rank` (good_low).
`get_weekly` returns a nested `{overall, metrics, categories}` shape — flatten
into the KPI block or a second small table, never a dumped dict.

**10. `scorecard_facilities` — Scorecard by Facility** · `get_facilities` · 191 rows

Facility `facility_name` (frozen), Facility ID, City, Ordered, Received, Fill rate
(pct, good_high), Weighted fill rate, Potential loss (money, good_low), Rank.

**11. `scorecard_skus` — Scorecard Key SKUs** · `get_key_skus` · 53 rows

Product `item_name` (frozen), Item ID, UPC, Variant `variant_description`,
Category `proxy_category`, Potential loss (money, good_low), GMV `total_gmv` (money).

**Completion criterion: this report deletes `export_to_excel.py`.** That script is
the only thing dumping these tables today, and it is a hardcoded raw dump.

---

### New glossary terms (write before either report renders)

| Key | Term | Meaning | Caveat |
|---|---|---|---|
| `spend` | Ad spend | What was actually charged for advertising in the window. | Budget is what you allowed; spend is what was used. |
| `ad_sales` | Ad-driven sales | Sales the platform attributes to an ad someone saw or clicked. | The attribution is the platform's, not ours, and cannot be independently checked. |
| `organic_revenue` | Organic revenue | Revenue not attributed to an ad. | Total revenue minus ad-driven. A shopper who saw an ad last week may count here. |
| `roas` | RoAS | Return on ad spend — ad-driven sales for every ₹1 spent. | 3.4 means ₹3.40 back per ₹1. Never average RoAS across rows; recompute from totals. |
| `acos` | ACoS | Advertising cost of sale — spend as a share of ad-driven sales. | The inverse of RoAS. **Lower is better**, unlike almost everything else here. |
| `impressions` | Impressions | Times an ad was shown. | Not people: one shopper scrolling counts many times. |
| `atc` | Add to cart | Times a shopper put the product in their basket after seeing the ad. | Not a sale — baskets get abandoned. |
| `sponsored_share` | Sponsored share of search | Share of a search term's *paid* slots held by your ads. | **Different from "Share of search"** on the public report, which is organic. Do not compare the two. |
| `fill_rate` | Fill rate | Of what the platform ordered, how much actually arrived. | Measured on its own window, not the report's. |
| `grn` | Received (GRN) | Goods Receipt Note — the quantity the platform recorded as delivered. | A short GRN can be a supply miss or a receiving error. |
| `potential_loss` | Potential loss | The platform's estimate of revenue lost to unfilled orders. | Their model, not ours. |
| `days_of_cover` | Days of cover | How long current stock lasts at the recent rate of sale. | Needs `/inventory/cover`, not yet built. |

### Gotchas found while planning

- **Services leak ORM internals.** `get_sponsored_sov`, `get_visibility_plans` and
  `get_collections` all return rows carrying `tenant_id`, `id`, `scrape_job_id`
  and `upsert_key`. Every sheet uses an explicit allow-list; none may pass a
  service dict straight through.
- **⚠ PO rows carry a named person's contact details** — `pm_name`, `pm_phone`,
  `pm_email`, plus `entity_vendor_cin`. These must not appear in a workbook that
  gets emailed onward. Excluded by the allow-list, and called out here so nobody
  "helpfully" adds them back.
- **The keyword sheet is the sleeper.** `blinkit_ad_campaign_detail` holds 30,809
  rows and a 500-row probe came back full. Capped at 300 by spend, with the cut
  stated on the sheet.
- **Never average a ratio.** RoAS, ACoS and fill-rate totals must be recomputed
  from summed numerators and denominators. Averaging per-campaign RoAS is a
  classic mistake and produces a number that matches nothing else on the sheet.
- **Check ratio scaling before formatting.** `acos` came back `0.2922` and `roas`
  `3.4222` — one is a fraction, the other a multiple. The `pct` type expects 0–100.
- **`get_campaigns` returns all 240 campaigns**, inactive and zero-spend included.
  See open questions.
- **`potential_loss` read 0.0.** Confirm that is genuinely zero and not "never
  computed" before putting it in front of a client.
- **`get_fill_rate` has its own window** (`from_date`), independent of the
  report's. Its sheet must say so or the reader assumes they match.
- **Private data is Dobra-only.** Both reports validate against exactly one client.
- **Do not blend as-of dates.** Ads/sales are current, public is weekly. A future
  executive one-pager must label each source's freshness separately.

### Open questions (decide at build time)

1. **Zero-spend campaigns** — include all 240, or only those with spend in the
   window? *Recommendation:* only those with spend, with the excluded count noted.
2. **Days of cover** — build `/inventory/cover` in `inventory_service` (so the
   dashboard gets it too) or compute it in the section? *Recommendation:* service.
3. **Stock-on-hand cap** — how many rows before it stops being a report?
   *Recommendation:* lowest 200 by cover, since it is a "what runs out next" sheet.
4. **`get_weekly`'s nested shape** — flatten `{overall, metrics, categories}` into
   the KPI block, or give categories their own small table?

### Build order

- **Phase A** — renderer prerequisites (A1 KPI deltas, A2 Indian money).
- **Phase B** — `sections/ads.py` + `cli export ads`; cross-check every sheet
  against its service the way the public report was checked.
- **Phase C** — `sections/sales.py` + `cli export sales`; **delete
  `export_to_excel.py`**.
- **Phase D (later)** — executive one-pager composing all three families.

---

## Gotchas this must respect

- **Window = the selected dates**, filtered `scraped_at ∈ [start, end+1day)` —
  never "N days from now". `get_availability_history` is the deliberate exception
  (`?weeks=`, anchored to now); its sheet says so.
- **`merchant_id != ''`** — rows before 2026-07-18 predate the store columns and
  collapse into one phantom store. History was deliberately not backfilled.
- **`COUNT(DISTINCT merchant_id)`**, one row per (store, product) — one coordinate
  resolves to several stores and one store answers several coordinates.
- **Segment denominators by tier** — ~2,059 express stores vs ~510 shared hubs;
  mixing them is meaningless.
- **Read services are UI-shaped.** Several take `Pagination` and slice in Python;
  the report calls them with a full-window limit, which is memory-bound. Size the
  page, don't assume.
- **Raw rows do not belong in the report.** One 7-day window of one client is
  ~300k rows / 79 MB. See *Raw data* below.
- **Output artifacts**: local `backend/out/` for the CLI. When the endpoint
  lands, Render's disk is ephemeral — either stream the workbook straight from
  memory or put it in object storage. Decide then, don't write to disk on Render.

---

## CLI

```bash
# The client report — small, readable, what a download button will serve
python -m cli export public --tenant <uuid> \
  [--from 2026-08-01 --to 2026-08-07] \
  [--city bengaluru] [--kind main|combo|all] \
  [--marketplace blinkit] [--sections sku_shelf] \
  [--label "Q3 review"] [-o path.xlsx]

# The underlying rows — CSV, on demand, CLI only
python -m cli export raw --tenant <uuid> \
  [--from … --to …] [--tables sku,listings,searches,stores] \
  [--city bengaluru] [--marketplace blinkit] [--limit 5000] \
  [--include-extra] [--dry-run] [-o some/dir]

python -m cli export sections                   # what can be built
python -m cli export sample -o preview.xlsx     # fixture render, no DB
```

Default output: `<Client>_public_<end-date>.xlsx` for the report and
`<Client>_raw_<from>_<to>/` for the CSVs, both under `backend/out/` (gitignored).

Two behaviours worth knowing:

- **Omitting the dates does not mean "the last 7 days".** It means *the last 7
  days that actually have data* — the window is anchored to the newest scrape,
  not to today. Public scrapes run weekly, so a today-anchored default can land
  entirely after the last scrape and produce an empty workbook that looks like a
  bug. The resolved window is printed.
- **One `--city` at a time.** The read services filter a single city; silently
  widening a two-city request to "all cities" would overstate every denominator,
  so `ReportSpec` refuses it outright until sections learn to merge cities.

---

## Build phases

- **Phase 0 ✅** — this doc; legacy public scripts deleted.
- **Phase 1 ✅ (2026-08-10)** — `exports/theme.py` + `workbook.py`: the
  skeleton, the eight column types, widths/formats/emphasis/chips, cover +
  contents + glossary sheets, print setup. `app/schemas/exports.py` carries the
  render-side contracts (`Report` / `Section` / `Column` / `Kpi` / `Term`) — they
  moved up from Phase 2 because the writer needs them. `exports/sample.py`
  + `cli export sample` render the fixture.
- **Phase 2 ✅ (2026-08-10)** — `ReportSpec` (the input contract) +
  `glossary.py` (canonical wording **and** the wording guard) + `registry.py` +
  `text.py` (window/freshness phrasing) + `build.py` (cover, coverage counts,
  section runner, glossary collection) + `cli export public` / `export sections`.
  **Sheet 2 (SKU Shelf Presence) was built as part of this phase** rather than
  waiting for Phase 3 — a registry with no section in it proves nothing, and
  wiring one section end to end is what validated the design against real data.
- **Phase 3 ✅ (2026-08-10)** — the remaining public insight sections (1, 3–11) in
  `sections/shelf.py`, `pricing.py`, `visibility.py`, plus `sources.py` (memoized
  service reads). A full Dobra workbook is 13 sheets and ~29 s.
- **Phase 4 ✅ (2026-08-10)** — `exports/raw.py` + `cli export raw`. Split
  out of the workbook entirely rather than built as sheets 13–16: see *Raw data*.
- **Phase 5 ✅** — `cli export public` + `--sections`; first real Dobra run.
- **Phase 6 ✅ (2026-08-10)** — `sections/families.py`. Derives families from the
  product name; excludes multi-flavour bundles; unions store sets so a store
  carrying two variants counts once.
- **Phase 7 ✅ (2026-08-10)** — `explorer/export.py` is now a thin adapter onto
  the shared renderer. `Section.dense` was added for its long captured sheets,
  and `check_wording` moved into `write_workbook` so **every** consumer is
  checked, not just the client report.
- **Phase 8 (later)** — `GET /clients/{id}/exports/public.xlsx` + the Download
  button; optionally a `report.public` job type for scheduled/emailed exports.
- **Phases A–D** — Marketing & Ads and Sales & Operations reports; see
  *Next: Marketing & Sales exports* above.

Phases 1–2 are the standardization; 3–6 are the first report that proves it.
Explorer moves onto the renderer **after** the renderer is proven (7), not before —
it works today, so it's the follower, not the guinea pig.

---

See also [public-glossary.md](public-glossary.md) (the vocabulary),
[explorer.md](explorer.md) (the live-scrape sibling),
[dashboard-views.md](dashboard-views.md) (which view each section mirrors),
[per-unit-price.md](per-unit-price.md) (the ₹/unit band).
