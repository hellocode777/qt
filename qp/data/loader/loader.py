"""DatasetLoader — loads Data Products by name + version.

This is the ONLY public interface of the Data Layer (ADR-015).
Consumers never know which data source provided the raw data (ADR-017).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from qp.shared.paths import DATASET_DIR


class DatasetLoader:
    """Loads trusted Data Products from storage.

    For Walking Skeleton: auto-discovers parquet files by naming convention.
    Will be replaced by full Registry-based lookup in Phase 2.
    """

    def __init__(self, base_dir: str | Path = DATASET_DIR) -> None:
        self._base_dir = Path(base_dir)

    def load(self, name: str, version: str | None = None) -> pl.DataFrame:
        """Load a dataset by name and optional version.

        Args:
            name: Dataset name (e.g. 'daily_price').
            version: Version string. If None, loads the latest by file mtime.

        Returns:
            Polars DataFrame containing the dataset.
        """
        pattern = f"{name}_*.parquet"
        candidates = sorted(
            self._base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
        )

        if version:
            candidates = [p for p in candidates if version in p.name]

        if not candidates:
            raise FileNotFoundError(f"Dataset not found: {name} in {self._base_dir}")

        path = candidates[0]
        return pl.read_parquet(path)


def load_dataset(name: str, version: str | None = None) -> pl.DataFrame:
    """Convenience function to load a dataset.

    Usage:
        ds = load_dataset("daily_price", version="2026-07-20")
    """
    loader = DatasetLoader(base_dir=DATASET_DIR)
    return loader.load(name, version)
