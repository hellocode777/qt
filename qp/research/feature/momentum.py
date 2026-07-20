"""Momentum20dFeature — 20-day price momentum factor.

Implements BaseFeature for Walking Skeleton demonstration.
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class Momentum20dFeature(BaseFeature):
    """20-day momentum: (close_today - close_20d_ago) / close_20d_ago."""

    @property
    def feature_name(self) -> str:
        return "momentum_20d"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        """Compute 20-day momentum for all symbols.

        Args:
            data_map: {"daily_price": Polars DataFrame}

        Returns:
            DataFrame with [trade_date, symbol, feature_value].
        """
        df = data_map["daily_price"].clone()

        required_cols = ["trade_date", "symbol", "close"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        df = df.sort(["symbol", "trade_date"])

        # Compute 20-day return
        df = df.with_columns(
            (
                (pl.col("close") - pl.col("close").shift(20).over("symbol"))
                / pl.col("close").shift(20).over("symbol")
            ).alias("feature_value")
        )

        # Drop rows without enough history
        df = df.drop_nulls(subset=["feature_value"])

        return df.select(["trade_date", "symbol", "feature_value"])
