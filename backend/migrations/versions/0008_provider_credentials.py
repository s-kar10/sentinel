"""Project-scoped provider keys and non-secret lifecycle/admission evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0008_provider_credentials"
down_revision = "0007_encrypted_credentials"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.UniqueConstraint("project_id", "provider"),
        sa.CheckConstraint(
            "provider = 'openai'", name="ck_provider_credential_provider"
        ),
        sa.CheckConstraint("version >= 1", name="ck_provider_credential_version"),
    )
    op.create_index(
        "ix_provider_credentials_project_id", "provider_credentials", ["project_id"]
    )
    op.create_table(
        "credential_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=True),
        sa.Column("credential_version", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("event", sa.String(20), nullable=False),
        sa.Column("actor_kind", sa.String(20), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN ('created','replaced','revoked','snapshotted','dispatched')",
            name="ck_credential_audit_event",
        ),
    )
    op.create_index(
        "ix_credential_audit_project_id", "credential_audit", ["project_id"]
    )


def downgrade():
    conn = op.get_bind()
    if any(
        conn.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in ("provider_credentials", "credential_audit")
    ):
        raise RuntimeError(
            "Cannot downgrade provider credentials or audit history; restore a reviewed backup instead."
        )
    op.drop_table("credential_audit")
    op.drop_table("provider_credentials")
