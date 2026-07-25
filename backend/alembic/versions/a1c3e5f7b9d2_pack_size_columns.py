"""pack-size columns on public product tables (supersedes grammage)

Promotes Blinkit's per-product `unit` string (e.g. "225 ml", "12 x 250 ml",
"225 ml + 225 ml + 225 ml") out of the `search_listings.extra` blob — and out of
nowhere at all for `sku_snapshots`, which dropped it entirely — onto real columns:

    pack_raw    the source string, verbatim (audit trail)
    pack_size   total content normalized to one base unit (float, NULL if unparsed)
    pack_uom    that base unit — "ml" | "g" | "pc"
    pack_count  number of physical items (int, NULL if unparsed)

Per-unit price is derived at read time (price ÷ pack_size), never a column. See
scraper/utils/pack.py + docs/per-unit-price.md.

Also DROPS `grammage` (added 2026-07-22 in c7d1e9f3a2b4, never populated): a single
grams-only float can't represent the ~93% of this catalog measured in ml, and can't
express pack count. Superseded by the four columns above.

String columns get server_default="" so existing rows satisfy NOT NULL, mirroring the
merchant-column revision e6c2a9d4f1b8; `pack_size`/`pack_count` are nullable ("not yet
parsed" is a real state). Nullable/defaulted adds + one drop of a wholly-NULL column —
no table rewrite, safe on the shared DB. A backfill from `extra.unit` is a SEPARATE,
manually-run script, not part of this migration.

Revision ID: a1c3e5f7b9d2
Revises: c7d1e9f3a2b4
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, Sequence[str], None] = "c7d1e9f3a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("search_listings", "sku_snapshots")


def _str_col(name: str) -> sa.Column:
    # server_default so existing rows satisfy NOT NULL; every writer sets it explicitly
    # and "" is the correct "unparsed/unknown" for history.
    return sa.Column(name, sqlmodel.sql.sqltypes.AutoString(),
                     nullable=False, server_default="")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, _str_col("pack_raw"))
        op.add_column(t, sa.Column("pack_size", sa.Float(), nullable=True))
        op.add_column(t, _str_col("pack_uom"))
        op.add_column(t, sa.Column("pack_count", sa.Integer(), nullable=True))
        op.drop_column(t, "grammage")


def downgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("grammage", sa.Float(), nullable=True))
        op.drop_column(t, "pack_count")
        op.drop_column(t, "pack_uom")
        op.drop_column(t, "pack_size")
        op.drop_column(t, "pack_raw")
