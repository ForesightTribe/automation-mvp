"""ad automation rules and actions

Phase 1 of Ad Automation: `ad_automation_rules` (user-defined thresholds on ad
metrics) and `ad_automation_actions` (the recommendation queue produced by
evaluating those rules — pending/approved/rejected/completed). No execution
path against Blinkit yet; see app/services/ad_automation_service.py.

Revision ID: 9cba1aca0fa7
Revises: e2a7c9d5b1f4
Create Date: 2026-07-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "9cba1aca0fa7"
down_revision: Union[str, Sequence[str], None] = "e2a7c9d5b1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ad_automation_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="all"),
        sa.Column("scope_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("metric", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("operator", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("action_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("action_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_aar_tenant", "ad_automation_rules", ["tenant_id"])

    op.create_table(
        "ad_automation_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("campaign_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("metric", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("operator", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("action_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("action_value", sa.Float(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending"),
        sa.Column("reasoning", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["ad_automation_rules.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_aaa_tenant_status", "ad_automation_actions", ["tenant_id", "status"])
    op.create_index("idx_aaa_rule_campaign", "ad_automation_actions", ["rule_id", "campaign_id"])


def downgrade() -> None:
    op.drop_index("idx_aaa_rule_campaign", table_name="ad_automation_actions")
    op.drop_index("idx_aaa_tenant_status", table_name="ad_automation_actions")
    op.drop_table("ad_automation_actions")

    op.drop_index("idx_aar_tenant", table_name="ad_automation_rules")
    op.drop_table("ad_automation_rules")
