"""add search_results table (was missing from DB)

Revision ID: f1a2b3c4d5e6
Revises: adcf3ccd495b
Create Date: 2026-07-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'adcf3ccd495b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `search_results` is retired dead legacy — superseded by the per-tenant
    # search_snapshots / search_listings schema (f3a9c1d7b2e5 onward) and referenced by
    # no live model. Per the decision on 2026-07-21 it is not needed, so this revision
    # no longer creates it: fresh databases correctly never get the table, and databases
    # that already have it keep it (harmless). The revision/id is preserved only for
    # history continuity. See merge b6b4f0f7ee83.
    pass


def downgrade() -> None:
    pass
