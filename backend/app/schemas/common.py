"""Shared normalization helpers for public API schemas."""

from datetime import datetime, timezone


def ensure_utc(value: datetime | None) -> datetime | None:
    """Treat database-naive timestamps as UTC and normalize aware values to UTC.

    PostgreSQL preserves timezone information, while SQLite (used in tests and
    lightweight local development) reloads timestamps without it. Keeping the
    normalization at the API boundary gives clients one stable ISO-8601 contract.
    """

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
