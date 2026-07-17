"""store grain: merchant_id + merchant_type columns

Promotes the dark store off each product onto real columns. Blinkit stamps every
product with the store that fulfils it (`merchant_id`) and the tier it is sold under
(`merchant_type`) inside the atc block; the scraper has always extracted both but
only `search_listings` kept them — buried in the `extra` JSON blob, unqueryable and
unindexable. `sku_snapshots` kept `merchant_id` alone, and `search_snapshots` kept
nothing.

Adds:
  search_listings.merchant_id / .merchant_type   — per product; one response
                                                    routinely spans several stores
                                                    and tiers, interleaved by rank
  search_snapshots.merchant_id                   — the EXPRESS store for the
                                                    coordinate (this row stays
                                                    location-grain: rank/SoV are the
                                                    blended list the shopper sees)
  sku_snapshots.merchant_type                    — tier for the store-grain facts

**No backfill, by decision.** Existing rows keep "" and the store-level series starts
from the next scrape. Nothing is lost by waiting: the historical merchant fields are
still in `search_listings.extra` (100% coverage, including 1,313 longtail rows), so a
backfill can be added later as its own revision if the history is ever wanted:

    UPDATE search_listings
    SET merchant_id   = COALESCE(extra->>'merchant_id', ''),
        merchant_type = COALESCE(extra->>'merchant_type', '')
    WHERE merchant_id = '';          -- NOT optional: rows written after this
                                     -- revision keep these in the columns and no
                                     -- longer in `extra`, so an unguarded UPDATE
                                     -- would blank them out.

`sku_snapshots.merchant_type` has no direct source — it would have to be inferred by
joining `search_listings` on (platform_product_id, merchant_id), which resolves ~98.4%
of rows but leaves 16 (product, store) pairs whose tier conflicts across history.

"" therefore means "unknown", never "express". Readers must not treat empty as a
default — new rows carry the real value, old rows carry nothing.

See docs/darkstores.md.

Revision ID: e6c2a9d4f1b8
Revises: d4a9c7e2b6f1
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "e6c2a9d4f1b8"
down_revision: Union[str, Sequence[str], None] = "d4a9c7e2b6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col(name: str) -> sa.Column:
    # server_default so the existing rows satisfy NOT NULL. It stays on the column:
    # every writer sets these explicitly, and "" is the correct "unknown" for history.
    return sa.Column(name, sqlmodel.sql.sqltypes.AutoString(),
                     nullable=False, server_default="")


def upgrade() -> None:
    op.add_column("search_listings", _col("merchant_id"))
    op.add_column("search_listings", _col("merchant_type"))
    op.add_column("search_snapshots", _col("merchant_id"))
    op.add_column("sku_snapshots", _col("merchant_type"))

    # Store-grain reads group by (tenant, store, time) — mirrors idx_sku_tenant_store.
    op.create_index("idx_listing_tenant_store", "search_listings",
                    ["tenant_id", "merchant_id", "scraped_at"])


def downgrade() -> None:
    op.drop_index("idx_listing_tenant_store", table_name="search_listings")
    op.drop_column("sku_snapshots", "merchant_type")
    op.drop_column("search_snapshots", "merchant_id")
    op.drop_column("search_listings", "merchant_type")
    op.drop_column("search_listings", "merchant_id")
