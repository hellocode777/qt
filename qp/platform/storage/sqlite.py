"""SQLite storage backend (lightweight alternative)."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteStorage:
    """SQLite database backend for lightweight storage needs."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open the SQLite connection."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_connected(self) -> bool:
        """Check if the database connection is active."""
        return self._conn is not None
