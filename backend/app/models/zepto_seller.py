"""Zepto seller dashboard (brands.zepto.co.in) tables.

Shaped by what Zepto's Sales Analytics API actually returns, which is NOT the
same grain as Blinkit's seller data:

* Blinkit gives one row per item × city × day. Zepto gives a **daily total**
  (GMV/units for the whole brand, no item or city split) plus a **separate
  product breakdown aggregated over the requested window**. There is no
  per-city dimension anywhere in the responses we get, so nothing here has a
  city column — a Sales-by-City chart cannot be built from this source.
* The product endpoint returns one aggregate per SKU for the whole
  start→end window, not per day. `period_start`/`period_end` are therefore part
  of that table's grain (and its upsert key): scraping a one-day window gives
  daily rows, a 30-day window gives one 30-day snapshot.

Bookkeeping columns (tenant_id, platform, upsert_key, scrape_job_id,
scraped_at) match the Blinkit tables so both behave the same for re-runs.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Index

from app.utils.time import now_ist
from sqlmodel import Field, SQLModel


class ZeptoSellerSalesDaily(SQLModel, table=True):
    """One row per tenant per calendar day — GMV and units for the brand."""

    __tablename__ = "zepto_seller_sales_daily"

    __table_args__ = (Index("idx_zssd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    brand_id: str
    brand_name: str | None = None

    # Zepto returns GMV already rounded to whole rupees in the daily series.
    gmv: float = 0.0
    units: int = 0

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoAdCampaignDaily(SQLModel, table=True):
    """One row per ad campaign per day.

    Zepto's `/ads-bff/api/v1/campaigns` returns a campaign's identity *and* its
    metrics for whatever window is asked for, so scraping it a day at a time
    yields campaign x day rows directly. That covers what Blinkit splits across
    two tables (`blinkit_ad_campaigns` for identity, `blinkit_ad_campaign_daily`
    for the series) — hence one table here, not two.

    A row is filled from two endpoints, because neither is complete: the
    campaigns endpoint above for the operational fields (budgets, base bid,
    targeting, status, dates) and `/metrics/tabular?view=campaign_table` for
    revenue, add-to-carts and the rest of the block at the bottom of this class.
    The keyword breakdown lives on `ZeptoAdKeywordDaily`.

    Column names follow Zepto's own (`spend`, `roi`) rather than Blinkit's
    (`budget_consumed`, `roas`); mapping between them belongs in the service
    layer, not baked into a column name that would then misdescribe the source.
    """

    __tablename__ = "zepto_ad_campaign_daily"

    __table_args__ = (Index("idx_zacd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    campaign_id: int
    campaign_name: str | None = None
    brand_id: str
    brand_name: str | None = None

    # The campaign's real tab — but only once the Analytics table has confirmed
    # it. The campaigns endpoint ignores its `categoryType` parameter (asking
    # for sponsored_products, sponsored_display or sponsored_brands returns the
    # same 26 campaigns each time, verified 20-Aug-2026), so on its own this is
    # just the tab that was requested. `/metrics/tabular` DOES partition —
    # 14-Aug-2026 it returned 6 campaigns / Rs 8,136 under sponsored_products,
    # 1 / Rs 144 under sponsored_brands and nothing under display, summing to
    # the Rs 8,280 the campaigns endpoint reports for the day — so the scraper
    # overwrites this with the tab a campaign actually appeared in.
    #
    # A campaign with no spend in the window appears in no tabular tab, so its
    # value stays the requested-tab default. Filter on it for spend analysis,
    # not for a campaign inventory. `campaign_type` (PLA/Display) is a
    # different axis and always reflects the campaign itself.
    campaign_category: str
    campaign_type: str | None = None          # PLA | Display
    campaign_sub_type: str | None = None      # AUCTION_UP_SELL | PCA | ...
    status: str | None = None                 # ACTIVE | ...
    is_active: bool | None = None
    bid_targeting_type: str | None = None     # KEYWORD | ...
    campaign_targeting_type: str | None = None

    daily_budget: float | None = None
    lifetime_budget: float | None = None
    base_bid: float | None = None

    # ── Windowed: these DO change with the from/to dates, so they can be
    # summed or averaged over a date range. Verified 20-Aug-2026 by fetching
    # the same campaign for a 1-day, 6-day and 31-day window and watching the
    # values move.
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    cpc: float | None = None
    ecpm: float | None = None

    # ── NOT windowed. Zepto returns the same figure whatever date range is
    # requested (Bakers Dozen CKW: orders=158, sov=0.07, ad_position=16 for a
    # 1-day, 6-day and 31-day window alike), and every campaign in the table
    # has exactly one distinct value across all its days. `sov` is labelled
    # "SOV - last 7 day" in Zepto's own UI, i.e. a trailing metric by design.
    #
    # They are stored because they are real, current figures — but they must
    # never be summed across days, and must not be shown as though they
    # describe a chosen window. Summing `orders` per day is exactly what
    # inflated the Units-sold tile to 5,845; see app/services/zepto_ads.py.
    orders: int = 0
    # Zepto's "RoAS (including FOC)" — the campaign table's first RoAS column.
    # Its second, FOC-excluded column renders "-" here and this endpoint's
    # `robas` field is empty; the Analytics view does report it, so it is stored
    # in `robas` below. FOC = free-of-cost impressions Zepto grants, so this
    # runs at or above a pure return-on-money-spent figure.
    roi: float | None = None
    # Share of voice, percent — trailing 7 days, NOT the requested window
    # (Zepto's own column is titled "SOV - last 7 day"). See the note above.
    sov: float | None = None
    # Average ad position — also fixed, not windowed. See the note above.
    ad_position: float | None = None

    campaign_start_date: datetime | None = None
    campaign_end_date: datetime | None = None

    # ── From the Analytics page's campaign_table view, which the Campaign
    # Management endpoint does not report. All date-aware (verified: they scale
    # across 1-day / 6-day / 31-day windows).
    #
    # `revenue` is Zepto's own reported figure. It was previously reconstructed
    # as spend x roi, which came within ~0.1% (7,586 vs 7,580 on 14 Aug) — the
    # gap being RoAS rounded to 2dp — but a reported number beats a derived one.
    revenue: float | None = None
    atc: int | None = None
    # Orders from campaign_table, which IS windowed — unlike the `orders`
    # column above, taken from the campaigns endpoint, which is a lifetime
    # figure that ignores the date range.
    windowed_orders: int | None = None
    # RoAS excluding free-of-cost impressions. The Campaign Management table
    # renders this as "-"; only the Analytics view populates it.
    robas: float | None = None
    cpm: float | None = None
    # Orders split by whether they were for the advertised SKU or another one.
    same_skus: int | None = None
    other_skus: int | None = None
    unique_reach: int | None = None
    new_to_brand_pct: float | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoAdKeywordDaily(SQLModel, table=True):
    """One row per keyword per match type per day, per campaign category —
    Zepto's equivalent of Blinkit's `blinkit_ad_campaign_detail`.

    From `/metrics/tabular` with view=keyword_table. Note the grain: keywords
    are reported per BRAND, not per campaign — the response carries no campaign
    id, so a keyword cannot be attributed to the campaign that bid on it. That
    is the one place Blinkit's detail table is richer, since its rows are keyed
    by campaign.

    A consequence of that missing id: the same keyword bid by two campaigns
    comes back as two rows identical in every field. The parser sums them, so a
    row here means "this keyword, this match type, this day, across every
    campaign that bid it". Verified additive against the campaign table for the
    same day — spend, clicks, add-to-carts and orders agree to the unit.

    `ctr`/`cpc`/`cpm`/`roas` are recomputed from the summed components rather
    than copied, so they stay correct for the summed rows; Zepto's own values
    round CPC to whole rupees anyway. `robas` is spend-weighted, since the
    free-of-cost revenue it excludes is not reported separately.
    """

    __tablename__ = "zepto_ad_keyword_daily"

    __table_args__ = (Index("idx_zakd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    brand_id: str
    campaign_category: str

    keyword: str
    match_type: str | None = None      # BROAD | PHRASE | EXACT

    spend: float = 0.0
    revenue: float | None = None
    impressions: int = 0
    clicks: int = 0
    orders: int | None = None
    atc: int | None = None
    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None
    robas: float | None = None
    same_skus: int | None = None
    other_skus: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoSellerProductPerf(SQLModel, table=True):
    """One row per tenant per SKU per scraped window.

    ⚠️ THREE columns here are NOT facts about `period_start`/`period_end` —
    `stock_on_hand`, `week_on_week_growth`, `month_on_month_growth`. They carry
    the same value on every day of the window a scrape covered, because they
    describe the moment of the CALL: one scrape on 19-Aug wrote `stock_on_hand`
    727 to all 28 sales-days it touched; a later scrape wrote 466.

    Re-scraping an older window returns null for them, which a plain upsert used
    to write over a real reading. Guarded by `_KEEP_IF_NULL` in
    `seller/storage.py` (COALESCE on conflict) since 2026-08-28.

    Everything else on this row IS a fact about the date, `available_stores` and
    `sales_contribution` included — both vary day to day within a single scrape
    job (18/34 SKU-jobs), exactly like `gmv`. An earlier version of this note
    listed them as snapshots; that was wrong. See docs/zepto.md.

    The three snapshot columns will eventually move to a table keyed on the
    scrape JOB rather than the sales date. Not built yet: whether the two growth
    columns are scrape-time readings or window-level aggregates is unproven, and
    stored data cannot settle it (the upsert overwrites in place, so no SKU-day
    has ever had two rows to compare).
    """

    __tablename__ = "zepto_seller_product_perf"

    __table_args__ = (
        Index("idx_zspp_tenant_period", "tenant_id", "period_start", "period_end"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    period_start: date
    period_end: date

    product_variant_id: str
    product_name: str | None = None
    sku_name: str | None = None
    pack_size: str | None = None
    unit_of_measure: str | None = None
    category_name: str | None = None
    subcategory_name: str | None = None

    gmv: float = 0.0
    qty_sold: int = 0
    # Percentages, as returned (e.g. 50.88 means 50.88%).
    sales_contribution: float | None = None
    available_stores: float | None = None
    week_on_week_growth: float | None = None
    month_on_month_growth: float | None = None
    stock_on_hand: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoAdProductDaily(SQLModel, table=True):
    """One row per advertised SKU per campaign category per day.

    From `/metrics/tabular` with view=product_table — the Analytics page's
    Product Performance tab. Answers "which SKUs is the ad spend going to",
    which no other Zepto endpoint reports: the campaigns endpoint stops at
    campaign level and `zepto_seller_product_perf` covers organic sales, not ads.

    `campaign_category` is part of the key. No product was observed under more
    than one ad type, but categories were (Cheese ran under both sponsored
    products and sponsored brands on 19-Aug-2026), so the same guard applies
    here rather than relying on that holding.

    Verified additive and date-aware: 18 Aug Rs 6,474 + 19 Aug Rs 8,353 equals
    the Rs 14,827 the 18-19 range returns, and each day matches the campaign
    table's spend for that day.
    """

    __tablename__ = "zepto_ad_product_daily"

    __table_args__ = (Index("idx_zapd_tenant_date", "tenant_id", "date"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    brand_id: str
    campaign_category: str

    # Zepto's product variant id, from the `product_details` box.
    product_variant_id: str
    product_name: str | None = None
    image_link: str | None = None
    # The SKU's retail category ("Breads & Buns"), NOT the ad type.
    product_category: str | None = None

    spend: float = 0.0
    revenue: float | None = None
    impressions: int = 0
    clicks: int = 0
    orders: int | None = None
    atc: int | None = None
    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None
    robas: float | None = None
    same_skus: int | None = None
    other_skus: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoAdBreakdownDaily(SQLModel, table=True):
    """One row per breakdown bucket per campaign category per day.

    Covers three `/metrics/tabular` views that are structurally identical —
    `category_table`, `city_table` and `page_table`. Each returns nothing but a
    `{dim}_name` and the same twelve metrics, so three separate tables would
    have had identical columns and three copies of the same parser. The view is
    stored in `dimension` instead.

    * `dimension="category"` — the RETAIL category ("Breads & Buns", "Cheese"),
      not the ad type. Both are in the key: Cheese ran under sponsored products
      AND sponsored brands on 19-Aug-2026 (Rs 1,422 and Rs 158), so dropping the
      ad type would silently discard one.
    * `dimension="city"` — Zepto's delivery city. Only Bengaluru has had spend
      on this account so far.
    * `dimension="page"` — where the ad appeared: Search Page, Product Details
      Page, Trending Page, Category Page.

    None of these views reports CTR, unlike the product and keyword ones.
    """

    __tablename__ = "zepto_ad_breakdown_daily"

    __table_args__ = (
        Index("idx_zabd_tenant_date", "tenant_id", "date"),
        Index("idx_zabd_dimension", "tenant_id", "dimension", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    brand_id: str
    campaign_category: str

    # Which tabular view this row came from: category | city | page.
    dimension: str
    # The bucket's name — a retail category, a city, or a page type.
    name: str

    spend: float = 0.0
    revenue: float | None = None
    impressions: int = 0
    clicks: int = 0
    orders: int | None = None
    atc: int | None = None
    cpc: float | None = None
    cpm: float | None = None
    roas: float | None = None
    robas: float | None = None
    same_skus: int | None = None
    other_skus: int | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoSellerProductCityDaily(SQLModel, table=True):
    """One row per tenant per SKU per **city** per day.

    A finer grain than `ZeptoSellerProductPerf`, not a replacement: that table is
    SKU x day summed over every city, this one splits the same money by city.
    **Never sum across the two** — they hold the same rupees at different
    resolutions, exactly like the four `zepto_ad_*` tables.

    Why a separate table rather than city columns on the existing one: mixing an
    all-cities row and per-city rows in one table makes `sum(gmv)` silently wrong
    for anyone who forgets to filter. `zepto_ad_breakdown_daily` already
    demonstrates that failure — it totals ~3x its real spend because it stacks
    three views of the same money.

    Zepto exposes no city dimension inside a single product-performance
    response, but `cityIds` does filter it (verified 2026-08-26: Bengaluru
    returned 9 SKUs / Rs 52,215 for 25-Aug while three other cities returned
    nothing). So a city split means one call per city, the same shape as
    `fetch_sales_by_city`.

    This is what the Analytics "Revenue by category & city" heatmap needs: it
    requires city and category on one row, which no other Zepto table has.
    """

    __tablename__ = "zepto_seller_product_city_daily"

    __table_args__ = (
        Index("idx_zspcd_tenant_date", "tenant_id", "date"),
        Index("idx_zspcd_city", "tenant_id", "city_id", "date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    date: date
    city_id: str
    # Zepto's own prefixed form ("BLR - Bengaluru"), left uncleaned so the
    # dashboard shows what the seller portal shows.
    city_name: str | None = None

    product_variant_id: str
    product_name: str | None = None
    sku_name: str | None = None
    category_name: str | None = None
    subcategory_name: str | None = None

    gmv: float = 0.0
    qty_sold: int = 0

    scraped_at: datetime = Field(default_factory=now_ist)


# ── PO Management ────────────────────────────────────────────────────────────
# Zepto's supply-chain side: what Zepto ordered, what shipped, what arrived.
# Scraped from the `/vendor` app on fcc.zepto.co.in (see endpoints.py), which
# accepts the same saved session as the analytics endpoints.
#
# Three tables, not one, for the same reason the ad tables are separate: a PO,
# its shipment and its receipt are three different grains, and one row of each
# can exist without the others (a PO with no ASN yet, a GRN against a PO from
# before the scrape window). Merging them would need nullable everything and
# make `sum(qty)` meaningless.


class ZeptoPO(SQLModel, table=True):
    """One row per purchase order — the header, not its line items.

    Zepto's `/api/v1/po/filter` returns `itemsCount` but not the lines
    themselves; those sit behind a per-PO detail call that has not been
    captured. So this supports "how much did Zepto order, and did it arrive",
    but NOT the per-SKU PO history that Blinkit's `blinkit_po_items` backs.

    `total_grn_qty` over `total_qty` is the fill rate — the same quantity
    Blinkit's seller scorecard reports, and the only route to a Zepto fill rate
    given Zepto publishes no scorecard page.
    """

    __tablename__ = "zepto_po"

    __table_args__ = (
        Index("idx_zpo_tenant_date", "tenant_id", "po_date"),
        Index("idx_zpo_status", "tenant_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    po_id: str                       # Zepto's own id, e.g. "P5363881"
    vin_po_no: str | None = None
    status: str | None = None        # PENDING_ACKNOWLEDGEMENT, OPEN_TO_FULFILL, …

    vendor_code: str | None = None
    vendor: str | None = None
    vendor_relation_type: str | None = None

    location_code: str | None = None
    location: str | None = None
    mh_code: str | None = None
    # Zepto's prefixed form ("BLR - Bengaluru"), left uncleaned to match the
    # seller portal and the other Zepto city columns.
    city: str | None = None

    po_date: date | None = None
    scheduled_date: date | None = None
    expiry_date: date | None = None

    items_count: int | None = None
    total_qty: int | None = None
    total_asn_qty: int | None = None
    total_grn_qty: int | None = None
    total_value: float | None = None

    payment_terms: str | None = None
    source: str | None = None
    entity_code: str | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoGRN(SQLModel, table=True):
    """One row per goods-receipt note — what Zepto actually received.

    `po_qty` and `grn_qty` sit on the same row, so fill rate is readable
    directly per receipt (observed 201/202 = 99.5% on 20-Aug-2026) without
    joining back to the PO.
    """

    __tablename__ = "zepto_grn"

    __table_args__ = (
        Index("idx_zgrn_tenant_date", "tenant_id", "grn_date"),
        Index("idx_zgrn_po", "tenant_id", "po_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    grn_no: str
    asn_no: str | None = None
    ext_asn_no: str | None = None
    po_id: str | None = None
    vin_po_no: str | None = None
    status: str | None = None

    vendor_code: str | None = None
    vendor_name: str | None = None
    location_code: str | None = None
    location: str | None = None

    po_qty: int | None = None
    asn_qty: int | None = None
    grn_qty: int | None = None
    remaining_qty: int | None = None
    po_value: float | None = None
    grn_value: float | None = None

    grn_date: date | None = None
    entity_code: str | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoASN(SQLModel, table=True):
    """One row per advance shipping notice — what the vendor said was sent.

    Sits between the PO and the GRN: `po_qty` -> `asn_qty` -> `grn_qty` shows
    where a shortfall happened (never shipped, or shipped and not received).
    """

    __tablename__ = "zepto_asn"

    __table_args__ = (
        Index("idx_zasn_tenant_date", "tenant_id", "asn_date"),
        Index("idx_zasn_po", "tenant_id", "po_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    asn_no: str
    ext_asn_no: str | None = None
    po_id: str | None = None
    vin_po_no: str | None = None
    status: str | None = None

    vendor_code: str | None = None
    vendor_name: str | None = None
    location_code: str | None = None
    external_location_code: str | None = None
    location: str | None = None

    po_qty: int | None = None
    asn_qty: int | None = None
    grn_qty: int | None = None
    remaining_qty: int | None = None
    po_value: float | None = None
    asn_value: float | None = None

    asn_date: date | None = None
    entity_code: str | None = None

    scraped_at: datetime = Field(default_factory=now_ist)


class ZeptoPOItem(SQLModel, table=True):
    """One row per SKU per purchase order — the PO's line items.

    From `/api/v1/po/{po_id}/items`, one call per PO. The list endpoint returns
    `itemsCount` but not the lines, so this is a second pass over the POs already
    scraped.

    Two things live here and nowhere else in the system:

    * **Cost price** (`unit_price`, e.g. Rs 53.33 against an Rs 80 MRP) — the
      margin Zepto takes. No other Zepto endpoint reports it.
    * **Per-SKU fill rate** (`grn_qty` / `po_qty`). The GRN table gives fill rate
      per delivery; this gives it per product, which is what showed that two SKUs
      were halved while two others in the SAME delivery were accepted in full
      (GrnCode56384162, 22-Aug-2026).

    `product_variant_id` is Zepto's `pvId`, the SAME id `zepto_seller_product_perf`
    keys on — so PO lines join to the Products page directly, with no name
    matching and no `sku_map` bridge.
    """

    __tablename__ = "zepto_po_items"

    __table_args__ = (
        Index("idx_zpoi_tenant_po", "tenant_id", "po_id"),
        Index("idx_zpoi_pv", "tenant_id", "product_variant_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    platform: str = "zepto"
    upsert_key: str = Field(unique=True)
    scrape_job_id: uuid.UUID | None = Field(default=None, foreign_key="scrape_jobs.id")

    po_id: str
    line_id: str | None = None       # Zepto's per-line uuid
    status: str | None = None        # NO_UPDATES, …

    sku_code: str | None = None
    sku_name: str | None = None
    # Zepto's `pvId` — joins to zepto_seller_product_perf.product_variant_id.
    product_variant_id: str | None = None
    ean_no: str | None = None
    hsn_code: str | None = None
    brand: str | None = None

    po_qty: int | None = None
    asn_qty: int | None = None
    grn_qty: int | None = None
    remaining_qty: int | None = None

    # What Zepto PAYS per unit, against the `mrp` it sells at.
    unit_price: float | None = None
    mrp: float | None = None
    total_value: float | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    cess: float | None = None

    scheduled_date: date | None = None
    scraped_at: datetime = Field(default_factory=now_ist)
