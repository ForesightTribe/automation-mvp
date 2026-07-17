# Dark Stores — Store-Level Public Data

**Status: catalog + schema shipped 2026-07-17; store-level views not built yet.**

- ✅ `marketplace_locations` re-synced to the darkstore export — 2059 express stores,
  precise coordinates, `location_name` + `address`, `zone` dropped (`d4a9c7e2b6f1`)
- ✅ `merchant_id` / `merchant_type` promoted to real columns (`e6c2a9d4f1b8`)
- ✅ the `products[0]` collapse fixed; `RESULT_CAP` floor raised 12 → 48
- ⬜ store-grain metrics / views / dashboard — **not started**
- ⬜ history not backfilled (by decision — see below); the store-level series starts
  from the first scrape after `e6c2a9d4f1b8`

So the plumbing carries the store, and **nothing yet reads it**. "Dark-store data" is
not live for the client until the views exist.

The client asked for **dark-store-level data**, not location-level. This doc records
what Blinkit actually exposes, what we probed to find out, and what has to change.

- **Model & terms** (Reach vs Distribution, combos, sku_map) → [public-glossary.md](public-glossary.md)
- **Decisions log & sizing** → [public-scraper-refactor.md](public-scraper-refactor.md)
- **Schema & internals** → [architecture.md](architecture.md)

---

## TL;DR

**We were measuring the doorway. We should be measuring the room.**

`(lat, lon)` was never the unit we wanted — it is how you *knock*. Blinkit stamps every
product in a search response with the **store that fulfils it** (`merchant_id`) and the
**tier it is sold under** (`merchant_type`). Both already arrive in every response; we
throw them away.

> **The unit is the store (`merchant_id`), read off each product.**
> **The coordinate is just the probe.**
> **The store set is discovered, not configured.**

---

## What this supersedes

[public-scraper-refactor.md](public-scraper-refactor.md) locks this decision:

> *"The unit is the serviceable location `(lat,lon)`, not the store. The catalog
> lat/long is a delivery point several dark stores can share … so all read metrics
> count distinct `(lat,lon)`."*

The **reasoning** was sound but rested on an untested premise: that we cannot tell which
store answered. We can — exactly, on every product. The same claim appears in
`CLAUDE.md` under *Public Scraper — Key Facts* and must be corrected when this ships.

What survives unchanged: Reach/Distribution definitions, combo separation, `sku_map`,
the two-scrape split, per-tenant storage.

---

## What Blinkit actually returns

Per product, inside the **`atc` block** — `data.atc_action.add_to_cart.cart_item`:

| field | example | notes |
|---|---|---|
| `merchant_id` | `35540` | **the store**. Stable, real, physical. |
| `merchant_type` | `express` | the **tier**, see below. Not a store property. |
| `inventory` | `13` | that store's stock. `0` = listed but sold out. |
| `price` / `mrp` | `73` / `75` | that store's price. |
| `eta_identifier` | `express` | mirrors `merchant_type` in every sample. |

