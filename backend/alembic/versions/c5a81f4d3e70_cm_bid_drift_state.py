"""cm_bid_runtime drift + unreachable-target state

Adds the four columns the bid drift-down and the unreachable-target fallback need
(docs/campaign-manager-v2-implementation.md V4.13). Once a keyword HOLDS its target
position the optimizer shaves a percentage off the bid each tick; when a shave goes one
step too far and the position is lost it snaps back to the last bid known to hold and
stops shaving for a while.

- `last_holding_cpm` — the bid we last observed holding target. Refreshed on EVERY holding
  tick, so the snap-back tracks the market instead of returning to a price that worked an
  hour ago. Also the signal that distinguishes "our own drift overshot" (we are off target
  BELOW a bid known to hold → snap back) from "a competitor outbid us" (off target at or
  above it → normal raise).
- `drift_paused_until` — when shaving may resume after an overshoot. Gates the DECREASE
  only; raises are never blocked by it, so being outbid during a pause is still answered
  on the next tick.
- `effective_target` — the position actually achieved once the bid is pinned at `max_bid`
  and the real target is still out of reach. Adopted as the working target so drift can
  find the cheapest bid that holds it, rather than sitting at the ceiling paying the
  maximum for a position the maximum did not buy.
- `effective_at_max_bid` — the ceiling `effective_target` was derived at. The conclusion is
  void the moment the rule's `max_bid` differs; most sharply when the ceiling is RAISED,
  where a stale relaxed target would have the optimizer drift DOWN after being given more
  room to climb.

Additive and safe:

- both columns NULLABLE with no server default, so nothing is rewritten and a row with
  NULLs means "no drift state yet" — exactly the state a fresh rule starts in;
- `cm_bid_runtime` has **0 rows** at the time of writing, so there is no data to migrate;
- behaviour is unchanged on deploy: the feature is off unless `CM_BID_DRIFT_PCT` is set
  above its default of 0, and at 0 the optimizer's decision logic is byte-for-byte the
  behaviour it had before (freeze at target, step down only when BETTER than target);
- both columns are cleared whenever a bid window opens, so state never leaks across days;
- nothing else is altered or dropped.

Hand-written, NOT `--autogenerate`: autogenerate on this shared DB repeatedly sweeps in
unrelated drift (it has previously tried to DROP `ad_automation_rules`/`_actions` and the
`idx_listing_tenant_store` index, and to churn FKs). This file contains only the intended
change.

Revision ID: c5a81f4d3e70
Revises: b7e3f9c2a1d4
Create Date: 2026-08-14
"""
import sqlalchemy as sa
from alembic import op

revision = "c5a81f4d3e70"
down_revision = "b7e3f9c2a1d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cm_bid_runtime", sa.Column("last_holding_cpm", sa.Integer(), nullable=True))
    op.add_column("cm_bid_runtime", sa.Column("drift_paused_until", sa.DateTime(), nullable=True))
    op.add_column("cm_bid_runtime", sa.Column("effective_target", sa.Integer(), nullable=True))
    op.add_column("cm_bid_runtime", sa.Column("effective_at_max_bid", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cm_bid_runtime", "effective_at_max_bid")
    op.drop_column("cm_bid_runtime", "effective_target")
    op.drop_column("cm_bid_runtime", "drift_paused_until")
    op.drop_column("cm_bid_runtime", "last_holding_cpm")
