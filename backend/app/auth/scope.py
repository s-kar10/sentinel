"""Explicit project predicates for HTTP services; worker sessions are trusted."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import TargetProject


def owned_targets(db: Session):
    statement = select(TargetProject.target_id)
    if "project_id" in db.info:
        statement = statement.where(TargetProject.project_id == db.info["project_id"])
    return statement