**`cart_item` is the only trustworthy source.** The sibling
`tracking.common_attributes` block carries `merchant_id`/`merchant_type` keys but they
are **empty strings in search responses** — disagreed with `cart_item` on **864 of 864**
rows. (They *are* populated on the PDP endpoint, which we don't use.)

`scraper.py::_extract_product` already reads both fields. Nothing new to extract — we
just discard them downstream.

### The tiers

| `merchant_type` | meaning | observed? |
|---|---|---|
| `express` | 10-minute core shelf | yes, everywhere |
| `longtail` | extended range, hub-fulfilled, slower ETA | yes |
| `super_longtail` | deep tail | yes |
| `dummy` (`eta_identifier: large_order`) | large-order listings, carries the real store's id | yes, rare (6 rows) |
| `unicorn` | — | **never observed** — see [Limits](#limits) |

---

## The evidence

All findings below are from read-only probes (no DB writes). Scripts are not committed;
they are reproducible from this doc.

### 1. One product → exactly one store, per location

**0 of 773** products came back under more than one merchant at the same `(lat, lon)`.
Every product resolves to exactly one `(merchant_id, merchant_type, inventory)`. This is
the finding the whole design rests on: **inventory is unambiguously attributable.**

### 2. `merchant_id` is a real store with one stock level

Hub `35540` probed from two different Delhi catchments (Roshanpura `44173`, Gandhi Sadan
`30790`): **87 of 87 common products reported identical inventory *and* identical
price.** So `COUNT(DISTINCT merchant_id)` is safe, and any two stores are exactly
separable.

### 3. Tier is a property of the *product*, not the store

- **Tirupati `42618`** — returns `express` when probed from its own coordinate,
  `longtail` when probed from host `38262`'s coordinate. Same store, different tier,
  purely because of where you knocked.
- **Delhi Dwarka `34418`** — returns `express` *and* `longtail` products
  **simultaneously at the same coordinate**.
- **Agra `33920`** — returns `longtail` *and* `super_longtail` at once.

⇒ **Never model type on a store, and never look it up from a table.** Take it from the
response, per product, every time. Any `merchant_id → type` mapping is wrong by
construction (the export alone has 213 ids that are express in one row and longtail in
another).

### 4. A coordinate maps to a *set* of stores — no per-tier uniqueness

Delhi **Block B 22** (`30908`), keyword `geometry box`, returned **four stores at one
coordinate** — and **two different `longtail` stores**:

```
('30908','express')  ('45791','longtail')  ('36776','longtail')  ('45642','super_longtail')
```

⇒ Nothing may assume "one store per tier". Only product → store is 1:1.

### 5. Tier depth — why this was invisible

Non-express rows are **interleaved by rank**, not appended:

| location | keyword | first non-express at rank |
|---|---|---|
| Agra | `dobra` | 24 |
| Delhi | `dobra` | 29 |
| Delhi | `soda` | 20 |
| Delhi / Agra | `bedsheet`, `yoga mat`, `school bag` | 1 |

The `api.txt` capture was 12–13 products deep, so it showed express only and looked like
proof that only express exists. It wasn't. See [Caps](#caps).

### 6. The export: express mapping trustworthy, child lists are not

`blinkit_darkstores_export.xlsx` — one row per **express** store (2059 rows, all
`active=yes`, all `type=express`), with pipe-separated `longtail_ids` /
`super_longtail_ids` / `unicorn_ids`. 2844 distinct ids total.

| claim | verdict |
|---|---|
| `(lat,lon)` → express `merchant_id` | ✅ **16/16 correct** across Chandigarh, Delhi, Agra, Guntur, Kakinada, Kurnool, Tirupati, Vijayawada |
| `longtail_ids` predict the serving hub | ❌ **Mithai Pul `35298`**: export says `35540`; reality served `44311` + `43541`, **zero** from `35540` |
| `unicorn_ids` exist | ❌ never materialised in any probe |

⇒ Use the export to decide **where to knock** and to **assert** the express id. Never to
decide which hub owns what.

### 7. Orphan hubs — why discovery is mandatory

The export is organised by express store, so a store that is *only ever a hub* gets no
row of its own. **213 of 655 referenced hub ids are such orphans.**

Not theoretical — of the **29 stores actually observed across all probes, 7 (24%) were
orphans**:

| store | tier | serving |
|---|---|---|
| `45791` | longtail | 26 of 48 `notebook` results at Block B 22 |
| `44311` | longtail | 95 products at Mithai Pul — the store the export said was `35540` |
| `36776`, `45642`, `47284`, `47338`, `43649` | longtail / super_longtail | live Delhi stationery traffic |

⇒ Config can never enumerate the store set. Only scraping can.

**On labelling them** — the old 2216-row config *did* carry a `city` for 195 of the 213
orphans, and that data was dropped in the 2026-07-17 re-sync. Deliberately: the old
sheet had no `location_name` and no `address`, so a `city` string was its entire
contribution — and a hub's city is **derivable from the probe it answered**, since
every snapshot row stores `city`/`lat`/`lon` alongside the merchant:

```sql
SELECT DISTINCT merchant_id, city FROM sku_snapshots   -- hub -> city, live and current
```

Same information, derived from a live scrape instead of a stale file. Orphans render as
*"Longtail hub 45791 (Delhi)"*. No store name exists for them anywhere — not in the
export, not in the old config, not in the API. That gap is cosmetic; **inventory is
exact regardless.**

### 8. Hub duplication — 6.4×

510 distinct hubs, but **3249 (catchment, hub) pairs** — one hub reachable from up to 27
express catchments. Express dedupes naturally (~1:1 with the coordinate); hubs do not.

⇒ Rows are **redundant, not ambiguous**. `COUNT(DISTINCT merchant_id)`, never `COUNT(*)`.

### 9. The mixed-brand case is real

Delhi stationery: **51 of 111 brands span multiple tiers.** `Luxor` sits across
`express` at three stores, `longtail` at two, `super_longtail` at three — eight
`(store, tier)` combinations. Dobra, by contrast, is **100% express** (21/21 at Agra).

---

## The model

```
coordinate (probe)  ──►  response  ──►  product ──► (merchant_id, merchant_type, inventory)
   from config                             │
                                           └── group by merchant_id  ──►  per-store inventory
```

- **Config = where to knock.** Coordinates + expected express id + city metadata.
- **DB = what answered.** Stores discovered from responses.
- **Tier is a row label**, never an identity.

### Why tier matters commercially

`merchant_type` is effectively **delivery speed**. Express is the 10-minute shelf;
longtail ships from a hub, slower. Same coordinate, same shopper, same search — an
express competitor beats a longtail you on impulse purchase. Tier migration
(longtail → express) becomes a measurable objective. This insight does not exist today.

---

## DB changes (applied 2026-07-17)

| # | Table | Change | Revision |
|---|---|---|---|
| 1 | `sku_snapshots` | **+ `merchant_type`** — already had the correct per-product `merchant_id`; without tier you cannot separate an express row from a longtail one | `e6c2a9d4f1b8` |
| 2 | `search_listings` | **+ `merchant_id`, + `merchant_type`** — had neither; both were buried in the `extra` JSON blob | `e6c2a9d4f1b8` |
| 3 | `search_snapshots` | **+ `merchant_id`** (the express store = the coordinate's identity) — stays **location-grain**, see note | `e6c2a9d4f1b8` |
| 4 | `marketplace_locations` | re-synced from the export: 2216 → **2059** rows, precise coordinates (median **1.75 km** shift), **+ `location_name`, + `address`**, **− `zone`** (0 of 2216 rows ever used it) | `d4a9c7e2b6f1` |

**History was deliberately not backfilled.** Existing rows keep `""` and the store-level
series starts fresh. It stays recoverable — `search_listings.extra` still holds
`merchant_id`/`merchant_type` for every pre-migration row (100% coverage, including
**1,313 longtail rows** captured before we could see them). The `e6c2a9d4f1b8` docstring
carries the backfill SQL, including the `WHERE merchant_id = ''` guard that stops it
blanking post-migration rows.

⇒ **`""` means unknown, never `express`.** Any view treating empty as a default will
silently turn the 7,742 express-less snapshots into express.

**On #3 — `search_snapshots` deliberately stays location-grain.** Rank and SoV are what
the *shopper* sees: one blended list across stores. Re-keying that to store would invent
a ranking no human ever saw. Store grain belongs to `sku_snapshots` (inventory);
location grain stays on `search_snapshots` (visibility). `merchant_id` there is a label,
not a regrain.

### Rejected: a `marketplace_stores` registry

Considered and **dropped**. For an orphan like `44311` it would hold: the id (already on
every snapshot row), a NULL name (nobody has one — see §7), a city inferable from the
probe coordinate (already on the snapshot row), and `first_seen`/`tiers_seen` (a
`GROUP BY` away). **It adds no information that isn't already in the rows.** The store
list is:

```sql
SELECT DISTINCT merchant_id FROM sku_snapshots WHERE ...
LEFT JOIN marketplace_locations USING (mp_slug, merchant_id)   -- labels for the ~76% we know
```

`marketplace_locations` is already keyed `(mp_slug, merchant_id)` and `sku_snapshots`
already has `idx_sku_tenant_store (tenant_id, merchant_id, scraped_at)`, so this is
cheap. Known stores render with their real name; orphans render as
*"Longtail hub 45791 (Delhi)"*. Cosmetic gap, not a data gap — **inventory is exact
either way.**

Revisit only if: human-supplied labels for orphans are wanted, store open/close
detection (`first_seen`/`last_seen`) is needed, or the `DISTINCT` gets slow.

> ⚠️ Alembic has **2 heads** — `upgrade head` errors. Target explicitly.

---

## Config & sync

**No change to the config model.** The caps and the workbook stay exactly as they are.

| candidate column | verdict | why |
|---|---|---|
| store `type` | ❌ **never** | per-product attribute; a config column is wrong by construction (§3) |
| `longtail_ids` / `super_longtail_ids` / `unicorn_ids` | ❌ **do not sync** | don't predict the serving hub (§6); unicorn never materialises |
| express `merchant_id` | ✅ **keep** — role changes | not a scrape input (we send lat/lon). It is the probe point's **label** + a **validation assertion**: 16/16 correct, so a mismatch means a store moved/closed/opened |

The only config work is re-syncing `marketplace_locations` from the new export for
precise coordinates + `location_name`.

---

## Caps

Caps already live in config and the precedence is already correct:

```
keyword scrape:  CLI --cap  >  tenant keyword_cap  >  ep.RESULT_CAP        (orchestrator.py:214)
brand scrape:    CLI --brand-cap  >  tenant brand_cap  >  ep.BRAND_RESULT_CAP  (targeted.py:58)
```

Dobra runs `keyword_cap=36` / `brand_cap=48` and never touches the defaults. 36 is deep
enough to reach its rank-24/29 longtail rows.

**The problem is the floor, not the knob.** `RESULT_CAP = 12` sits *below* the depth
where non-express tiers appear (rank 20–29), so any tenant without a configured
`keyword_cap` is structurally blind to longtail. **Raise `RESULT_CAP` to ~36–48.** Leave
the config knob alone.

⚠️ Every Delhi stationery keyword returned *exactly* the 48-product probe ceiling —
i.e. truncated. For a mixed-tier brand, **cap directly bounds how many stores you
discover**. Cap sizing is a per-tenant judgement, not a global one.

---

## Code changes (no migration)

- `scraper.py::search()` — drop the `merchant_id = products[0]["merchant_id"]` collapse
  (line ~298). It stamps the express store onto every row and is wrong the moment a
  brand has non-express SKUs. Per-product merchant already flows through
  `classify_products` (`{**p}`), so `sku_storage`'s `l.get("merchant_id")` is already
  correct — the fallback is the liability.
- `endpoints.py` — `RESULT_CAP` 12 → ~36–48.
- Decide on `dummy` / `large_order` rows: **flag, don't drop** — they are real
  large-order listings, but must be excluded from tier denominators.

---

## Metrics at store grain

Definitions from [public-glossary.md](public-glossary.md) are unchanged — only the key
moves from `(lat,lon)` to `merchant_id`:

- **Reach** = stores where the SKU is listed ÷ stores reachable *(of that tier)*
- **Distribution** = stores in stock ÷ stores listed

**Denominators are per-tier.** ~2059 express stores vs ~510 hubs. *"In stock at 47 of
2059 stores"* is nonsense for a longtail SKU whose universe is ~510. Segment every KPI
by `merchant_type`, or show the tier beside it.

`N` is **stores observed**, never the full catalogue — absent ≠ out of stock.

### What this unlocks

- *"Dobra is listed at 47 of 52 express dark stores; in stock at 44; OOS at Agra–Shahganj
  (36058), …"* — routes to a named store manager.
- *"At Delhi Block B 22, Luxor is express, your pens are longtail — same shopper, same
  search, they get 10-minute delivery and you don't."*
- *"You're rank 24 in Agra because ranks 1–23 are express-tier and you're longtail."*
- Store discovery + the express assertion as a free store-moved/closed alarm.

---

## Limits

- **No unicorn.** Zero rows across ~1150 stationery products at three locations whose
  export rows all list `unicorn_ids`, plus Agra. Either not publicly exposed or dormant.
  **Do not promise it.**
- **You see the *serving* store, not every store holding the SKU.** If express carries
  it, you get express's number; a hub may also stock it, invisibly. "Per-store
  inventory" means *the store that serves it from here*.
- **Absent is ambiguous** — not-carried and past-the-cap look identical from outside.
- **Only stores reachable from covered coordinates** are ever discovered.
- **For Dobra this is mostly language + proof** — it is 100% express, and express is
  ~1:1 with the coordinate, so location and store were already the same thing. The tier
  machinery is what stops the dashboard breaking the day a Luxor-shaped brand signs.

---

## Open items

1. **Store-grain views + dashboard** — the actual deliverable. Nothing reads
   `merchant_type` yet.
2. Correct the location-unit claim in `CLAUDE.md` (*Public Scraper — Key Facts*) and
   `public-scraper-refactor.md` (*Locked decisions*) — both still say the unit is
   `(lat,lon)`, not the store.
3. Unicorn: one more targeted probe, or formally drop it from scope.
4. Cap sizing per tenant for mixed-tier brands — every Delhi stationery keyword hit the
   probe ceiling, i.e. was truncated. Dobra's `keyword_cap=36` is fine because it is
   express-only; a Luxor-shaped brand needs more.
5. `scraper/utils/cities.py` is still the fallback in `list_blinkit_zones` when the
   catalog is empty. Now that the catalog is authoritative, that fallback is arguably
   worse than an empty dropdown.
6. 49 of 2059 stores have an `address` but no `location_name` (the export's own gap) —
   they render as just their city.
7. Optional: backfill the history (SQL + guard in the `e6c2a9d4f1b8` docstring).
