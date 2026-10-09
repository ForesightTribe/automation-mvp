"""merge: rejoin the two migration lines that split at a1c4e7d93f20

Revision ID: f1a8c3e5b7d2
Revises: c3a9e5d7f2b1, d4b7e2a9c615
Create Date: 2026-10-07

A NO-OP. It changes no table; it only tells alembic the two lines are one again.

Two branches added migrations on top of `a1c4e7d93f20` at the same time, both applied to the
shared database:

  * `fix/zepto-private-refactor`: `b8e2d4f6a1c3` (bid automations target ad slots) →
    `c3a9e5d7f2b1` (zepto_ad_campaign_detail), applied 2026-10-06;
  * `dev`: `d4b7e2a9c615` (drops the dead Instamart `campaign_type` column), applied
    2026-10-07.

`alembic_version` then held only `d4b7e2a9c615`, though all three are in the schema —
checked read-only on 2026-10-07 (every column / table / index of b8e2 and c3a9 present, both
dropped Instamart columns absent).

On the shared database this revision is STAMPED, not run (it has nothing to run):
`alembic stamp --purge f1a8c3e5b7d2` — that records both lines as applied in one step.
"""
from typing import Sequence, Union

revision: str = 'f1a8c3e5b7d2'
down_revision: Union[str, Sequence[str], None] = ('c3a9e5d7f2b1', 'd4b7e2a9c615')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
