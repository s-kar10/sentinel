"""Alembic environment using the same database settings as the API."""

from alembic import context

import app.models  # noqa: F401
from app.core.config import get_settings
from app.database.base import Base
from app.database.session import build_engine


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=get_settings().resolved_database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        run(supplied_connection)
    else:
        engine = build_engine(get_settings().resolved_database_url)
        try:
            with engine.connect() as connection:
                run(connection)
        finally:
            engine.dispose()
