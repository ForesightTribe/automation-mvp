"""sku_snapshots.is_combo — separate combos/multipacks from main SKUs

Combos ("Pack of N", "… + … Combo", "Buy N Get 1 Free") are stocked selectively,
so the availability views analyse them apart from singular main SKUs. Adds the
flag and backfills existing rows from the product name with the same rule the
scraper now applies on write.

Revision ID: d1f4b8c6a3e7
Revises: c9e1a4b7d206
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f4b8c6a3e7"
down_revision: Union[str, Sequence[str], None] = "c9e1a4b7d206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirror of scraper.utils.search_result._COMBO_RE (POSIX form for Postgres ~*).
_COMBO_PATTERN = r"(pack of|combo|buy\s*\d+\s*get|\s\+\s)"


def upgrade() -> None:
    op.add_column(
        "sku_snapshots",
        sa.Column("is_combo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE sku_snapshots SET is_combo = TRUE WHERE product_name ~* :pat"
        ).bindparams(pat=_COMBO_PATTERN)
    )


def downgrade() -> None:
    op.drop_column("sku_snapshots", "is_combo")
