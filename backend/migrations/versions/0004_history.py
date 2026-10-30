"""Immutable baseline references and frozen version/comparison identities."""

import sqlalchemy as sa
from alembic import op

revision = "0004_history"
down_revision = "0003_durable_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evaluation_runs", sa.Column("version_tags", sa.JSON(), nullable=True)
    )
    op.add_column(
        "evaluation_runs", sa.Column("comparison_key", sa.String(64), nullable=True)
    )
    op.create_table(
        "baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("target_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("target_id", "name", name="uq_baselines_target_name"),
    )


def downgrade():
    op.drop_table("baselines")
    op.drop_column("evaluation_runs", "comparison_key")
    op.drop_column("evaluation_runs", "version_tags")
