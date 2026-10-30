"""Transactional queue with bounded dispatch and expiring case leases."""

import sqlalchemy as sa
from alembic import op

revision = "0003_durable_jobs"
down_revision = "0002_engine_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "test_results", sa.Column("attempt_count", sa.Integer(), nullable=True)
    )
    op.create_table(
        "queue_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("next_dispatch", sa.Float(), nullable=False),
    )
    op.execute("INSERT INTO queue_control (id, next_dispatch) VALUES (1, 0)")
    op.create_table(
        "evaluation_jobs",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("target_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Float(), nullable=False),
        sa.Column("deadline", sa.Float(), nullable=False),
        sa.Column("lease_until", sa.Float(), nullable=False),
        sa.Column("token", sa.String(64)),
        sa.Column("state", sa.String(20), nullable=False),
    )


def downgrade():
    # Stop API/workers first. The old binary cannot decode CANCELLED.
    op.execute(
        "UPDATE evaluation_runs SET status = 'FAILED' WHERE status IN ('CANCELLED', 'PENDING', 'RUNNING') AND id IN (SELECT run_id FROM evaluation_jobs)"
    )
    op.drop_table("evaluation_jobs")
    op.drop_table("queue_control")
    op.drop_column("test_results", "attempt_count")
