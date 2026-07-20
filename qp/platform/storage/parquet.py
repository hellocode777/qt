"""Parquet columnar storage helper (TDR-003)."""

from __future__ import annotations

from pathlib import Path

import polars as pl


class ParquetStorage:
    """Helper for reading and writing Parquet files."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def read(self, name: str) -> pl.DataFrame:
        """Read a Parquet file into a Polars DataFrame.

        Args:
            name: File name (without extension) under the base directory.

        Returns:
            Polars DataFrame.
        """
        path = self._base_dir / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found: {path}")
        return pl.read_parquet(path)

    def write(self, df: pl.DataFrame, name: str) -> None:
        """Write a Polars DataFrame to a Parquet file.

        Args:
            df: Polars DataFrame to write.
            name: File name (without extension) under the base directory.
        """
        path = self._base_dir / f"{name}.parquet"
        df.write_parquet(path)

    def exists(self, name: str) -> bool:
        """Check if a Parquet file exists.

        Args:
            name: File name (without extension).

        Returns:
            True if the file exists.
        """
        return (self._base_dir / f"{name}.parquet").exists()
