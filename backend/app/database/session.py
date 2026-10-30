"""SQLAlchemy engine and request-scoped session management."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str | URL, *, echo: bool = False) -> Engine:
    """Build an engine that works with PostgreSQL and SQLite test databases."""

    parsed_url = make_url(database_url)
    is_sqlite = parsed_url.get_backend_name() == "sqlite"
    connect_args: dict[str, object] = {}
    pool_options: dict[str, object] = {}
    if is_sqlite:
        connect_args["check_same_thread"] = False
    elif parsed_url.get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = 3
        pool_options["pool_timeout"] = 3

    created_engine = create_engine(
        database_url,
        echo=echo,
        # Bound values can contain target API keys and protected values. Keep them
        # out of SQL echo output and exception representations in every environment.
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args=connect_args,
        **pool_options,
    )

    if is_sqlite:
        # SQLite does not enforce foreign keys unless explicitly enabled.
        @event.listens_for(created_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return created_engine


settings = get_settings()
engine = build_engine(settings.resolved_database_url, echo=settings.sql_echo)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always release it after the request."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
