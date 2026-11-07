"""Adopt existing resources into one legacy project without rebuilding parent tables."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0006_projects"
down_revision = "0005_access_tokens"
branch_labels = None
depends_on = None


def upgrade():
    organizations = op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    projects = op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("cache_namespace", sa.String(36), nullable=False, unique=True),
        sa.UniqueConstraint("organization_id", "name"),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    for table, resource, parent in (
        ("target_projects", "target_id", "target_applications"),
        ("token_projects", "token_id", "access_tokens"),
    ):
        op.create_table(
            table,
            sa.Column(
                resource,
                sa.Integer(),
                sa.ForeignKey(f"{parent}.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False
            ),
        )
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    conn = op.get_bind()
    # Let sequences allocate IDs, so the next PostgreSQL insert does not collide.
    org = conn.execute(
        organizations.insert().values(name="Legacy installation")
    ).inserted_primary_key[0]
    namespace = str(uuid4())
    project = conn.execute(
        projects.insert().values(
            organization_id=org, name="Legacy project", cache_namespace=namespace
        )
    ).inserted_primary_key[0]
    for table, column, parent in (
        ("target_projects", "target_id", "target_applications"),
        ("token_projects", "token_id", "access_tokens"),
    ):
        conn.execute(
            sa.text(
                f"INSERT INTO {table} ({column}, project_id) SELECT id, :project FROM {parent}"
            ),
            {"project": project},
        )
    # Preserve accepted work and its private frozen configuration while adding scope.
    jobs = sa.table(
        "evaluation_jobs",
        sa.column("run_id", sa.Integer),
        sa.column("target_id", sa.Integer),
        sa.column("payload", sa.JSON),
    )
    for row in conn.execute(sa.select(jobs)).mappings():
        if row["payload"] is not None:
            payload = dict(row["payload"])
            payload["target"] = {
                **payload["target"],
                "id": row["target_id"],
                "project_id": project,
            }
            if "judge_runtime" in payload:
                payload["judge_runtime"] = {
                    **payload["judge_runtime"],
                    "project_namespace": namespace,
                }
            conn.execute(
                jobs.update()
                .where(jobs.c.run_id == row["run_id"])
                .values(payload=payload)
            )


def downgrade():
    conn = op.get_bind()
    # An older binary would expose all projects to every token. Refuse that collapse.
    if (
        conn.scalar(sa.text("SELECT count(*) FROM projects")) != 1
        or conn.scalar(sa.text("SELECT count(*) FROM organizations")) != 1
    ):
        raise RuntimeError(
            "Cannot downgrade multiple projects; restore a reviewed backup instead."
        )
    jobs = sa.table(
        "evaluation_jobs",
        sa.column("run_id", sa.Integer),
        sa.column("payload", sa.JSON),
    )
    for row in conn.execute(sa.select(jobs)).mappings():
        if row["payload"] is not None:
            payload = dict(row["payload"])
            payload["target"] = dict(payload["target"])
            payload["target"].pop("project_id", None)
            if "judge_runtime" in payload:
                payload["judge_runtime"] = dict(payload["judge_runtime"])
                payload["judge_runtime"].pop("project_namespace", None)
            conn.execute(
                jobs.update()
                .where(jobs.c.run_id == row["run_id"])
                .values(payload=payload)
            )
    op.drop_table("token_projects")
    op.drop_table("target_projects")
    op.drop_table("projects")
    op.drop_table("organizations")
