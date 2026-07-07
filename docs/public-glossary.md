# Public Data — Glossary & Model

The definitive reference for every term in the public (scraped) system. All public
metrics are counted in **serviceable locations**, split by **Main vs Combo**, sourced
from **two scrapes**, and tagged with **freshness**. Blinkit-only.

## Foundations

- **Serviceable location `(lat, lon)`** — the unit of everything. It's a **delivery
  point**, *not* a store address. Several dark stores can serve one location, and the
  public search API selects the serving store from the coordinate — so we scrape
  *locations*, and every count is "how many locations," never "how many stores."
  (A catalog of ~2,216 store rows collapses to ~1,924 distinct locations.)
- **Covered locations** — the distinct `(lat,lon)` a client is set up to track (via
  `tenant_locations`). The denominator for **Reach**.
- **The two public scrapes** (both hit `POST /v1/layout/search`, differing only in query):
  - **Keyword scrape** — `cli scrape public-run`. Searches category keywords ("soda")
    → *visibility*: rank, share of voice, competitors. Writes `search_snapshots` +
    `search_listings`.
  - **Brand scrape** — `cli scrape public-skus`. Searches the brand name ("dobra")
    → *own shelf*: price, stock, distribution. Writes `sku_snapshots`.
- **Main vs Combo** — **Main** = singular SKUs; **Combo** = multipacks / bundles
  ("Pack of 2", "…+… Combo", "Buy 2 Get 1"). Combos are stocked selectively, so they're
  analysed apart from main SKUs (a **Main / Combos / All** filter, default Main).
  Classified by name (`is_combo` column on `sku_snapshots` and `search_listings`).
- **Freshness ("Updated N days ago")** — when the scrape feeding a section last ran.
  Public data is weekly/on-demand, so this flags staleness; never treat it as live.

## Availability & price (Inventory page + Products "on the shelf")

| Term | Meaning | Formula |
|---|---|---|
| **Reach** | How *widely present* the SKU is — % of covered areas where it appears at all | found locations ÷ covered locations |
| **Distribution %** | Of the areas where it's present, how many have it **in stock** (an in-stock rate) | in-stock locations ÷ found locations |
| **In-stock / locations** | The raw counts behind Distribution (e.g. 1,848 / 1,870) | — |
| **Avg discount** | Average % off MRP across locations | (MRP − price) ÷ MRP |
| **Rating** | Consumer star rating on the listing | — |
| **Price / median** | Typical price across locations | median of latest price per location |
| **Price band (min–max)** | Cheapest → dearest across locations | — |
| **Price dispersion** | The band per SKU — surfaces locations pricing you differently | min / median / max |
| **Availability trend** | Weekly on-shelf availability %; **OOS %** is its inverse | avg(in-stock) per week |
| **SKUs with gaps** | How many own SKUs are below 100% distribution | count(distribution < 100%) |

> **Reach vs Distribution — the important distinction.** *Reach* = "am I on the shelf
> here at all?" (breadth). *Distribution* = "where I'm on the shelf, am I in stock?"
> (health). A SKU can be 97% reach but 90% distribution if it's often OOS where it
> reaches. (Note: retail sometimes uses "distribution" for breadth; here that's **Reach**.)

## Visibility & competition (Competition page + Products "where it ranks")

| Term | Meaning |
|---|---|
| **Share of Voice (SoV)** | % of a keyword's search results that are *your* products — how much shelf you own for that search |
| **Rank** | Your best position in results; **#1 = top, lower is better** |
| **Rank heatmap** | Avg rank per **keyword × city** — darker = weaker; the "where am I losing" grid |
| **Where it ranks** (Products) | Per keyword: the SKU's avg position **and distinct locations** it appeared in (exact keyword → many locations; broad keyword → ranks low, fewer locations) |
| **Top competitors** | Which rival brands show up most in *your* searches |
| — **Areas seen in** | distinct locations a competitor appeared in |
| — **Share %** | that competitor's slice of all competitor location-presences |
| — **Keywords** | distinct keywords the competitor appeared in |
| — **Avg pos / Avg price** | their mean rank and listed price |
| **Price positioning** | Per keyword: **your** price band vs the **competitor** band — priced into or out of the set |

## The bridge (Products page)

- **`sku_map`** — links the **private** seller `item_id` (sales, stock) to the **public**
  `platform_product_id` (price, rank, availability). Blinkit uses different ids on each
  side (8-digit seller vs 6-digit consumer, no shared UPC), so this is built by
  normalized name-matching (`cli sku-map build` / `apply`). Without a mapping, a SKU's
  public panel shows "not mapped."
- **Product 360 → "On the shelf (public)"** — the public panel joined onto a private SKU
  via `sku_map`: Reach, Distribution, price band, discount, rating, and per-keyword rank —
  so one page shows *sold* (private) next to *on-shelf + ranked* (public).

## One-line mental model

**Reach** = breadth (how many areas) · **Distribution** = in-stock health (of those areas)
· **SoV / Rank** = visibility vs competitors · **Price / discount / rating** = the offer.
All in **serviceable locations**, split **Main vs Combo**, from **two scrapes**, tagged
with **freshness**.
