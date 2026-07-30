"""add cm_bid, cm_ops to lane enum (corrective)

Revision ID: f2a7c4e1d9b3
Revises: e5c9b2d7a418
Create Date: 2026-07-30

The cm.* jobs run in the `cm_bid` / `cm_ops` lanes. Their enum values were meant to be
added by aef972735d57 (the cm-tables migration), but on the shared DB that revision was
stamped during a multi-author merge — so the tables landed while the `ALTER TYPE`
never ran, and the runner fails to claim a cm job (invalid input value for enum lane:
"cm_bid"). This mirrors e3b1f7a9c2d5 for the ad lanes: a dedicated, idempotent migration
that self-heals every environment. `IF NOT EXISTS` makes it a no-op where it already ran.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a7c4e1d9b3"
down_revision: Union[str, Sequence[str], None] = "e5c9b2d7a418"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG 12+ allows ADD VALUE inside a transaction block (the values are only added,
    # never used in this same transaction). Supabase is PG 15.
    for value in ("cm_bid", "cm_ops"):
        op.execute(sa.text(f"ALTER TYPE lane ADD VALUE IF NOT EXISTS '{value}'"))


def downgrade() -> None:
    # Postgres does not support removing enum values — downgrade is a no-op.
    pass
