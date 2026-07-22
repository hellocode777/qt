"""Volume-price factors — liquidity and money-flow signals.

Factors:
  - Volume_Ratio_5D: Volume / 5-day avg volume (volume breakout)
  - Volume_Trend_10D: 5-day MA volume / 20-day MA volume (volume trend)
  - Price_Volume_Corr: 20-day correlation between return and volume
  - Volume_Price_Trend: Sign of price_slope * volume_slope (trend confirmation)

All factors follow BaseFeature for registry compatibility and can also be
computed in batch via compute_volume_factors().
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class VolumeRatio5D(BaseFeature):
    """Volume relative to 5-day average.  > 1 = volume breakout.

    Direction: +1 (high relative volume often precedes price moves).
    """

    @property
    def feature_name(self) -> str:
        return "Volume_Ratio_5D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        ma5 = pl.col("volume").rolling_mean(5).over("symbol")
        df = df.with_columns((pl.col("volume") / ma5.replace(0.0, None)).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class VolumeTrend10D(BaseFeature):
    """Volume trend: 5-day MA / 20-day MA of volume.

    > 1 = expanding volume (increasing interest).  Direction: +1.
    """

    @property
    def feature_name(self) -> str:
        return "Volume_Trend_10D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        ma5 = pl.col("volume").rolling_mean(5).over("symbol")
        ma20 = pl.col("volume").rolling_mean(20).over("symbol")
        df = df.with_columns((ma5 / ma20.replace(0.0, None)).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class PriceVolumeCorr(BaseFeature):
    """20-day correlation between daily return and volume.

    Positive = rising prices with rising volume (healthy trend).
    Negative = divergence (rising price, declining volume = weak).

    Direction: +1 (volume confirming price trend is positive).
    """

    @property
    def feature_name(self) -> str:
        return "Price_Volume_Corr"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        ret = pl.col("close").pct_change()
        vol_col = pl.col("volume")

        # Rolling correlation = cov(ret, vol) / (std(ret) * std(vol))
        ret_mean = ret.rolling_mean(20).over("symbol")
        vol_mean = vol_col.rolling_mean(20).over("symbol")
        cov = ((ret - ret_mean) * (vol_col - vol_mean)).rolling_mean(20).over("symbol")
        std_ret = ret.rolling_std(20).over("symbol")
        std_vol = vol_col.rolling_std(20).over("symbol")
        corr = cov / (std_ret * std_vol).replace(0.0, None)

        df = df.with_columns(corr.alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class VolumePriceTrend(BaseFeature):
    """Volume-price trend consistency: sign(price_slope * volume_slope).

    +1 = price and volume moving together (confirmed trend).
    -1 = divergence.

    Direction: +1 (confirmed trends are more reliable).
    """

    @property
    def feature_name(self) -> str:
        return "Volume_Price_Trend"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        price_slope = pl.col("close").rolling_mean(5).diff(5).over("symbol")
        vol_slope = pl.col("volume").rolling_mean(5).diff(5).over("symbol")

        df = df.with_columns((price_slope.sign() * vol_slope.sign()).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


# ------------------------------------------------------------------
# Batch computation
# ------------------------------------------------------------------

# A-share single-factor IC (2024-2026): all volume factors have negative IC.
# Higher volume/activity predicts lower future returns (contrarian signal).
VOLUME_DIRECTIONS: dict[str, int] = {
    "Volume_Ratio_5D": -1,
    "Volume_Trend_10D": -1,
    "Price_Volume_Corr": -1,
    "Volume_Price_Trend": -1,
}

VOLUME_DESCRIPTIONS: dict[str, str] = {
    "Volume_Ratio_5D": "Volume / 5-day MA (volume breakout detection)",
    "Volume_Trend_10D": "5-day MA volume / 20-day MA volume (volume trend)",
    "Price_Volume_Corr": "20-day correlation between return and volume",
    "Volume_Price_Trend": "Sign consistency of price & volume slope",
}


def compute_volume_factors(df: pl.DataFrame) -> pl.DataFrame:
    """Compute all volume factors for a single stock in one pass.

    Args:
        df: Single-stock DataFrame with [trade_date, close, volume] (sorted).

    Returns:
        DataFrame with [trade_date, factor columns...].
    """
    df = df.sort("trade_date")

    # Volume ratios (no groupby — single stock)
    ma5 = pl.col("volume").rolling_mean(5)
    ma20 = pl.col("volume").rolling_mean(20)

    df = df.with_columns(
        (pl.col("volume") / ma5.replace(0.0, None)).alias("Volume_Ratio_5D"),
        (ma5 / ma20.replace(0.0, None)).alias("Volume_Trend_10D"),
    )

    # Price-volume correlation
    ret = pl.col("close").pct_change()
    ret_mean = ret.rolling_mean(20)
    vol_mean = pl.col("volume").rolling_mean(20)
    cov = ((ret - ret_mean) * (pl.col("volume") - vol_mean)).rolling_mean(20)
    std_ret = ret.rolling_std(20)
    std_vol = pl.col("volume").rolling_std(20)
    df = df.with_columns((cov / (std_ret * std_vol).replace(0.0, None)).alias("Price_Volume_Corr"))

    # Volume-price trend consistency
    price_slope = pl.col("close").rolling_mean(5).diff(5)
    vol_slope = pl.col("volume").rolling_mean(5).diff(5)
    df = df.with_columns((price_slope.sign() * vol_slope.sign()).alias("Volume_Price_Trend"))

    factor_names = [
        "Volume_Ratio_5D",
        "Volume_Trend_10D",
        "Price_Volume_Corr",
        "Volume_Price_Trend",
    ]

    # shift(1): prevent future information leakage — each factor uses only data ≤ T-1
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))

    return df.select(["trade_date"] + factor_names).drop_nulls()
