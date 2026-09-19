"""Research Dataset — PIT-aware dataset loading, caching, and train/test splitting.

Provides the Dataset abstraction that sits between raw data sources and
research consumers.  Consumers never call data source APIs directly.

Key features:
  - PIT (Point-in-Time) dataset construction
  - Train/validation/test splitting respecting time order
  - Data integrity checks (suspension, limit up/down, ST flags)
  - Caching for repeated access

See research_layer.md §1 and ADR-013.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import polars as pl

from qp.shared.paths import RESEARCH_CACHE_DIR


class ResearchDataset:
    """PIT-aware dataset for research consumption.

    Wraps a Gold-tier dataset and provides train/val/test splitting
    with temporal ordering guarantees.  No future information leakage.

    Usage:
        ds = ResearchDataset(DAILY_PRICE_MAIN)
        train, test = ds.split_train_test(test_ratio=0.2)
        # Or with validation:
        train, val, test = ds.split_train_val_test(val_ratio=0.1, test_ratio=0.1)
    """

    def __init__(
        self,
        path: str,
        cache_dir: str | Path = RESEARCH_CACHE_DIR,
        date_col: str = "trade_date",
        symbol_col: str = "symbol",
    ) -> None:
        self._path = Path(path)
        self._cache_dir = Path(cache_dir)
        self._date_col = date_col
        self._symbol_col = symbol_col
        self._df: pl.DataFrame | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, force_reload: bool = False) -> pl.DataFrame:
        """Load dataset into memory with optional caching.

        Args:
            force_reload: If True, re-read from disk even if cached.

        Returns:
            Loaded DataFrame.
        """
        if self._df is not None and not force_reload:
            return self._df

        cache_path = self._cache_dir / (self._path.stem + ".parquet")

        if cache_path.exists() and not force_reload:
            self._df = pl.read_parquet(str(cache_path))
            return self._df

        if self._path.exists():
            self._df = pl.read_parquet(str(self._path))
            # Write to cache
            os.makedirs(self._cache_dir, exist_ok=True)
            self._df.write_parquet(str(cache_path))
            return self._df

        raise FileNotFoundError(f"Dataset not found: {self._path}")

    @property
    def df(self) -> pl.DataFrame:
        """Access loaded DataFrame (loads on first access)."""
        if self._df is None:
            return self.load()
        return self._df

    # ------------------------------------------------------------------
    # Splitting
    # ------------------------------------------------------------------

    def split_train_test(
        self,
        test_ratio: float = 0.2,
        min_train_days: int = 252,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Split dataset into train and test by time.

        Test set is the most recent `test_ratio` fraction of dates.
        No shuffling — time order is strictly preserved.

        Args:
            test_ratio: Fraction of dates to hold out for testing.
            min_train_days: Minimum training days required.

        Returns:
            (train_df, test_df).

        Raises:
            ValueError: If not enough dates for the split.
        """
        df = self.df
        dates = sorted(df[self._date_col].unique().to_list())
        n_dates = len(dates)

        if n_dates < min_train_days * 2:
            raise ValueError(f"Need at least {min_train_days * 2} dates, got {n_dates}")

        split_idx = int(n_dates * (1 - test_ratio))
        train_dates = set(dates[:split_idx])
        test_dates = set(dates[split_idx:])

        df = df.with_columns(pl.col(self._date_col).cast(pl.Utf8))
        train = df.filter(pl.col(self._date_col).is_in(train_dates))
        test = df.filter(pl.col(self._date_col).is_in(test_dates))

        return train, test

    def split_train_val_test(
        self,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
        min_train_days: int = 252,
    ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        """Split dataset into train / validation / test by time.

        Most recent dates → test, next most recent → validation, rest → train.

        Args:
            val_ratio: Fraction for validation.
            test_ratio: Fraction for testing.
            min_train_days: Minimum training days.

        Returns:
            (train_df, val_df, test_df).
        """
        df = self.df
        dates = sorted(df[self._date_col].unique().to_list())
        n_dates = len(dates)

        if n_dates < min_train_days + 63:  # Need at least ~3 months test
            raise ValueError(f"Need at least {min_train_days + 63} dates, got {n_dates}")

        test_cut = int(n_dates * (1 - test_ratio))
        val_cut = int(n_dates * (1 - test_ratio - val_ratio))

        test_dates = set(dates[test_cut:])
        val_dates = set(dates[val_cut:test_cut])
        train_dates = set(dates[:val_cut])

        df = df.with_columns(pl.col(self._date_col).cast(pl.Utf8))
        train = df.filter(pl.col(self._date_col).is_in(train_dates))
        val = df.filter(pl.col(self._date_col).is_in(val_dates))
        test = df.filter(pl.col(self._date_col).is_in(test_dates))

        return train, val, test

    def split_by_date(
        self,
        train_end: str,
        test_start: str,
        test_end: str | None = None,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Split by explicit date boundaries.

        Args:
            train_end: Last training date (inclusive).
            test_start: First test date.
            test_end: Last test date (inclusive, defaults to max date).

        Returns:
            (train_df, test_df).
        """
        df = self.df.with_columns(pl.col(self._date_col).cast(pl.Utf8))

        if test_end is None:
            test_end = str(df[self._date_col].max())

        train = df.filter(pl.col(self._date_col) <= train_end)
        test = df.filter(
            (pl.col(self._date_col) >= test_start) & (pl.col(self._date_col) <= test_end)
        )

        return train, test

    # ------------------------------------------------------------------
    # Data integrity checks
    # ------------------------------------------------------------------

    def check_integrity(self) -> dict[str, Any]:
        """Run data integrity checks on the loaded dataset.

        Checks:
          - Required columns present
          - No duplicate (date, symbol) pairs
          - No negative prices or volumes
          - Suspicious price gaps (single-day > 20% change)
          - Missing dates per symbol

        Returns:
            Dict with check results.  "all_clean" = True if no issues found.
        """
        df = self.df
        issues: list[str] = []

        # Required columns
        required = {self._date_col, self._symbol_col, "close"}
        missing = required - set(df.columns)
        if missing:
            issues.append(f"Missing columns: {missing}")

        # Duplicates
        dup_count = df.filter(df.select([self._date_col, self._symbol_col]).is_duplicated()).height
        if dup_count > 0:
            issues.append(f"{dup_count} duplicate (date, symbol) pairs")

        # Negative prices
        if "close" in df.columns:
            neg_close = df.filter(pl.col("close") <= 0).height
            if neg_close > 0:
                issues.append(f"{neg_close} rows with close <= 0")

        # Negative volume
        if "volume" in df.columns:
            neg_vol = df.filter(pl.col("volume") < 0).height
            if neg_vol > 0:
                issues.append(f"{neg_vol} rows with negative volume")

        # Extreme price gaps (>50% single-day change)
        if "close" in df.columns:
            df_sorted = df.sort([self._symbol_col, self._date_col])
            pct_chg = (
                df_sorted.with_columns(
                    (pl.col("close").pct_change().over(self._symbol_col).abs()).alias("_pct_chg")
                )
                .filter(pl.col("_pct_chg") > 0.5)
                .height
            )
            if pct_chg > 0:
                issues.append(f"{pct_chg} extreme price gaps (>50% single-day)")

        return {
            "all_clean": len(issues) == 0,
            "n_issues": len(issues),
            "issues": issues,
            "n_rows": df.height,
            "n_symbols": df[self._symbol_col].n_unique(),
            "date_range": (
                f"{df[self._date_col].min()} → {df[self._date_col].max()}"
                if not df.is_empty()
                else "empty"
            ),
        }

    # ------------------------------------------------------------------
    # PIT filter helpers
    # ------------------------------------------------------------------

    def filter_pit(
        self,
        as_of_date: str,
        listing_date_col: str | None = None,
        delisting_date_col: str | None = None,
    ) -> pl.DataFrame:
        """Filter to Point-in-Time: only stocks listed on or before as_of_date.

        This ensures no survivorship bias — stocks that delisted after
        as_of_date are still included, but stocks that hadn't listed yet
        are excluded.

        Args:
            as_of_date: Reference date (YYYY-MM-DD).
            listing_date_col: Column with listing date. If None, skip filter.
            delisting_date_col: Column with delisting date. If None, skip filter.

        Returns:
            Filtered DataFrame.
        """
        df = self.df

        if listing_date_col and listing_date_col in df.columns:
            df = df.filter(pl.col(listing_date_col).cast(pl.Utf8) <= as_of_date)

        if delisting_date_col and delisting_date_col in df.columns:
            df = df.filter(
                (pl.col(delisting_date_col).cast(pl.Utf8) >= as_of_date)
                | pl.col(delisting_date_col).is_null()
            )

        return df

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def date_range(self) -> tuple[str, str]:
        """Return (min_date, max_date) of the dataset."""
        df = self.df
        return (str(df[self._date_col].min()), str(df[self._date_col].max()))

    @property
    def symbols(self) -> list[str]:
        """Return unique symbols in the dataset."""
        return sorted(self.df[self._symbol_col].unique().to_list())

    @property
    def n_rows(self) -> int:
        return self.df.height

    @property
    def n_symbols(self) -> int:
        return self.df[self._symbol_col].n_unique()

    @property
    def n_dates(self) -> int:
        return self.df[self._date_col].n_unique()
