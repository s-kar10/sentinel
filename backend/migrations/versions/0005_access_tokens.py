"""Revocable operator token hashes and credential lifecycle evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0005_access_tokens"
down_revision = "0004_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "access_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('reader', 'runner', 'admin')", name="ck_access_token_role"
        ),
    )
    op.create_table(
        "access_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN ('issued', 'revoked')", name="ck_access_audit_event"
        ),
    )


def downgrade():
    # Downgrading removes authentication credentials/audit; data from prior phases
    # remains. Never downgrade an exposed service to an unauthenticated release.
    op.drop_table("access_audit")
    op.drop_table("access_tokens")
