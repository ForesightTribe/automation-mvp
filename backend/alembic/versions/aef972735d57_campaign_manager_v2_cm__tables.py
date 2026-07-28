"""campaign manager v2 cm_ tables

Creates the five v2 tables (cm_budget_schedules, cm_budget_rules, cm_bid_rules,
cm_bid_runtime, cm_run_log). Additive only — the v1 tables are untouched (D14).

HAND-TRIMMED: `alembic revision --autogenerate` also swept in drift against existing
tables — it wanted to DROP `ad_automation_rules`/`ad_automation_actions` (which we keep,
deprecated — §4.1), DROP the `idx_listing_tenant_store` index on `search_listings`, and
churn FKs on `jobs`/`budget_schedule_rules`/`campaign_data_cache`. ALL of that was
removed; this migration only CREATEs the cm_* tables.

Revision ID: aef972735d57
Revises: e3b1f7a9c2d5
Create Date: 2026-07-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'aef972735d57'
down_revision: Union[str, Sequence[str], None] = 'e3b1f7a9c2d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add v2's own lanes to the `lane` enum, then create the cm_* tables."""
    # v2 owns its lanes (D18) — additive enum values. IF NOT EXISTS = idempotent.
    # PG 12+ allows ADD VALUE in a transaction as long as the value isn't USED in the
    # same transaction (the cm_* tables below have no lane column, so we're safe).
    op.execute("ALTER TYPE lane ADD VALUE IF NOT EXISTS 'cm_bid'")
    op.execute("ALTER TYPE lane ADD VALUE IF NOT EXISTS 'cm_ops'")

    op.create_table(
        'cm_bid_rules',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('keyword', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('match_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('target_position', sa.Integer(), nullable=False),
        sa.Column('min_bid', sa.Integer(), nullable=False),
        sa.Column('max_bid', sa.Integer(), nullable=False),
        sa.Column('start_time', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('stop_time', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('start_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('stop_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.Column('location_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('brand_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_cm_bid_tenant', 'cm_bid_rules', ['tenant_id'], unique=False)

    op.create_table(
        'cm_budget_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('default_budget', sa.Float(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'platform', 'campaign_id',
                            name='uq_cm_bs_tenant_platform_campaign'),
    )
    op.create_index('idx_cm_bs_tenant', 'cm_budget_schedules', ['tenant_id'], unique=False)

    op.create_table(
        'cm_budget_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=False),
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('days', sa.JSON(), nullable=True),
        sa.Column('time_slots', sa.JSON(), nullable=True),
        sa.Column('start_time', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('end_time', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('start_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('end_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('date', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('budget', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['schedule_id'], ['cm_budget_schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cm_budget_rules_schedule_id'), 'cm_budget_rules',
                    ['schedule_id'], unique=False)

    op.create_table(
        'cm_bid_runtime',
        sa.Column('rule_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_cpm', sa.Integer(), nullable=True),
        sa.Column('last_position', sa.Float(), nullable=True),
        sa.Column('last_bid_updated_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['cm_bid_rules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('rule_id'),
    )

    op.create_table(
        'cm_run_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('campaign_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('keyword', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('action', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('old_value', sa.Float(), nullable=True),
        sa.Column('new_value', sa.Float(), nullable=True),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_cm_runlog_tenant', 'cm_run_log', ['tenant_id', 'timestamp'],
                    unique=False)


def downgrade() -> None:
    """Drop the cm_* tables (children before parents). Only touches cm_* — nothing else.
    The `cm_bid`/`cm_ops` enum values are left in place (Postgres can't drop enum values
    cleanly); they're inert when unused."""
    op.drop_index('idx_cm_runlog_tenant', table_name='cm_run_log')
    op.drop_table('cm_run_log')
    op.drop_table('cm_bid_runtime')
    op.drop_index(op.f('ix_cm_budget_rules_schedule_id'), table_name='cm_budget_rules')
    op.drop_table('cm_budget_rules')
    op.drop_index('idx_cm_bs_tenant', table_name='cm_budget_schedules')
    op.drop_table('cm_budget_schedules')
    op.drop_index('idx_cm_bid_tenant', table_name='cm_bid_rules')
    op.drop_table('cm_bid_rules')
