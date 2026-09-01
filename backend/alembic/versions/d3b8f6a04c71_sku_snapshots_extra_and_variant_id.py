"""sku_snapshots: `extra` JSON + `variant_id`

Zepto returns far more per product than the shared listing schema carries —
brand id, ratings and review counts, manufacturer, country of origin, shelf life,
purchase caps, relevance scores, the raw pack string. `search_listings` already
has an `extra` blob for that kind of thing; `sku_snapshots` has none, so the data
had nowhere to go.

WHY HERE AND NOT ON `search_listings`
-------------------------------------
Measured on a real run: a national keyword scrape produces ~212,000
`search_listings` rows against ~12,000-37,000 `sku_snapshots` rows — the SKU
table is **6-17x smaller** and own-brand only. A JSON blob costs ~400 bytes a
row, so putting it on the keyword table would be ~85 MB per run against a 500 MB
quota, for fields nothing currently queries. On the SKU table it is ~10 MB.

So the keyword table stays lean and the SKU table takes the richness. Promote a
field out of `extra` onto a real column when a query actually needs it; a
backfill over ~25k rows is cheap.

An earlier draft of this work proposed an `is_ad` column on `search_listings`
(sponsored vs organic share of voice). **Dropped after measurement**:
`is_fly_wheel_ad` is present on 100% of items and `False` on all 557 sampled,
along with every other ads/ranking field — Zepto ships the schema but zeroes the
values for anonymous clients. A column that is always False is worse than no
column, because it reads as a measurement. See
zepto-cm-exp/public_scraper/FIELDS.md.

`variant_id` is a real column rather than an `extra` key because it is an
identity: Zepto has both a product id and a variant id, `platform_product_id`
holds only one of them, and the variant is what dedupe keys on.

Both nullable with no server_default — an instant catalogue-only change in
Postgres, no table rewrite, no meaningful lock. **Blinkit rows simply carry
NULL**; nothing about the Blinkit path changes.

Revision ID: d3b8f6a04c71
Revises: c8f4e91a37d2
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql


revision: str = "d3b8f6a04c71"
down_revision: Union[str, Sequence[str], None] = "c8f4e91a37d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON (not JSONB): matches `search_listings.extra`, which is declared
    # sa.JSON via the SQLModel `Column(JSON)`. Keeping the two the same means one
    # reader shape for both tables. Nothing indexes into this blob — the moment
    # something needs to, that key earns a real column instead.
    op.add_column(
        "sku_snapshots",
        sa.Column("extra", sa.JSON(), nullable=True),
    )
    # Nullable, no default: "" would be indistinguishable from "this marketplace
    # has no variant concept", which is exactly Blinkit's case.
    op.add_column(
        "sku_snapshots",
        sa.Column("variant_id", sqlmodel.sql.sqltypes.AutoString(),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sku_snapshots", "variant_id")
    op.drop_column("sku_snapshots", "extra")
