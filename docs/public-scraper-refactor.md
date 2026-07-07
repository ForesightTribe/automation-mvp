# Public Scraper — Decisions, Cost Sizing & Open Items

The public-scraper refactor shipped. This doc is now the **decisions log + cost
sizing + remaining open items** — it is not a how-to. For that:

- **Model & terms** (Reach vs Distribution, combos, sku_map, the two scrapes) → [public-glossary.md](public-glossary.md)
- **Schema & internals** → [architecture.md](architecture.md)
- **Commands** → [cli.md](cli.md)   ·   **Endpoints** → [api-reference.md](api-reference.md)

## Locked decisions (the *why*, not captured in the reference docs)

- **Per-tenant storage** — `tenant_id` on every public row; public data is *not*
  shared/deduped across tenants. Near-zero keyword overlap expected between clients,
  so dedup saves almost nothing while shared storage would force a watchlist-lens
  read indirection.
- **Two scrapes, one API.** Both hit `/v1/layout/search`, differing only in query:
  the **keyword scrape** (`public-run`) for visibility (SoV/rank/competitors →
  `search_snapshots`/`search_listings`), the **brand scrape** (`public-skus`) for
  own-shelf (price/stock → `sku_snapshots`). The dedicated PDP endpoint
  (`/v1/layout/product/{id}`) was evaluated and left unused (too heavy).
- **The unit is the serviceable location `(lat,lon)`, not the store.** The catalog
  lat/long is a delivery point several dark stores can share, and the search API
  resolves a coordinate to one serving store — so all read metrics count distinct
  `(lat,lon)`. This resolved a long "coverage gap" that was purely a store-vs-location
  counting artifact (brand search returns only ~18 basic matches for a brand query,
  but that never mattered — the real numbers are location-based and healthy, ~97%
  reach for a main SKU).
- **Header + detail** for the keyword scrape (`search_snapshots` header for cheap
  trends + `search_listings` per-product detail); **flat** `sku_snapshots` for the
  brand scrape.
- **Combos separated from main SKUs** (`is_combo`, name-classified) — combos are
  stocked selectively, so metrics default to main-only (`?kind=main|combo|all`).
- **`sku_map` bridges private↔public** (`item_id` ↔ `platform_product_id`) —
  different Blinkit id systems, no shared UPC, so name-matched.
- **Watchlist-driven, job-tracked** — the per-tenant spec (config workbook →
  `tenant_watchlist` + `tenant_locations`) drives scraping; every run opens a
  `scrape_jobs` row, like the private path.

## Cost / volume sizing (for the production-scaling conversation)

Scrape grain = `keyword × location`. Each search → 1 snapshot + ~15 listing rows.
Rule of thumb: **≈ 0.75 GB / keyword / month** (incl. indexes).

| Keywords | Searches/day | Listings/mo | Storage added/mo |
|---|---|---|---|
| 10 | 40,000 | 18 M | ~7.5 GB |
| 20 | 80,000 | 36 M | ~15 GB |
| 50 | 200,000 | 90 M | ~38 GB |

Append-only → accumulates (20 kw ≈ 180 GB after 12 months). Supabase $ is modest;
what bites first: **scrape throughput** (browser-based can't sustain a full census
— hence the worker pool + session reuse) and **cumulative growth** (retention +
monthly partitioning when it matters). Private data is a rounding error next to this.

## Open items

- **Scrape dedup (optional efficiency)** — iterate distinct `(lat,lon)` (~1,924) not
  all catalog rows (~2,216): ~13% less work, no duplicate rows at source. Needs a
  re-scrape. Metrics already count locations, so this is efficiency-only.
- **Explorer system** — on-demand custom-scrape → Excel tool (any keyword/brand/SKU/
  city, ephemeral, agency-facing). Net-new, reuses the scrape engine.
- **Production/scaling** — cloud scheduler for the scrapes, proxy pool (IP diversity
  is the real ceiling, not compute/DB), pre-aggregation/partitioning + retention.
- **Private-data UI gaps** — Inventory's private SOH/fill-rate section (endpoints
  exist, no UI).
- **Cleanup** — unused `AttentionFeed.jsx` + `useAlerts` (removed from Overview).
