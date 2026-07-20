"""DuckDB storage backend."""

from __future__ import annotations

from pathlib import Path

import duckdb


class DuckDBStorage:
    """DuckDB analytical database backend (TDR-002)."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> None:
        """Open the DuckDB connection."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._path))

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_connected(self) -> bool:
        """Check if the database connection is active."""
        return self._conn is not None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Get the raw DuckDB connection."""
        if self._conn is None:
            raise RuntimeError("DuckDB is not connected. Call connect() first.")
        return self._conn
