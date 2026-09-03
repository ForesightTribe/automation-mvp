"""merge zepto automations + zepto private-data lines

BOOKKEEPING ONLY — both `upgrade()` and `downgrade()` are deliberately empty.

Two migration lines grew from `c8f4e91a37d2` in parallel branches:

    ours   c8f4e91a37d2 -> d3b8f6a04c71 -> f2a71c4d8e93   (sku extra/variant, is_ad)
    theirs c8f4e91a37d2 -> d7e3b81c4a95 -> ...            (PO, cities, V7, sales rename)
                        -> b6d24a08f3c1

Both were APPLIED to the shared database — every table from both lines was verified
present before this merge was written. What diverged was the ledger, not the schema:
each of us ran `alembic upgrade head` from a branch that could only see its own
revision files, so alembic saw a linear history and stamped `alembic_version` with
its own head, overwriting the other's record. The DDL all ran; the bookkeeping
forgot half of it.

⚠️ This revision must be reached with `alembic stamp`, NEVER `alembic upgrade`.
Upgrading from a database stamped at one line's head would try to replay the other
line in full — `create_table` against tables that already exist — and fail partway,
leaving the schema half-migrated and the ledger worse than before.

The general lesson, which this repo has now paid for twice: when two people migrate
one shared database from separate branches, the version table records whoever ran
last, not what is actually in the database. Check the tables, not the stamp.

Revision ID: 6eb277c7b1fb
Revises: b6d24a08f3c1, f2a71c4d8e93
Create Date: 2026-09-02 23:55:49.319044

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6eb277c7b1fb'
down_revision: Union[str, Sequence[str], None] = ('b6d24a08f3c1', 'f2a71c4d8e93')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
