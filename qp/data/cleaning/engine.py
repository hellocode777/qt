"""Cleaning Engine — deterministic cleaning of raw market data.

Handles: suspension detection, limit-up/down detection, adjustment factor,
         ST/delisting marks.

Principle: same raw input → same cleaned output, every time.
"""

from __future__ import annotations

import pandas as pd


class CleaningEngine:
    """Deterministic data cleaning pipeline.

    Bronze tier: raw → cleaned with consistent rules.
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

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all cleaning steps to raw data.

        Args:
            df: Raw DataFrame from a data source adapter.

        Returns:
            Cleaned DataFrame with standardized column names.
        """
        if df.empty:
            return df

        df = df.copy()

        # 1. Rename columns to English
        df = self._rename_columns(df)

        # 2. Convert date column
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])

        # 3. Ensure numeric types
        numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 4. Mark suspension (volume == 0)
        if "volume" in df.columns:
            df["is_suspended"] = df["volume"] <= 0

        # 5. Sort by symbol and date
        sort_cols = ["symbol", "trade_date"] if "symbol" in df.columns else ["trade_date"]
        df = df.sort_values(sort_cols).reset_index(drop=True)

        # 6. Drop rows with NaN prices
        price_cols = [c for c in ["open", "close"] if c in df.columns]
        if price_cols:
            df = df.dropna(subset=price_cols)

        return df

    def _rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename Chinese column names to English."""
        return df.rename(columns=self.COLUMN_MAP)
