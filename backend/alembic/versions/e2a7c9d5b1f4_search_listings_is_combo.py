"""search_listings.is_combo — separate combos/multipacks from main SKUs

Mirrors sku_snapshots.is_combo onto the keyword-scrape detail so Competition price
comparisons can filter to singular SKUs (combos are priced higher and stocked
selectively). Adds the flag and backfills existing rows (own + competitor) from the
product name with the same rule the scraper now applies on write.

Revision ID: e2a7c9d5b1f4
Revises: d1f4b8c6a3e7
Create Date: 2026-07-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2a7c9d5b1f4"
down_revision: Union[str, Sequence[str], None] = "d1f4b8c6a3e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirror of scraper.utils.search_result._COMBO_RE (POSIX form for Postgres ~*).
_COMBO_PATTERN = r"(pack of|combo|buy\s*\d+\s*get|\s\+\s)"


def upgrade() -> None:
    op.add_column(
        "search_listings",
        sa.Column("is_combo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE search_listings SET is_combo = TRUE WHERE product_name ~* :pat"
        ).bindparams(pat=_COMBO_PATTERN)
    )


def downgrade() -> None:
    op.drop_column("search_listings", "is_combo")
