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


class ResidualMomentum3M(BaseFeature):
    """Beta-adjusted 3-month residual momentum.

    Formula: residual = stock_ret_60d - beta * market_ret_60d
    where beta = cov(stock, market)_{60d} / var(market)_{60d}.

    Removes market-driven moves, isolating stock-specific alpha.
    A-share residual momentum reverses (direction: -1).
    """

    @property
    def feature_name(self) -> str:
        return "Residual_Momentum_3M"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price", "index_price"]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Momentum"

    @property
    def lookback(self) -> int:
        return 60

    @property
    def direction(self) -> int:
        return -1

    @property
    def author(self) -> str:
        return "Wei"

    @property
    def description(self) -> str:
        return "Beta-adjusted 3-month momentum (market-neutral residual return)"

    @property
    def neutralize(self) -> list[str]:
        return ["Industry", "MarketCap"]

    @property
    def winsorize(self) -> str:
        return "MAD"

    @property
    def normalize(self) -> str:
        return "ZScore"

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        index_df = data_map.get("index_price")
        df = df.sort(["symbol", "trade_date"])
        if index_df is not None:
            index_df = index_df.sort("trade_date")

        result_parts = []
        for symbol in df["symbol"].unique():
            stock_df = df.filter(pl.col("symbol") == symbol)
            factors = compute_momentum_factors(stock_df, index_df=index_df)
            if "Residual_Momentum_3M" in factors.columns:
                result_parts.append(
                    factors.select(["trade_date", "Residual_Momentum_3M"]).with_columns(
                        pl.lit(symbol).alias("symbol")
                    )
                )

        if not result_parts:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("feature_value"))
            return df.select(["trade_date", "symbol", "feature_value"])

        result = pl.concat(result_parts, how="vertical")
        result = result.rename({"Residual_Momentum_3M": "feature_value"})
        result = result.drop_nulls(subset=["feature_value"])
        return result.select(["trade_date", "symbol", "feature_value"])


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
    "Residual_Momentum_3M": -1,  # A-share: residual momentum reverses
}

MOMENTUM_DESCRIPTIONS: dict[str, str] = {
    "Short_Term_Reversal_5D": "5-day short-term reversal (mean-reversion)",
    "Momentum_1M": "20-day momentum (~1 month)",
    "Momentum_3M": "60-day momentum (~3 months)",
    "Momentum_6M": "120-day momentum (~6 months)",
    "Momentum_3M_vol_adj": "Volatility-adjusted 3-month momentum",
    "Trend_MA120": "Price deviation from 120-day MA (trend confirmation)",
    "Residual_Momentum_3M": "Beta-adjusted 3-month momentum (market-neutral residual)",
}


def compute_momentum_factors(
    df: pl.DataFrame,
    index_df: pl.DataFrame | None = None,
    subset: list[str] | None = None,
) -> pl.DataFrame:
    """Compute all momentum factors for a single stock in one pass.

    Args:
        df: Single-stock DataFrame with [trade_date, close] (sorted).
        index_df: Optional index DataFrame with [trade_date, close] for
            computing Residual_Momentum_3M. If provided, the stock's 60-day
            return is adjusted by beta * market_return to isolate stock-
            specific alpha. If None, Residual_Momentum_3M is not computed.
        subset: If provided, only keep and drop-null these factor columns.
            Avoids the 120-day bottleneck from Momentum_6M / Trend_MA120
            when the caller only needs short-lookback factors.

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

    # Residual Momentum: beta-adjusted 3M momentum (stock-specific alpha)
    factor_names = [
        *list(_MOMENTUM_PERIODS.keys()),
        "Momentum_3M_vol_adj",
        "Trend_MA120",
    ]
    if index_df is not None and not index_df.is_empty():
        df = _compute_residual_momentum(df, index_df)
        factor_names.append("Residual_Momentum_3M")

    # shift(1): prevent future information leakage — each factor uses only data ≤ T-1
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))

    keep = subset if subset else factor_names
    return df.select(["trade_date", *keep]).drop_nulls(subset=keep)


def _compute_residual_momentum(
    df: pl.DataFrame,
    index_df: pl.DataFrame,
    window: int = 60,
) -> pl.DataFrame:
    """Compute beta-adjusted 3-month residual momentum.

    residual = stock_ret_60d - beta * index_ret_60d

    where beta = cov(stock_daily_ret, index_daily_ret)_{60d}
                / var(index_daily_ret)_{60d}

    Removes market-driven moves, isolating stock-specific alpha.
    A-share residual momentum also reverses (direction = -1).
    """
    # Normalize index_df column names (accept both "date" and "trade_date")
    idx = index_df.clone()
    if "date" in idx.columns and "trade_date" not in idx.columns:
        idx = idx.rename({"date": "trade_date"})
    # Cast to match stock DataFrame's trade_date type
    idx = idx.with_columns(pl.col("trade_date").cast(df["trade_date"].dtype))
    idx = idx.sort("trade_date").with_columns(pl.col("close").pct_change().alias("idx_ret"))
    idx = idx.drop_nulls(subset=["idx_ret"])

    # Merge market returns onto stock DataFrame by trade_date
    df = df.join(
        idx.select(["trade_date", "idx_ret"]),
        on="trade_date",
        how="left",
    )
    df = df.sort("trade_date")

    # Daily stock return
    df = df.with_columns(pl.col("close").pct_change().alias("stock_ret"))

    # Rolling covariance / variance = rolling beta
    stock_x_idx = (pl.col("stock_ret") * pl.col("idx_ret")).rolling_sum(window)
    idx_sq = (pl.col("idx_ret") ** 2).rolling_sum(window)
    df = df.with_columns((stock_x_idx / idx_sq.replace(0.0, None)).alias("_beta"))

    # Residual = raw 60d momentum - beta * index 60d return
    df = df.with_columns(pl.col("close").pct_change(window).alias("_stock_mom"))
    idx_mom = pl.col("idx_ret").rolling_sum(window)
    df = df.with_columns(
        (pl.col("_stock_mom") - pl.col("_beta") * idx_mom).alias("Residual_Momentum_3M")
    )

    # Cleanup
    return df.drop(["_beta", "_stock_mom", "stock_ret", "idx_ret"])


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

# Momentum20dFeature is the legacy name for Momentum1M (ADR-019)
Momentum20dFeature = Momentum1M
