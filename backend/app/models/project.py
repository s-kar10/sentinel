"""Organization ownership and additive project bindings for existing resources."""

from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cache_namespace: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, default=lambda: str(uuid4())
    )
    organization: Mapped[Organization] = relationship(lazy="joined")


class TargetProject(Base):
    __tablename__ = "target_projects"
    target_id: Mapped[int] = mapped_column(
        ForeignKey("target_applications.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    project: Mapped[Project] = relationship(lazy="joined")


class TokenProject(Base):
    __tablename__ = "token_projects"
    token_id: Mapped[int] = mapped_column(
        ForeignKey("access_tokens.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, index=True
    )
    project: Mapped[Project] = relationship(lazy="joined")
