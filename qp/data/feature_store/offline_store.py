"""Offline Feature Store — Parquet-based batch feature storage.

Implements data_layer.md §1.5:
  "离线特征库 (Offline Feature Store):
    - Storage: Parquet / Feather
    - Access: Fast Column Scan
    - Partition: By Year/Factor Group"

Stores precomputed feature matrices for historical analysis and backtesting.
Features are partitioned by year for efficient time-range queries.

Usage::

    from qp.data.feature_store import OfflineStore

    store = OfflineStore(FEATURES_DIR)
    store.write(df, factor_group="momentum")
    df = store.load("2024-01-01", "2024-12-31", factor_groups=["momentum"])
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from qp.shared.json_io import json_load, json_save
from qp.shared.time import utc_iso

_DEFAULT_STORE_DIR = Path("data/feature_store_data")


class OfflineStore:
    """Parquet-based offline feature storage with year partitioning.

    Directory structure::

        <store_dir>/
        └── <factor_group>/
            ├── _metadata.json
            ├── year=2020/
            │   ├── part_0000.parquet
            │   └── part_0001.parquet
            ├── year=2021/
            │   └── ...
            └── year=2022/
                └── ...
    """

    def __init__(self, store_dir: str | Path = _DEFAULT_STORE_DIR) -> None:
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

    # ── Write ──

    def write(
        self,
        df: pl.DataFrame,
        factor_group: str = "default",
        partition_by: str = "year",
        mode: str = "append",
    ) -> int:
        """Write feature DataFrame to the offline store.

        Args:
            df: DataFrame with [symbol, trade_date, ...feature columns].
            factor_group: Factor category (e.g., 'momentum', 'value', 'volatility').
            partition_by: Partition strategy ('year' or 'none').
            mode: 'append' (add to existing) or 'overwrite' (replace group).

        Returns:
            Number of rows written.
        """
        if df.is_empty():
            return 0

        group_dir = self._store_dir / factor_group
        group_dir.mkdir(parents=True, exist_ok=True)

        write_df = df.clone()

        # Ensure year column for partitioning
        if (
            partition_by == "year"
            and "trade_date" in write_df.columns
            and "year" not in write_df.columns
        ):
            write_df = write_df.with_columns(pl.col("trade_date").dt.year().alias("year"))

        # Write metadata
        self._write_metadata(factor_group, df)

        if mode == "overwrite":
            # Clean existing partitions
            import shutil

            for d in group_dir.glob("*"):
                if d.is_dir():
                    shutil.rmtree(d)

        n_rows = write_df.height

        try:
            write_df.write_parquet(
                group_dir,
                partition_by=[partition_by] if partition_by != "none" else None,
                compression="zstd",
            )
            logger.info(
                "OfflineStore: wrote {} rows to '{}/{}' (mode={})",
                n_rows,
                self._store_dir.name,
                factor_group,
                mode,
            )
        except Exception as e:
            logger.error("OfflineStore write failed: {}", e)
            raise

        return n_rows

    # ── Read ──

    def load(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        symbols: list[str] | None = None,
        factor_groups: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> pl.DataFrame:
        """Load features from the offline store.

        Args:
            start_date: ISO date string filter (inclusive).
            end_date: ISO date string filter (inclusive).
            symbols: Symbol list filter. None = all symbols.
            factor_groups: Factor group filter. None = all groups.
            columns: Columns to read. None = all columns.

        Returns:
            Combined Polars DataFrame of all matching data.
        """
        groups = factor_groups or self.list_groups()
        if not groups:
            logger.warning("OfflineStore: no factor groups found")
            return pl.DataFrame()

        frames: list[pl.DataFrame] = []
        for group in groups:
            group_dir = self._store_dir / group
            if not group_dir.exists():
                continue

            try:
                # Try to scan with hive partitioning
                df = pl.scan_parquet(str(group_dir / "**" / "*.parquet"))
            except Exception:
                df = pl.scan_parquet(str(group_dir / "*.parquet"))

            # Apply filters at scan level when possible
            if start_date:
                df = df.filter(pl.col("trade_date") >= pl.lit(start_date).str.to_date())
            if end_date:
                df = df.filter(pl.col("trade_date") <= pl.lit(end_date).str.to_date())
            if symbols:
                df = df.filter(pl.col("symbol").is_in(symbols))
            if columns:
                available = [c for c in columns if c in df.columns]
                if available:
                    df = df.select(available)
                else:
                    continue

            try:
                collected = df.collect()
                if not collected.is_empty():
                    frames.append(collected)
            except Exception as e:
                logger.debug("OfflineStore: failed to scan '{}': {}", group, e)

        if not frames:
            return pl.DataFrame()

        result = pl.concat(frames, how="diagonal_relaxed")
        logger.info(
            "OfflineStore: loaded {} rows from {} groups",
            result.height,
            len(groups),
        )
        return result

    def load_snapshot(
        self,
        as_of_date: str,
        symbols: list[str] | None = None,
        factor_groups: list[str] | None = None,
    ) -> pl.DataFrame:
        """Load the latest feature values as of a specific date.

        Useful for getting the feature snapshot for a single trading day.

        Args:
            as_of_date: Reference date (ISO format).
            symbols: Optional symbol filter.
            factor_groups: Optional factor group filter.

        Returns:
            DataFrame with the latest feature row for each symbol on or
            before the as_of_date.
        """
        df = self.load(
            end_date=as_of_date,
            symbols=symbols,
            factor_groups=factor_groups,
        )

        if df.is_empty():
            return df

        # Get the latest row per symbol
        return df.sort(["symbol", "trade_date"]).group_by("symbol").agg(pl.all().last())

    # ── Group management ──

    def list_groups(self) -> list[str]:
        """List all factor groups in the store."""
        if not self._store_dir.exists():
            return []
        groups: list[str] = []
        for d in sorted(self._store_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and not d.name.startswith("."):
                groups.append(d.name)
        return groups

    def group_info(self, factor_group: str) -> dict[str, Any]:
        """Get metadata about a factor group.

        Returns:
            Dict with row_count, date_range, symbol_count, columns, last_updated.
        """
        group_dir = self._store_dir / factor_group
        if not group_dir.exists():
            return {}

        meta_path = group_dir / "_metadata.json"
        if meta_path.exists():
            return json_load(meta_path)

        # Fallback: scan data
        try:
            df = pl.scan_parquet(str(group_dir / "**" / "*.parquet")).collect()
            if df.is_empty():
                return {}

            return {
                "factor_group": factor_group,
                "row_count": df.height,
                "symbol_count": df["symbol"].n_unique() if "symbol" in df.columns else 0,
                "columns": [c for c in df.columns if c not in ("year",)],
                "min_date": str(df["trade_date"].min()) if "trade_date" in df.columns else None,
                "max_date": str(df["trade_date"].max()) if "trade_date" in df.columns else None,
            }
        except Exception:
            return {}

    def delete_group(self, factor_group: str) -> bool:
        """Delete an entire factor group from the store."""
        import shutil

        group_dir = self._store_dir / factor_group
        if not group_dir.exists():
            return False
        shutil.rmtree(group_dir)
        logger.info("OfflineStore: deleted group '{}'", factor_group)
        return True

    # ── Internal ──

    def _write_metadata(self, factor_group: str, df: pl.DataFrame) -> None:
        """Write metadata JSON for a factor group."""
        group_dir = self._store_dir / factor_group
        group_dir.mkdir(parents=True, exist_ok=True)

        meta: dict[str, Any] = {
            "factor_group": factor_group,
            "row_count": df.height,
            "symbol_count": df["symbol"].n_unique() if "symbol" in df.columns else 0,
            "columns": [c for c in df.columns if c not in ("year",)],
            "min_date": str(df["trade_date"].min()) if "trade_date" in df.columns else None,
            "max_date": str(df["trade_date"].max()) if "trade_date" in df.columns else None,
            "last_updated": utc_iso(),
        }

        meta_path = group_dir / "_metadata.json"
        json_save(meta_path, meta)

    def __repr__(self) -> str:
        groups = self.list_groups()
        return f"OfflineStore(dir='{self._store_dir}', groups={groups})"
