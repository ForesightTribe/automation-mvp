# Public Data — Glossary & Model

The definitive reference for every term in the public (scraped) system. All public
metrics are counted in **dark stores**, split by **Main vs Combo**, sourced from
**two scrapes**, and tagged with **freshness**. Blinkit-only.

> ⚠️ **Model change, 2026-07-18.** The unit was previously the *serviceable location*
> `(lat,lon)`, on the belief that we could not tell which store served a coordinate.
> We can: every product carries its own `merchant_id` + `merchant_type`. The unit is
> now the **store**. See [darkstores.md](darkstores.md).
> **The read services still compute at location grain — migration is pending**, so
> what the API returns today still matches the old definitions.

## Foundations

- **Dark store (`merchant_id`)** — the unit of everything. A real, physical store; the
  same id seen from two different coordinates reports identical inventory and price.
- **Probe point `(lat, lon)`** — where we *knock*, not what we measure. Blinkit resolves
  a coordinate to its serving store(s) and the response names them. One coordinate can
  return several stores (express + longtail hubs); one store can answer several
  coordinates (when the catalog drifts). Hence **always `COUNT(DISTINCT merchant_id)`**,
  and one row per `(store, product)`.
- **Store tier (`merchant_type`)** — `express` (10-minute core shelf) · `longtail` /
  `super_longtail` (extended range, hub-fulfilled, slower) · `dummy` (large-order).
  A property of the **product's fulfilment**, not of the store: one store can be
  express to its own catchment and longtail to a neighbour. **Denominators must be
  segmented by tier** — ~2,059 express stores vs ~510 shared hubs; mixing them is
  meaningless.
- **Covered stores** — the stores a client's coordinates reach (via `tenant_locations`).
  The denominator for **Reach**.
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
| **Reach** | How *widely present* the SKU is — % of covered stores where it appears at all | stores listed ÷ stores covered |
| **Distribution %** | Of the stores where it's listed, how many have it **in stock** | stores in stock ÷ stores listed |
| **In-stock / listed** | The raw counts behind Distribution (e.g. 24,410 / 25,474) | — |
| **Avg discount** | Average % off MRP across stores | (MRP − price) ÷ MRP |
| **Rating** | Consumer star rating on the listing | — |
| **Price / median** | Typical price across stores | median of latest price per store |
| **Price band (min–max)** | Cheapest → dearest across stores | — |
| **Price dispersion** | The band per SKU — surfaces stores pricing you differently | min / median / max |
| **Availability trend** | Weekly on-shelf availability %; **OOS %** is its inverse | avg(in-stock) per week |
| **SKUs with gaps** | How many own SKUs are below 100% distribution | count(distribution < 100%) |

> **Reach vs Distribution — the important distinction.** *Reach* = "am I on the shelf
> here at all?" (breadth). *Distribution* = "where I'm on the shelf, am I in stock?"
> (health). A SKU can be 97% reach but 90% distribution if it's often OOS where it
> reaches. (Note: retail sometimes uses "distribution" for breadth; here that's **Reach**.)
>
> They are also **different problems for different teams**: a SKU that is *not listed*
> is a range/commercial gap; one that is *listed but out of stock* is a replenishment
> gap. Measured all-India on 2026-07-19: Reach 84.7% (4,586 unlisted store×SKU slots)
> vs Distribution 95.8% (1,064 stockouts) — i.e. the bigger opportunity was listings,
> not replenishment. Keep them apart or that signal is lost.

> **"Absent" is not "out of stock."** A SKU missing from a store's response may be
> not-carried *or* past the scrape cap — indistinguishable from outside. So `N` is
> always **stores observed**, never the brand's full catalogue.

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
