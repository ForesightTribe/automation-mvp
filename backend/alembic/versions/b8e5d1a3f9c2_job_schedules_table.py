"""job_schedules table + jobs.schedule_id FK (scheduler / Phase 2) — see docs/jobs.md

Adds `job_schedules` (recurring job definitions the scheduler reads) and wires the
`jobs.schedule_id` column added in Phase 1 to it as a real FK (ON DELETE SET NULL, so
deleting a schedule keeps its historical jobs). Branches off a7f3c2e9d4b1 (my line);
does not touch the divergent b7c3d8e2f1a9 branch.

Hand-written to stay surgical.

Revision ID: b8e5d1a3f9c2
Revises: a7f3c2e9d4b1
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8e5d1a3f9c2'
down_revision: Union[str, Sequence[str], None] = 'a7f3c2e9d4b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('job_type', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=True),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('cron', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('catchup', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_enqueued_at', sa.DateTime(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_job_schedules_due', 'job_schedules', ['enabled', 'next_run_at'])
    # Wire the Phase-1 jobs.schedule_id column to the new table.
    op.create_foreign_key(
        'fk_jobs_schedule_id', 'jobs', 'job_schedules',
        ['schedule_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_jobs_schedule_id', 'jobs', type_='foreignkey')
    op.drop_index('idx_job_schedules_due', table_name='job_schedules')
    op.drop_table('job_schedules')
