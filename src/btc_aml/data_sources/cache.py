"""Local SQLite cache for API responses.

Each entry lives in a namespace (``tx``, ``address``, ``block``, ``price``...) and is
stored as JSON with the time it was fetched. Immutable data (confirmed transactions,
blocks, historical prices) is read without an age limit; mutable data (address
histories) is read with ``max_age_seconds`` so it gets refreshed periodically.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    namespace  TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (namespace, key)
)
"""


class Cache:
    """Key-value cache backed by a single SQLite file."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(_SCHEMA)
        self._clock = clock

    def get(self, namespace: str, key: str, max_age_seconds: float | None = None) -> Any | None:
        """Return the cached value, or None if absent or older than ``max_age_seconds``."""
        row = self._conn.execute(
            "SELECT value, fetched_at FROM entries WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        value, fetched_at = row
        if max_age_seconds is not None and self._clock() - fetched_at > max_age_seconds:
            return None
        return json.loads(value)

    def put(self, namespace: str, key: str, value: Any) -> None:
        """Store (or replace) a JSON-serialisable value."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO entries (namespace, key, value, fetched_at) "
                "VALUES (?, ?, ?, ?)",
                (namespace, key, json.dumps(value), self._clock()),
            )

    def stats(self) -> dict[str, int]:
        """Number of cached entries per namespace."""
        rows = self._conn.execute(
            "SELECT namespace, COUNT(*) FROM entries GROUP BY namespace ORDER BY namespace"
        )
        return dict(rows.fetchall())

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
