"""cm_budget_schedules.stop_after_window — campaign activation toggle

Adds the single column that lets a budget automation also STOP its campaign when a
rule's window ends (and restart it at the next window start). See
docs/campaign-activation.md — activation is folded into the budget scheduler rather
than built beside it, because Blinkit's restart call carries the budget, so starting a
campaign and setting its budget is one API call.

Additive and safe:

- one column, `NOT NULL DEFAULT false`, so every existing row keeps today's exact
  behaviour and no data is rewritten;
- `false` means "we never STOP this campaign". It does not mean "we never write to it":
  starting is unconditional (AD7), so an existing schedule will restart a campaign it
  finds stopped at a window start. That is the intended behaviour change of this feature
  and it applies to existing schedules on deploy — see docs/campaign-activation.md §5.2;
- nothing else is altered or dropped.

Hand-written, NOT `--autogenerate`: autogenerate on this shared DB repeatedly sweeps in
unrelated drift (it has previously tried to DROP `ad_automation_rules`/`_actions` and
the `idx_listing_tenant_store` index, and to churn FKs). This file contains only the
intended change.

Revision ID: b7e3f9c2a1d4
Revises: f3c8d1a5e7b2
Create Date: 2026-08-07
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e3f9c2a1d4"
down_revision = "f3c8d1a5e7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cm_budget_schedules",
        sa.Column("stop_after_window", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cm_budget_schedules", "stop_after_window")
