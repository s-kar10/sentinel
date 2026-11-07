"""Encrypt target credentials and frozen job configuration in place."""

import json

import sqlalchemy as sa
from alembic import op

from app.secrets.codec import configured_keyring

revision = "0007_encrypted_credentials"
down_revision = "0006_projects"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Deliberately raw historical types: the current ORM already encrypts writes.
    targets = sa.table(
        "target_applications",
        sa.column("id", sa.Integer),
        sa.column("api_key", sa.Text),
    )
    jobs = sa.table(
        "evaluation_jobs",
        sa.column("run_id", sa.Integer),
        sa.column("payload", sa.JSON),
    )
    ring = None
    for table, pk, column, purpose in (
        (targets, "id", "api_key", "target-api-key"),
        (jobs, "run_id", "payload", "job-payload"),
    ):
        for row in conn.execute(sa.select(table)).mappings():
            value = row[column]
            if value is None:
                continue
            ring = ring or configured_keyring()
            encrypted = ring.seal(
                json.dumps(value) if column == "payload" else value, purpose
            )
            conn.execute(
                table.update()
                .where(table.c[pk] == row[pk])
                .values(
                    {
                        column: {"encrypted": encrypted}
                        if column == "payload"
                        else encrypted
                    }
                )
            )


def downgrade():
    conn = op.get_bind()
    jobs = sa.table("evaluation_jobs", sa.column("payload", sa.JSON))
    if conn.scalar(
        sa.text("SELECT count(*) FROM target_applications WHERE api_key IS NOT NULL")
    ) or any(value is not None for value in conn.scalars(sa.select(jobs.c.payload))):
        raise RuntimeError(
            "Cannot downgrade encrypted credentials or pending payloads; restore a reviewed backup instead."
        )
