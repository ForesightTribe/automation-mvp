"""budget scheduler and bid optimizer tables

Revision ID: c2d4e6f8a1b3
Revises: b7c3d8e2f1a9, f5b3d8e1c4a2
Create Date: 2026-07-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c2d4e6f8a1b3'
down_revision: Union[str, Sequence[str], None] = 'a3e8d1f6c2b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Budget Schedules ──────────────────────────────────────────────────────
    op.create_table(
        'budget_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('default_budget', sa.Float(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'campaign_id', name='uq_budget_schedule_tenant_campaign'),
    )
    op.create_index('idx_bs_tenant', 'budget_schedules', ['tenant_id'], unique=False)

    # ── Budget Schedule Rules ─────────────────────────────────────────────────
    op.create_table(
        'budget_schedule_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(), nullable=False, server_default='recurring'),
        sa.Column('days', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('time_slots', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('start_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
        sa.Column('start_date', sa.String(), nullable=True),
        sa.Column('end_date', sa.String(), nullable=True),
        sa.Column('date', sa.String(), nullable=True),
        sa.Column('budget', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['schedule_id'], ['budget_schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_bsr_schedule', 'budget_schedule_rules', ['schedule_id'], unique=False)

    # ── Budget Scheduler Log ──────────────────────────────────────────────────
    op.create_table(
        'budget_scheduler_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('campaign_name', sa.String(), nullable=False),
        sa.Column('budget_applied', sa.Float(), nullable=False),
        sa.Column('rule', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_bsl_tenant', 'budget_scheduler_log', ['tenant_id', 'timestamp'], unique=False)

    # ── Bid Optimizer Rules ───────────────────────────────────────────────────
    op.create_table(
        'bid_optimizer_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('campaign_name', sa.String(), nullable=False),
        sa.Column('keyword', sa.String(), nullable=False),
        sa.Column('match_type', sa.String(), nullable=False, server_default='EXACT'),
        sa.Column('target_position', sa.Integer(), nullable=False),
        sa.Column('min_bid', sa.Integer(), nullable=False),
        sa.Column('max_bid', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.String(), nullable=True),
        sa.Column('stop_time', sa.String(), nullable=True),
        sa.Column('start_date', sa.String(), nullable=True),
        sa.Column('stop_date', sa.String(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.Column('location_name', sa.String(), nullable=True),
        sa.Column('brand_name', sa.String(), nullable=True),
        sa.Column('last_cpm', sa.Integer(), nullable=True),
        sa.Column('last_position', sa.Float(), nullable=True),
        sa.Column('last_bid_updated_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_bor_tenant', 'bid_optimizer_rules', ['tenant_id'], unique=False)

    # ── Bid Optimizer Log ─────────────────────────────────────────────────────
    op.create_table(
        'bid_optimizer_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('campaign_name', sa.String(), nullable=False),
        sa.Column('keyword', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('old_cpm', sa.Integer(), nullable=True),
        sa.Column('new_cpm', sa.Integer(), nullable=True),
        sa.Column('position', sa.Float(), nullable=True),
        sa.Column('target_position', sa.Integer(), nullable=True),
        sa.Column('impressions', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_bol_tenant', 'bid_optimizer_log', ['tenant_id', 'timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_bol_tenant', table_name='bid_optimizer_log')
    op.drop_table('bid_optimizer_log')
    op.drop_index('idx_bor_tenant', table_name='bid_optimizer_rules')
    op.drop_table('bid_optimizer_rules')
    op.drop_index('idx_bsl_tenant', table_name='budget_scheduler_log')
    op.drop_table('budget_scheduler_log')
    op.drop_index('idx_bsr_schedule', table_name='budget_schedule_rules')
    op.drop_table('budget_schedule_rules')
    op.drop_index('idx_bs_tenant', table_name='budget_schedules')
    op.drop_table('budget_schedules')
