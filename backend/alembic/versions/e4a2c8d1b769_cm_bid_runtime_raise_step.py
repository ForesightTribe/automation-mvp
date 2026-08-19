"""cm_bid_runtime.raise_step — escalating raise state

The bid raise no longer scales with distance-from-target. Sponsored slots sit ~4 apart
(1/5/9/13/17), so slot distance was almost always either ≥4 or 1–2: the old four-tier
table resolved to ₹100 or ₹25 in practice and its ₹50 tier fired **once in 88 recorded
steps**. Slot distance is also a poor proxy for rupee distance — the bid→position curve is
a staircase with treads hundreds of rupees wide, so "one slot away" can cost ₹50 or ₹600.

The step now escalates on the feedback each tick already provides: if the last raise did
not move the position we are mid-tread and the next step must be bigger; if it did, we
crossed a riser and reset to base. `raise_step` is that carried state.

- NULL = "start from the base step" — the state at a window open, immediately after a
  riser is crossed, and for a rule that has never climbed. So an existing row needs no
  backfill: NULL is already the correct starting value.
- Only a genuine raise writes it. A drift recovery snap-back is a precise return to a
  known-good price rather than a climb, and holding ticks aren't climbing at all; letting
  either escalate would make the next real raise start from an inflated step.

Additive and safe: one NULLABLE column, no server default, nothing rewritten, nothing else
altered or dropped. Overshoot from the faster climb is recovered by the drift-down, which
is what makes an aggressive raise safe — climb fast to find the position, descend slowly to
find the price.

Hand-written, NOT `--autogenerate`: autogenerate on this shared DB repeatedly sweeps in
unrelated drift (it has previously tried to DROP `ad_automation_rules`/`_actions` and the
`idx_listing_tenant_store` index, and to churn FKs). This file contains only the intended
change.

Revision ID: e4a2c8d1b769
Revises: d1f7b3c9e485
Create Date: 2026-08-17
"""
import sqlalchemy as sa
from alembic import op

revision = "e4a2c8d1b769"
down_revision = "d1f7b3c9e485"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cm_bid_runtime", sa.Column("raise_step", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cm_bid_runtime", "raise_step")
