"""converge pack_size + campaign_data_cache heads

Revision ID: 2bb4d44b4cf7
Revises: a1c3e5f7b9d2, d8e2f1a4c3b7
Create Date: 2026-07-25 09:35:21.482965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2bb4d44b4cf7'
down_revision: Union[str, Sequence[str], None] = ('a1c3e5f7b9d2', 'd8e2f1a4c3b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
