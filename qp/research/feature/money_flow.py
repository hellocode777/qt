"""Money flow factors — capital flow proxies from daily bar data.

Factors:
  - Amplitude_5D: 5-day avg intraday amplitude (high-low)/prev_close
  - Volume_Concentration: 20-day CV of daily amount (institutional activity proxy)
  - Implied_Net_Flow: Approximate net capital flow from up/down day amounts

These are derived from OHLCV data — no external capital-flow data source needed.
They approximate the behavior of real money-flow indicators.

All factors follow BaseFeature for registry compatibility and can also be
computed in batch via compute_money_flow_factors().
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class Amplitude5D(BaseFeature):
    """5-day average intraday amplitude.

    Amplitude = (high - low) / previous_close per day, averaged over 5 days.
    High amplitude = active trading / large divergence between bulls and bears.
    Consecutive low amplitude followed by volume spike = potential breakout.

    Direction: +1 (active stocks are more liquid and tradeable).
    """

    @property
    def feature_name(self) -> str:
        return "Amplitude_5D"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        prev_close = pl.col("close").shift(1).over("symbol").replace(0.0, None)
        amplitude = (pl.col("high") - pl.col("low")) / prev_close

        df = df.with_columns(amplitude.rolling_mean(5).over("symbol").alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class VolumeConcentration(BaseFeature):
    """20-day coefficient of variation of daily trading amount.

    CV = std(amount, 20d) / mean(amount, 20d).
    High CV → institutional money moving in pulses (large orders).
    Low CV → retail-driven uniform trading.

    Direction: +1 (institutional activity is a positive signal).
    """

    @property
    def feature_name(self) -> str:
        return "Volume_Concentration"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        # Use amount if available, else approximate as close * volume
        if "amount" not in df.columns:
            df = df.with_columns((pl.col("close") * pl.col("volume")).alias("amount"))

        mean_20 = pl.col("amount").rolling_mean(20).over("symbol")
        std_20 = pl.col("amount").rolling_std(20).over("symbol")

        df = df.with_columns((std_20 / mean_20.replace(0.0, None)).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class ImpliedNetFlow(BaseFeature):
    """Approximate net capital flow from up/down-day amounts.

    Logic:
      - close > open (bullish candle): daily amount = "inflow"
      - close < open (bearish candle): daily amount = "outflow"
      - Net flow = (sum inflow - sum outflow) / total amount over 5-day window.
      - Positive = net buying pressure, negative = net selling.

    Direction: +1 (net buying pressure is bullish).
    """

    @property
    def feature_name(self) -> str:
        return "Implied_Net_Flow"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        # Use amount if available
        if "amount" not in df.columns:
            df = df.with_columns((pl.col("close") * pl.col("volume")).alias("amount"))

        # Positive flow on up days, negative on down days
        up_flow = pl.when(pl.col("close") > pl.col("open")).then(pl.col("amount")).otherwise(0.0)

        down_flow = pl.when(pl.col("close") < pl.col("open")).then(pl.col("amount")).otherwise(0.0)

        total_5d = pl.col("amount").rolling_sum(5).over("symbol")
        net_5d = up_flow.rolling_sum(5).over("symbol") - down_flow.rolling_sum(5).over("symbol")

        df = df.with_columns((net_5d / total_5d.replace(0.0, None)).alias("feature_value"))
        # shift(1): prevent future information leakage — factor for day T only uses data ≤ T-1
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


# ------------------------------------------------------------------
# Batch computation
# ------------------------------------------------------------------

# A-share single-factor IC (2024-2026): all money flow factors have negative IC.
MONEY_FLOW_DIRECTIONS: dict[str, int] = {
    "Amplitude_5D": -1,
    "Volume_Concentration": -1,
    "Implied_Net_Flow": -1,
}

MONEY_FLOW_DESCRIPTIONS: dict[str, str] = {
    "Amplitude_5D": "5-day avg intraday amplitude (active trading proxy)",
    "Volume_Concentration": "CV of daily amount over 20 days (institutional proxy)",
    "Implied_Net_Flow": "Net buying pressure from up/down day amounts (5-day)",
}


def compute_money_flow_factors(df: pl.DataFrame) -> pl.DataFrame:
    """Compute all money flow factors for a single stock in one pass.

    Args:
        df: Single-stock DataFrame with [trade_date, open, high, low, close, volume]
            (sorted). Uses 'amount' column if available.

    Returns:
        DataFrame with [trade_date, factor columns...].
    """
    df = df.sort("trade_date")

    if "amount" not in df.columns:
        df = df.with_columns((pl.col("close") * pl.col("volume")).alias("amount"))

    # Amplitude (no groupby — single stock)
    prev_close = pl.col("close").shift(1).replace(0.0, None)
    amplitude = (pl.col("high") - pl.col("low")) / prev_close
    df = df.with_columns(amplitude.rolling_mean(5).alias("Amplitude_5D"))

    # Volume concentration
    mean_20 = pl.col("amount").rolling_mean(20)
    std_20 = pl.col("amount").rolling_std(20)
    df = df.with_columns((std_20 / mean_20.replace(0.0, None)).alias("Volume_Concentration"))

    # Implied net flow
    up_flow = pl.when(pl.col("close") > pl.col("open")).then(pl.col("amount")).otherwise(0.0)
    down_flow = pl.when(pl.col("close") < pl.col("open")).then(pl.col("amount")).otherwise(0.0)
    total_5d = pl.col("amount").rolling_sum(5)
    net_5d = up_flow.rolling_sum(5) - down_flow.rolling_sum(5)
    df = df.with_columns((net_5d / total_5d.replace(0.0, None)).alias("Implied_Net_Flow"))

    factor_names = ["Amplitude_5D", "Volume_Concentration", "Implied_Net_Flow"]

    # shift(1): prevent future information leakage — each factor uses only data ≤ T-1
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))

    return df.select(["trade_date"] + factor_names).drop_nulls()
