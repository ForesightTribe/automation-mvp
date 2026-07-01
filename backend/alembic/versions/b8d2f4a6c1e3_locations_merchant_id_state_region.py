"""marketplace_locations: add merchant_id/state/region, key on merchant_id

Part of the public-scraper refactor. The darkstore catalog is keyed by the
platform's merchant_id (stable store identity); pincode/zone are unreliable in
the source data and are best-effort metadata only. Table is empty, so this is a
clean structural change.

Revision ID: b8d2f4a6c1e3
Revises: f3a9c1d7b2e5
Create Date: 2026-06-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "b8d2f4a6c1e3"
down_revision: Union[str, Sequence[str], None] = "f3a9c1d7b2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("marketplace_locations",
                  sa.Column("merchant_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))
    op.add_column("marketplace_locations",
                  sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))
    op.add_column("marketplace_locations",
                  sa.Column("region", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))
    op.drop_constraint("uq_mploc_mp_zone", "marketplace_locations", type_="unique")
    op.create_unique_constraint("uq_mploc_mp_merchant", "marketplace_locations", ["mp_slug", "merchant_id"])


def downgrade() -> None:
    op.drop_constraint("uq_mploc_mp_merchant", "marketplace_locations", type_="unique")
    op.create_unique_constraint("uq_mploc_mp_zone", "marketplace_locations", ["mp_slug", "city", "zone", "pincode"])
    op.drop_column("marketplace_locations", "region")
    op.drop_column("marketplace_locations", "state")
    op.drop_column("marketplace_locations", "merchant_id")
