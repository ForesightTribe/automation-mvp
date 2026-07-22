"""add grammage to public product tables

Adds a nullable `grammage` (pack size in grams) column to `search_listings` and
`sku_snapshots`. Provisioned blank — grammage lives in the product name today
("400 g") and is a known system-wide gap; the per-gram price views in the
Reports/Competition endpoint compute None until a scraper/backfill populates it.

Nullable add only — no data rewrite, safe on the shared DB. Chains off the
single converged head b6b4f0f7ee83.

Revision ID: c7d1e9f3a2b4
Revises: b6b4f0f7ee83
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7d1e9f3a2b4"
down_revision: Union[str, Sequence[str], None] = "b6b4f0f7ee83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_listings", sa.Column("grammage", sa.Float(), nullable=True)
    )
    op.add_column(
        "sku_snapshots", sa.Column("grammage", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sku_snapshots", "grammage")
    op.drop_column("search_listings", "grammage")
