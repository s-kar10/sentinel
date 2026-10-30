"""Disposable local derived cache, separate from Sentinel's migrated source of truth."""

import json
import os
import sqlite3
import time
from contextlib import closing

TTL_SECONDS = 86_400
MAX_ENTRIES = 1000


def access(path: str, key: str, value: dict | None = None) -> dict | None:
    if not path:
        return None
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path, timeout=0.2)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL)"
            )
            db.execute(
                "DELETE FROM cache WHERE created < ?", (time.time() - TTL_SECONDS,)
            )
            if value is not None:
                db.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                    (key, json.dumps(value), time.time()),
                )
                db.execute(
                    "DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY created DESC, key LIMIT ?)",
                    (MAX_ENTRIES,),
                )
                return None
            row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
    except (OSError, sqlite3.Error, ValueError):
        # Cache availability must never prevent evaluation.
        return None
