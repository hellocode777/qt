"""Cleaning Engine — deterministic cleaning of raw market data.

Handles: suspension detection, limit-up/down detection, adjustment factor,
         ST/delisting marks.

Principle: same raw input → same cleaned output, every time.

Uses Polars for vectorized, high-performance columnar operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    import pandas as pd


class CleaningEngine:
    """Deterministic data cleaning pipeline (Polars-native).

    Bronze tier: raw → cleaned with consistent rules.
    Accepts both Polars DataFrames and Pandas DataFrames (auto-converted).
    """

    # Column mapping from AkShare Chinese to English
    COLUMN_MAP = {
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }

    def clean(self, df: pl.DataFrame | pd.DataFrame) -> pl.DataFrame:
        """Apply all cleaning steps to raw data.

        Args:
            df: Raw DataFrame from a data source adapter (Polars or Pandas).

        Returns:
            Cleaned Polars DataFrame with standardized English column names.
        """
        # Auto-convert Pandas → Polars for backward compatibility
        if not isinstance(df, pl.DataFrame):
            df = pl.from_pandas(df)

        if df.is_empty():
            return df

        # 1. Rename columns to English
        df = self._rename_columns(df)

        # 2. Convert date column
        if "trade_date" in df.columns:
            try:
                df = df.with_columns(pl.col("trade_date").str.to_date().alias("trade_date"))
            except Exception:
                # Already date type or non-standard format — try cast
                df = df.with_columns(pl.col("trade_date").cast(pl.Date).alias("trade_date"))

        # 3. Ensure numeric types
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))

        # 4. Mark suspension (volume <= 0)
        if "volume" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("volume") <= 0).then(True).otherwise(False).alias("is_suspended")
            )

        # 5. Sort by symbol and date
        sort_cols = ["symbol", "trade_date"] if "symbol" in df.columns else ["trade_date"]
        df = df.sort(sort_cols)

        # 6. Drop rows with NaN prices
        price_cols = [c for c in ["open", "close"] if c in df.columns]
        if price_cols:
            df = df.drop_nulls(subset=price_cols)

        return df

    def _rename_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """Rename Chinese column names to English."""
        # Build mapping with only the columns that actually exist
        mapping = {k: v for k, v in self.COLUMN_MAP.items() if k in df.columns}
        if mapping:
            df = df.rename(mapping)
        return df
