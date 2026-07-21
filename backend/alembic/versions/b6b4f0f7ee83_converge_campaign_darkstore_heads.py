"""converge campaign + darkstore heads

No schema changes — a MERGE migration only. History forked at `adcf3ccd495b`
(restructure_blinkit_marketing_tables) into two lines that never rejoined:

  - campaign branch:  f1a2b3c4d5e6 (search_results) -> b7c3d8e2f1a9 (daily_budget)
  - main line:        f3a9c1d7b2e5 (public per-tenant) -> ... -> e6c2a9d4f1b8 (store grain)

The shared DB only ever advanced down the main line (alembic_version =
e6c2a9d4f1b8); the campaign branch was never applied there. This revision
converges both heads so Alembic has a single head again.

**Apply this with `alembic stamp b6b4f0f7ee83`, NOT `upgrade`.** The campaign
branch's DDL must not run against the shared DB:
  - b7c3d8e2f1a9 adds blinkit_ad_campaigns.daily_budget, but that column already
    exists (created out of band by the campaign-manager models) -> an upgrade
    would fail with "column already exists".
  - f1a2b3c4d5e6 creates `search_results`, which is dead legacy — superseded by
    the per-tenant search_snapshots/search_listings schema and referenced by no
    live model. It is intentionally never created; stamping skips it for good.

Future campaign-manager migrations should chain off this revision.

Revision ID: b6b4f0f7ee83
Revises: e6c2a9d4f1b8, b7c3d8e2f1a9
Create Date: 2026-07-21 19:14:08.309602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b6b4f0f7ee83'
down_revision: Union[str, Sequence[str], None] = ('e6c2a9d4f1b8', 'b7c3d8e2f1a9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
