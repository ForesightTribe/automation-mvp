"""merge watchlist caps + seller-hub cleanup lines

BOOKKEEPING ONLY — both `upgrade()` and `downgrade()` are deliberately empty.

Two lines grew from `8f3230b33b37` (add blinkit_seller_hub_sales_order) in parallel:

    dev      8f3230b33b37 -> 4b7e2c91d0a3   drop retired seller-hub daily tables
    public   8f3230b33b37 -> c639761284ff   tenant_watchlist_caps (fix/public-scrape-sep30)

Unlike `6eb277c7b1fb`, only ONE of them had run when this was written (checked
2026-10-03): the shared database was stamped `4b7e2c91d0a3` and `tenant_watchlist_caps`
did not exist. So this revision is reached with a plain `alembic upgrade head`, which
runs `c639761284ff` (creates the table, copies the current caps across) and then
records this merge — NOT with `alembic stamp`, which would mark the caps table as
present when it is not.

Before running it anywhere else, check the table, not the stamp: if
`tenant_watchlist_caps` already exists there, `c639761284ff` has run and this revision
must be stamped instead.

Revision ID: 335b665ed095
Revises: 4b7e2c91d0a3, c639761284ff
Create Date: 2026-10-03 12:25:41.807723

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '335b665ed095'
down_revision: Union[str, Sequence[str], None] = ('4b7e2c91d0a3', 'c639761284ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
