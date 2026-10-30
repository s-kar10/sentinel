"""Add nullable engine provenance/outcomes without inventing historical metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0002_engine_v2"
down_revision = "0001_v01_baseline"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("engine_version", sa.String(30), nullable=True),
        sa.Column("scoring_version", sa.String(30), nullable=True),
        sa.Column("pack_digest", sa.String(64), nullable=True),
        sa.Column("pack_snapshot", sa.JSON(), nullable=True),
    ):
        op.add_column("evaluation_runs", column)
    for column in (
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("assertion_results", sa.JSON(), nullable=True),
        sa.Column("observation_snapshot", sa.JSON(), nullable=True),
    ):
        op.add_column("test_results", column)


def downgrade():
    # Discards V2 metadata only; original result text/counts remain. Back up first.
    for column in (
        "observation_snapshot",
        "assertion_results",
        "provenance",
        "response_status",
        "outcome",
    ):
        op.drop_column("test_results", column)
    for column in ("pack_snapshot", "pack_digest", "scoring_version", "engine_version"):
        op.drop_column("evaluation_runs", column)
