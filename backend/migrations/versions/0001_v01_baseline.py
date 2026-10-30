"""Freeze the existing V0.1 schema, without changing its storage contracts.

This snapshot is also used to validate legacy adoption. Never import live ORM
models here: future model changes must not change an already released revision.
"""

import sqlalchemy as sa
from alembic import op
from alembic.operations import ops

revision = "0001_v01_baseline"
down_revision = None
branch_labels = None
depends_on = None


def baseline_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    sa.Table(
        "target_applications",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("endpoint_url", sa.String(2048), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("request_template", sa.JSON(), nullable=False),
        sa.Column("prompt_field", sa.String(500), nullable=False),
        sa.Column("response_field", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    sa.Table(
        "protected_values",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_application_id",
            sa.Integer(),
            sa.ForeignKey("target_applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    sa.Table(
        "evaluation_runs",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_application_id",
            sa.Integer(),
            sa.ForeignKey("target_applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # SQLAlchemy's non-native Enum stores member NAMES, e.g. COMPLETED,
        # in VARCHAR(20), without a DB enum or CHECK constraint in V0.1.
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_tests", sa.Integer(), nullable=False),
        sa.Column("passed_tests", sa.Integer(), nullable=False),
        sa.Column("failed_tests", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    sa.Table(
        "test_results",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "evaluation_run_id",
            sa.Integer(),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("test_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(100), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    return metadata


def upgrade() -> None:
    # Generate explicit Alembic create operations from the frozen snapshot.
    for table in baseline_metadata().sorted_tables:
        op.invoke(ops.CreateTableOp.from_table(table))
        for index in sorted(table.indexes, key=lambda item: item.name):
            op.invoke(ops.CreateIndexOp.from_index(index))


def downgrade() -> None:
    # Destructive: intended for disposable databases only. Restore a backup to
    # recover production data; recreating tables cannot recover deleted rows.
    for table in reversed(baseline_metadata().sorted_tables):
        op.drop_table(table.name)
