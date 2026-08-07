"""Volatility factors — risk-based signals.

Factors:
  - Volatility_20D: 20-day annualized volatility (direction: -1, low-vol anomaly)
  - Volatility_60D: 60-day annualized volatility (direction: -1)
  - MaxDD_60D: 60-day maximum drawdown (direction: -1, penalize large drawdowns)

All factors follow BaseFeature for registry compatibility and can also be
computed in batch via compute_volatility_factors().
"""

from __future__ import annotations

import polars as pl

from qp.shared.constants import TRADING_DAYS_PER_YEAR
from qp.shared.protocols.base_feature import BaseFeature


class Volatility20D(BaseFeature):
    """20-day annualized historical volatility (inverted).

    Low-volatility stocks tend to outperform risk-adjusted
    (the low-volatility anomaly).  Negative sign so low-vol stocks score higher.
    """

    @property
    def feature_name(self) -> str:
        return "Volatility_20D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        df = df.with_columns(pl.col("close").log().diff().over("symbol").alias("log_return"))
        df = df.with_columns(
            (
                -pl.col("log_return").rolling_std(20).over("symbol") * (TRADING_DAYS_PER_YEAR**0.5)
            ).alias("feature_value")
        )
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class Volatility60D(BaseFeature):
    """60-day annualized historical volatility (inverted).  Direction: -1."""

    @property
    def feature_name(self) -> str:
        return "Volatility_60D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        df = df.with_columns(pl.col("close").log().diff().over("symbol").alias("log_return"))
        df = df.with_columns(
            (
                -pl.col("log_return").rolling_std(60).over("symbol") * (TRADING_DAYS_PER_YEAR**0.5)
            ).alias("feature_value")
        )
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class MaxDrawdown60D(BaseFeature):
    """60-day maximum drawdown (negative values, smaller = worse drawdown).

    Computed as: (close - rolling_max_60d) / rolling_max_60d.
    Values range from -1 to 0, with 0 meaning at all-time-high.
    Direction: -1 (stocks closer to highs are preferred).
    """

    @property
    def feature_name(self) -> str:
        return "MaxDD_60D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        rolling_max = pl.col("close").rolling_max(60).over("symbol")
        df = df.with_columns(
            ((pl.col("close") - rolling_max) / rolling_max.replace(0.0, None)).alias(
                "feature_value"
            )
        )
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


# ------------------------------------------------------------------
# Batch computation
# ------------------------------------------------------------------

# All three factors already encode "higher = better" in their computation:
#   - Volatility is negated: low vol → high score
#   - MaxDD is (close-max)/max: near high → near 0 → higher is better
# Single-factor IC confirms these directions for A-share market.
VOLATILITY_DIRECTIONS: dict[str, int] = {
    "Volatility_20D": 1,
    "Volatility_60D": 1,
    "MaxDD_60D": 1,
}

VOLATILITY_DESCRIPTIONS: dict[str, str] = {
    "Volatility_20D": "20-day annualized volatility (low-vol anomaly)",
    "Volatility_60D": "60-day annualized volatility",
    "MaxDD_60D": "60-day maximum drawdown from rolling high",
}


def compute_volatility_factors(
    df: pl.DataFrame,
    subset: list[str] | None = None,
) -> pl.DataFrame:
    """Compute all volatility factors for a single stock in one pass.

    Args:
        df: Single-stock DataFrame with [trade_date, close] (sorted).
        subset: If provided, only keep and drop-null these factor columns.
            Avoids the 60-day bottleneck from Volatility_60D / MaxDD_60D
            when the caller only needs Volatility_20D.

    Returns:
        DataFrame with [trade_date, Volatility_20D, Volatility_60D, MaxDD_60D].
    """
    df = df.sort("trade_date")

    daily_ret = pl.col("close").pct_change()
    sqrt252 = TRADING_DAYS_PER_YEAR**0.5

    df = df.with_columns(
        (-daily_ret.rolling_std(20) * sqrt252).alias("Volatility_20D"),
        (-daily_ret.rolling_std(60) * sqrt252).alias("Volatility_60D"),
    )

    rolling_max = pl.col("close").rolling_max(60)
    df = df.with_columns(
        ((pl.col("close") - rolling_max) / rolling_max.replace(0.0, None)).alias("MaxDD_60D")
    )

    factor_names = ["Volatility_20D", "Volatility_60D", "MaxDD_60D"]

    # shift(1): prevent future information leakage — each factor uses only data ≤ T-1
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))

    keep = subset if subset else factor_names
    return df.select(["trade_date", *keep]).drop_nulls(subset=keep)


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

# Volatility20dFeature is the legacy name for Volatility20D (ADR-019)
Volatility20dFeature = Volatility20D
