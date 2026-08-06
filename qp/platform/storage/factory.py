"""StorageFactory — creates and manages storage backend instances."""

from __future__ import annotations

from typing import Protocol

from qp.platform.storage.duckdb import DuckDBStorage
from qp.platform.storage.parquet import ParquetStorage
from qp.platform.storage.sqlite import SQLiteStorage


class StorageBackend(Protocol):
    """Protocol for storage backends."""

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def is_connected(self) -> bool: ...


class StorageFactory:
    """Creates storage backends based on configuration.

    Platform provides the factory; each business layer creates
    its own Repositories using the backend from this factory (ADR-004).
    """

    def __init__(self, backend: str, **kwargs: str) -> None:
        self._backend_name = backend
        self._kwargs = kwargs
        self._instance: StorageBackend | None = None

    def get_storage(self) -> StorageBackend:
        """Get or create the configured storage backend.

        Returns:
            A connected storage backend instance.
        """
        if self._instance is not None:
            return self._instance

        if self._backend_name == "duckdb":
            self._instance = DuckDBStorage(
                self._kwargs.get("duckdb_path", "data/qp.duckdb")
            )
        elif self._backend_name == "sqlite":
            self._instance = SQLiteStorage(
                self._kwargs.get("sqlite_path", "data/qp.sqlite")
            )
        else:
            raise ValueError(f"Unknown storage backend: {self._backend_name}")

        self._instance.connect()
        return self._instance

    def get_parquet(self) -> ParquetStorage:
        """Get a Parquet storage helper."""
        return ParquetStorage(self._kwargs.get("parquet_dir", "data/parquet"))
