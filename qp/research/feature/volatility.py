"""Volatility20dFeature — 20-day historical volatility factor.

A non-momentum alpha factor: low-volatility stocks tend to outperform
risk-adjusted (the low-volatility anomaly).  Anti-correlated with
momentum, providing diversification benefit.

Formula: -std(log_return, 20) * sqrt(252)
  Higher score → lower volatility (inverted).
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class Volatility20dFeature(BaseFeature):
    """20-day annualized historical volatility (inverted).

    Low volatility stocks score higher.  Volatility is computed from
    daily log returns over a 20-day rolling window, then annualized.
    The negative sign means lower-vol stocks rank first.
    """

    @property
    def feature_name(self) -> str:
        return "volatility_20d"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        """Compute 20-day annualized volatility for all symbols.

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

        # Log returns
        df = df.with_columns((pl.col("close").log().diff().over("symbol")).alias("log_return"))

        # 20-day rolling std of log returns, annualized, inverted
        df = df.with_columns(
            (-pl.col("log_return").rolling_std(20).over("symbol") * (252**0.5)).alias(
                "feature_value"
            )
        )

        # Drop rows without enough history
        df = df.drop_nulls(subset=["feature_value"])

        return df.select(["trade_date", "symbol", "feature_value"])
