"""merge sku_map line and ad_automation line into one head

No schema changes — this is a MERGE migration only. Two feature branches split at
`e2a7c9d5b1f4` and each added independent, additive migrations to the shared DB:

  - f5b3d8e1c4a2  sku_map            (this line, + explorer_runs on top)
  - 9cba1aca0fa7  ad_automation      (automation_dhriti branch)

Both are already applied to the shared DB. This revision converges the two heads
so Alembic has a single linear history again. `explorer_runs` (a3e8d1f6c2b9) sits
on top of this merge.

Revision ID: c3f9e1a7d2b8
Revises: 9cba1aca0fa7, f5b3d8e1c4a2
Create Date: 2026-07-08

"""
from typing import Sequence, Union


revision: str = "c3f9e1a7d2b8"
down_revision: Union[str, Sequence[str], None] = ("9cba1aca0fa7", "f5b3d8e1c4a2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
