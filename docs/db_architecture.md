# Database Architecture

**Database:** MongoDB Atlas  
**Driver:** Motor (async PyMongo) — raw collections, no ODM on the write path  
**Models:** Beanie Documents in `app/models/` — used by the API read layer only

---

## Collections

Seven collections, each with one clear business purpose. Platform count and data type count do not change this set — they are absorbed via the `platform` and `data_type` envelope fields.

| Collection | Purpose | Key `data_type` values |
|---|---|---|
| `scrape_jobs` | One doc per scrape run — status, timing, error | — |
| `ad_campaigns` | All advertising performance data | `campaign`, `snapshot` |
| `brand_collections` | Brand page / product grouping configs | `brand_collection` |
| `visibility_plans` | Platform promotion plan subscriptions | `visibility_plan` |
| `product_catalog` | Product listings and pricing | `product` |
| `sales_data` | Revenue and units sold (time series) | `sales` |
| `inventory_data` | Stock levels (time series) | `inventory` |

> `platform_sessions` is a separate operational collection for encrypted browser sessions — not part of the scraped data schema.

---

## Standard Envelope

**Every document in every collection carries these fields.** They answer: who, where, what, and when — and enable deduplication.

```python
{
    "tenant_id":      str,   # which seller, e.g. "seller1"
    "platform":       str,   # "blinkit" | "zepto" | "instamart"
    "dashboard":      str,   # "sales" | "marketing" | "unified"
    "data_type":      str,   # specific subtype within the collection
    "scrape_job_id":  str,   # links back to the scrape_jobs document
    "scraped_at":     datetime,  # UTC timestamp when the scrape ran
    "date":           date,      # business date this data represents
    "upsert_key":     str,   # unique identity string — see convention below
}
```

Platform-specific fields are appended flat alongside these. MongoDB's flexible schema handles sparse fields across different platforms and data types without any schema changes.

---

## Upsert Key Convention

`upsert_key` is the deduplication anchor. It is always a colon-separated string built from the natural identity of the record. Every write is an upsert on this field — re-scraping the same data updates the existing document rather than creating a duplicate.

| Collection | `data_type` | `upsert_key` formula |
|---|---|---|
| `ad_campaigns` | `campaign` | `{tenant_id}:{platform}:campaign:{name}:{date}` |
| `ad_campaigns` | `snapshot` | `{tenant_id}:{platform}:snapshot:{date}` |
| `brand_collections` | `brand_collection` | `{tenant_id}:{platform}:brand_collection:{name}` |
| `visibility_plans` | `visibility_plan` | `{tenant_id}:{platform}:visibility_plan:{plan}:{period}` |
| `product_catalog` | `product` | `{tenant_id}:{platform}:product:{product_id}` |
| `sales_data` | `sales` | `{tenant_id}:{platform}:sales:{product_id}:{date}` |
| `inventory_data` | `inventory` | `{tenant_id}:{platform}:inventory:{product_id}:{date}` |

`brand_collections` and `visibility_plans` do not include `date` in the key — they are configuration records that are updated in place when re-scraped. Time-series collections (`ad_campaigns`, `sales_data`, `inventory_data`) include `date` so each day is a separate document.

---

## Per-Collection Document Shapes

### `scrape_jobs`

```python
{
    "tenant_id":       "seller1",
    "platform":        "blinkit",
    "dashboard":       "marketing",     # which dashboard was targeted
    "status":          "success",       # pending | running | success | failed
    "started_at":      ISODate,
    "completed_at":    ISODate,
    "error":           None,
    "records_written": 42,
    "created_at":      ISODate,
}
```

### `ad_campaigns` — `data_type: "campaign"`

```python
{
    ...envelope,
    "name":             "Summer Sale",
    "status":           "Active",
    "campaign_type":    "Brand Focus",
    "duration":         "Jan 15 - Feb 28",
    "budget_consumed":  74341.0,
    "impressions":      123456,
    "atcs":             5432,
    "roas":             3.14,
    "ctr":              0.45,
    # Zepto may add "cpm", "cpp", etc. — sparse fields are fine
}
```

### `ad_campaigns` — `data_type: "snapshot"`

