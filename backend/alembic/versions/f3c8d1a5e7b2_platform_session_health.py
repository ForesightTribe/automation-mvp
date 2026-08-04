"""platform_credentials table + platform_sessions health tracking

Two changes, both for platform_auth:

1. **`platform_credentials`** — what a tenant needs to BEGIN a login (address,
   optional encrypted password). Separate from `platform_sessions` because
   credentials are long-lived and human-entered while sessions are short-lived
   and machine-rotated; mixing them means every token refresh rewrites the row
   holding the password. Blinkit's dashboards are passwordless, but Zepto is not,
   so the column exists from the start rather than being retrofitted.

2. **Health columns on `platform_sessions`** — the row's existence used to be the
   only signal, so `cli auth status` reported a session that died days earlier as
   present. That is how the seller scrape failed silently from 2026-07-21.

Additive only: no existing column is altered or dropped, every new column is
nullable or has a server default, and no data is rewritten. Code running against
the pre-migration schema simply never sees the new fields.

Revision ID: f3c8d1a5e7b2
Revises: a4d9f2e6b1c8
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8d1a5e7b2"
down_revision = "a4d9f2e6b1c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        # Plaintext: PII, not a secret, and it must stay readable to render
        # status and to decide whether a tenant can auto-login at all.
        sa.Column("login_email", sa.String(), nullable=False),
        # Fernet, same key as platform_sessions.encrypted_session.
        sa.Column("encrypted_password", sa.LargeBinary(), nullable=True),
        # JSON — anything a future marketplace needs, without a schema change.
        sa.Column("extra", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "platform", name="uq_platform_credentials_tenant_platform"
        ),
    )

    # Liveness. 'unknown' is the honest default for rows predating any probe.
    op.add_column(
        "platform_sessions",
        sa.Column("status", sa.String(), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "platform_sessions", sa.Column("last_login_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "platform_sessions", sa.Column("last_validated_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "platform_sessions",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "platform_sessions", sa.Column("last_error", sa.String(), nullable=True)
    )


def downgrade() -> None:
    for column in (
        "last_error",
        "consecutive_failures",
        "last_validated_at",
        "last_login_at",
        "status",
    ):
        op.drop_column("platform_sessions", column)
    op.drop_table("platform_credentials")
