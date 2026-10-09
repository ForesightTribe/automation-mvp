"""bid automations target AD SLOTS: record the slot, the page's ads, our organic listings

Revision ID: b8e2d4f6a1c3
Revises: a1c4e7d93f20
Create Date: 2026-10-05

A bid rule's target is now an ad slot — the Nth sponsored listing on the page
(campaign_manager/ad_slots.py) — instead of a page position. Additive only:

  cm_bid_store_reads  + ad_slot            the slot the decision acted on (`position` stays
                      + ad_positions       the PAGE position); every ad's page position, and
                      + organic_positions  our organic listings' — for History and the
                                           organic-overlap warning
  cm_run_log          + ad_slot            same split for the decision row
                      + measured_in        "ad_slot" on rows the new engine wrote, so History
                                           can read `target` right even when `ad_slot` is empty
  cm_bid_runtime      + measured_in        "ad_slot" on state the new engine wrote; NULL =
                                           page positions, which the engine then ignores

Deliberately NO data change. The learned state in `cm_bid_runtime` is in page positions
and must not be read as slots — but wiping it here would not help: the old code keeps
running (and writing page positions) until the new code is deployed. `measured_in` lets
the new engine recognise and discard it on its own, whenever it starts.

Safe to apply before the code: old code never selects these columns.

⚠️ HAND-WRITTEN. The shared database carries tables from branches not merged here, so
`--autogenerate` emits DROP TABLE for them. Keep editing by hand.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f6a1c3'
down_revision: Union[str, Sequence[str], None] = 'a1c4e7d93f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('cm_bid_store_reads', sa.Column('ad_slot', sa.Integer(), nullable=True))
    op.add_column('cm_bid_store_reads', sa.Column('ad_positions', sa.JSON(), nullable=True))
    op.add_column('cm_bid_store_reads', sa.Column('organic_positions', sa.JSON(), nullable=True))
    op.add_column('cm_run_log', sa.Column('ad_slot', sa.Integer(), nullable=True))
    op.add_column('cm_run_log', sa.Column('measured_in', sa.String(), nullable=True))
    op.add_column('cm_bid_runtime', sa.Column('measured_in', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('cm_bid_runtime', 'measured_in')
    op.drop_column('cm_run_log', 'measured_in')
    op.drop_column('cm_run_log', 'ad_slot')
    op.drop_column('cm_bid_store_reads', 'organic_positions')
    op.drop_column('cm_bid_store_reads', 'ad_positions')
    op.drop_column('cm_bid_store_reads', 'ad_slot')