One per scrape run — aggregate totals across all active campaigns.

```python
{
    ...envelope,
    "total_budget_consumed": 184341.0,
    "total_impressions":     523456,
    "total_atcs":            15432,
    "total_qty_sold":        8900,
    "total_sales":           234567.0,
    "overall_roas":          3.14,
    "overall_ctr":           0.45,
}
```

### `brand_collections`

```python
{
    ...envelope,
    "name":            "Summer Essentials",
    "product_count":   25,
    "collection_type": "STATIC",
    "created_by":      "admin@brand.com",
    "created_on":      "2026-01-15",
}
```

### `visibility_plans`

```python
{
    ...envelope,
    "plan":    "Premium",
    "period":  "Monthly",
    "budget":  50000.0,
    "status":  "Active",
}
```

### `product_catalog`

```python
{
    ...envelope,
    "product_id": "prod_123",
    "name":       "Oats 500g",
    "sku":        "OAT-500",
    "category":   "Breakfast",
    "price":      89.0,
    "mrp":        99.0,
}
```

### `sales_data`

```python
{
    ...envelope,
    "product_id":   "prod_123",
    "product_name": "Oats 500g",
    "units_sold":   890,
    "revenue":      23456.0,
    "returns":      5,
}
```

### `inventory_data`

```python
{
    ...envelope,
    "product_id":        "prod_123",
    "product_name":      "Oats 500g",
    "stock_available":   240,
    "days_of_inventory": 12,
}
```

---

## Indexes

Each collection has two indexes defined in its Beanie model (`app/models/`):

1. **Unique index on `upsert_key`** — enforces deduplication at the database level
2. **Compound query index on `(tenant_id, platform, date DESC)`** — fast retrieval for the most common query pattern: "get data for seller X on platform Y, newest first"

`scrape_jobs` indexes on `(tenant_id, platform, created_at DESC)` and `(status)` for job monitoring queries.

---

## How a Scrape Run Writes Data

```
1. Create scrape_jobs doc           → status: "pending"
2. Run platform scraper             → raw dicts with string values
3. Run parser                       → typed Python values (float, int, datetime)
4. Build envelope fields            → tenant_id, platform, dashboard, scrape_job_id, date, upsert_key
5. upsert_many() to target collections via bulk_write UpdateOne(upsert=True)
6. Update scrape_jobs doc           → status: "success", records_written: N
```

The upsert utility lives at `scraper/utils/storage.py`. All platform storage modules call it — no platform writes directly to MongoDB.

---

## Dashboard → Collection Mapping

Different platforms expose their data through different dashboard structures. The scraper layer handles this; the storage layer is unaware of it.

| Platform | Dashboard | Writes to |
|---|---|---|
| Blinkit | `marketing` | `ad_campaigns`, `brand_collections`, `visibility_plans` |
| Blinkit | `sales` | `sales_data`, `inventory_data`, `product_catalog` |
| Zepto | `unified` | all collections (single dashboard, same data) |
| Instamart | `unified` | all collections (single dashboard, same data) |

---

## Adding New Metrics or Data Types

**New field on an existing data type** (e.g. Zepto exposes `cpm` on campaigns):  
Add the field to the document in the scraper. MongoDB handles sparse fields — existing documents without `cpm` are unaffected. Add the field to the Beanie model if the API needs to return it.

**New subtype in an existing collection** (e.g. keyword bidding — still ad-related):  
Use a new `data_type` value (e.g. `"keyword_bid"`) in `ad_campaigns`. Define its `upsert_key` formula in this document. Add a `NormalizedKeywordBid` dataclass in `scraper/normalizer/schema.py`.

**Genuinely new data domain** (e.g. customer reviews, returns):  
1. Add a new collection name (e.g. `reviews_data`)
2. Create `app/models/review.py` with the Beanie Document
3. Add a `NormalizedReview` dataclass in `scraper/normalizer/schema.py`
4. Add the `data_type` and `upsert_key` formula to this document
5. Write a storage call in the platform's `storage.py` using `upsert_many(db, "reviews_data", docs)`

No changes to existing collections, models, or infrastructure needed.
