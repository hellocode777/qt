"""Momentum factors — multi-period returns and vol-adjusted momentum.

Factors:
  - Short_Term_Reversal_5D: 5-day return (short-term reversal)
  - Momentum_1M: 20-day return (~1 month)
  - Momentum_3M: 60-day return (~3 months)
  - Momentum_6M: 120-day return (~6 months)
  - Momentum_3M_vol_adj: 60-day return / 60-day volatility

Also supports residual momentum: beta-adjusted 3M momentum that removes
market-driven moves, isolating stock-specific alpha.

All factors follow BaseFeature for registry compatibility and can also be
computed in batch via compute_momentum_factors().
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class ShortTermReversal5D(BaseFeature):
    """Short-term reversal: 5-day cumulative return.

    Direction: -1 (reversal — recent winners likely to underperform).
    """

    @property
    def feature_name(self) -> str:
        return "Short_Term_Reversal_5D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])
        df = df.with_columns((pl.col("close").pct_change(5).over("symbol")).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class Momentum1M(BaseFeature):
    """1-month momentum: 20-day cumulative return.  Direction: +1."""

    @property
    def feature_name(self) -> str:
        return "Momentum_1M"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])
        df = df.with_columns((pl.col("close").pct_change(20).over("symbol")).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class Momentum3M(BaseFeature):
    """3-month momentum: 60-day cumulative return.  Direction: +1."""

    @property
    def feature_name(self) -> str:
        return "Momentum_3M"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])
        df = df.with_columns((pl.col("close").pct_change(60).over("symbol")).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class Momentum6M(BaseFeature):
    """6-month momentum: 120-day cumulative return.  Direction: +1."""

    @property
    def feature_name(self) -> str:
        return "Momentum_6M"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])
        df = df.with_columns(
            (pl.col("close").pct_change(120).over("symbol")).alias("feature_value")
        )
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class Momentum3MVolAdjusted(BaseFeature):
    """Volatility-adjusted 3M momentum: 60d return / 60d volatility.

    Higher values mean high return per unit of risk — a more stable signal
    than raw momentum.  Direction: +1.
    """

    @property
    def feature_name(self) -> str:
        return "Momentum_3M_vol_adj"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        ret_60d = pl.col("close").pct_change(60).over("symbol")
        vol_60d = pl.col("close").pct_change().rolling_std(60).over("symbol")

        df = df.with_columns((ret_60d / vol_60d.replace(0.0, None)).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


# ------------------------------------------------------------------
# Batch computation — compute all momentum factors in one pass
# ------------------------------------------------------------------

_MOMENTUM_PERIODS: dict[str, int] = {
    "Short_Term_Reversal_5D": 5,
    "Momentum_1M": 20,
    "Momentum_3M": 60,
    "Momentum_6M": 120,
}

# Factor directions calibrated to A-share market (2024-2026 single-factor IC).
# Chinese A-shares exhibit strong mean-reversion: past winners underperform.
# All momentum factors have negative IC → direction flipped to -1.
MOMENTUM_DIRECTIONS: dict[str, int] = {
    "Short_Term_Reversal_5D": -1,  # 5-day reversal (IC confirms)
    "Momentum_1M": -1,  # A-share: momentum reverses
    "Momentum_3M": -1,  # A-share: momentum reverses
    "Momentum_6M": -1,  # A-share: momentum reverses
    "Momentum_3M_vol_adj": -1,  # A-share: momentum reverses
    "Trend_MA120": +1,  # Price > MA120 = trend confirmation
}

MOMENTUM_DESCRIPTIONS: dict[str, str] = {
    "Short_Term_Reversal_5D": "5-day short-term reversal (mean-reversion)",
    "Momentum_1M": "20-day momentum (~1 month)",
    "Momentum_3M": "60-day momentum (~3 months)",
    "Momentum_6M": "120-day momentum (~6 months)",
    "Momentum_3M_vol_adj": "Volatility-adjusted 3-month momentum",
    "Trend_MA120": "Price deviation from 120-day MA (trend confirmation)",
}


def compute_momentum_factors(df: pl.DataFrame) -> pl.DataFrame:
    """Compute all momentum factors for a single stock in one pass.

    Args:
        df: Single-stock DataFrame with [trade_date, close] (sorted).

    Returns:
        DataFrame with [trade_date, factor columns...].
    """
    df = df.sort("trade_date")

    for name, period in _MOMENTUM_PERIODS.items():
        df = df.with_columns(pl.col("close").pct_change(period).alias(name))

    # Vol-adjusted momentum
    df = df.with_columns(pl.col("close").pct_change().rolling_std(60).alias("_vol_60d"))
    df = df.with_columns(
        (pl.col("Momentum_3M") / pl.col("_vol_60d").replace(0.0, None)).alias("Momentum_3M_vol_adj")
    )
    df = df.drop("_vol_60d")

    # Trend confirmation: price deviation from 120-day MA (positive = uptrend)
    ma120 = pl.col("close").rolling_mean(120)
    df = df.with_columns(
        ((pl.col("close") - ma120) / ma120.replace(0.0, None)).alias("Trend_MA120")
    )

    factor_names = list(_MOMENTUM_PERIODS.keys()) + ["Momentum_3M_vol_adj", "Trend_MA120"]

    # shift(1): prevent future information leakage — each factor uses only data ≤ T-1
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))

    return df.select(["trade_date"] + factor_names).drop_nulls()


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

# Momentum20dFeature is the legacy name for Momentum1M (ADR-019)
Momentum20dFeature = Momentum1M
