"""cm_bid_rules.max_bid becomes optional (NULL = no ceiling)

A bid rule no longer has to name a ceiling. The client's case: sometimes the target
position is wanted whatever it costs, and being forced to guess a number up front either
caps the rule too low or invites a made-up value.

`NULL` does not mean "unbounded" — `bid.resolve_ceiling` substitutes
`config.BID_MAX_ABSOLUTE` (default ₹10,000, env `CM_BID_MAX_ABSOLUTE`) so an unbounded
rule still has a runaway guard, and a rule that DOES set `max_bid` is capped at the lower
of the two (which also catches a typo'd ceiling). Everything downstream — the decision
logic, the clamps, the unreachable-target relaxation — still receives a plain int, so no
behaviour changes for a rule that sets one.

Safe:

- **widening only** — `DROP NOT NULL` never rejects existing data and rewrites nothing;
- every existing row keeps its value, so armed rules behave exactly as before;
- `cm_bid_rules` has 0 rows at the time of writing anyway;
- the reverse is the risky direction and is handled: `downgrade()` backfills any NULL to
  `BID_MAX_ABSOLUTE` before restoring `NOT NULL`, so it cannot fail on live data.

Hand-written, NOT `--autogenerate`: autogenerate on this shared DB repeatedly sweeps in
unrelated drift (it has previously tried to DROP `ad_automation_rules`/`_actions` and the
`idx_listing_tenant_store` index, and to churn FKs). This file contains only the intended
change.

Revision ID: d1f7b3c9e485
Revises: c5a81f4d3e70
Create Date: 2026-08-17
"""
import sqlalchemy as sa
from alembic import op

revision = "d1f7b3c9e485"
down_revision = "c5a81f4d3e70"
branch_labels = None
depends_on = None

# Must match config.BID_MAX_ABSOLUTE's default. Only used by downgrade(), to give
# pre-existing NULL rows a concrete ceiling before NOT NULL is restored.
_FALLBACK_CEILING = 10000


def upgrade() -> None:
    op.alter_column("cm_bid_rules", "max_bid", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute(
        f"UPDATE cm_bid_rules SET max_bid = {_FALLBACK_CEILING} WHERE max_bid IS NULL"
    )
    op.alter_column("cm_bid_rules", "max_bid", existing_type=sa.Integer(), nullable=False)
