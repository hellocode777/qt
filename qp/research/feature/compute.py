"""Batch factor computation — compute all price/volume factors in one pass per stock.

Efficient alternative to computing each factor independently via BaseFeature.
Computes all 15+ factors across 5 categories for a single stock's DataFrame.

Usage:
    from qp.research.feature.compute import compute_all_factors

    factors = compute_all_factors(df)  # df = single stock, sorted by trade_date
    # Returns DataFrame with [trade_date, factor_1, factor_2, ...]
"""

from __future__ import annotations

import polars as pl

from qp.research.feature.momentum import (
    MOMENTUM_DESCRIPTIONS,
    MOMENTUM_DIRECTIONS,
    compute_momentum_factors,
)
from qp.research.feature.money_flow import (
    MONEY_FLOW_DESCRIPTIONS,
    MONEY_FLOW_DIRECTIONS,
    compute_money_flow_factors,
)
from qp.research.feature.volatility import (
    VOLATILITY_DESCRIPTIONS,
    VOLATILITY_DIRECTIONS,
    compute_volatility_factors,
)
from qp.research.feature.volume import (
    VOLUME_DESCRIPTIONS,
    VOLUME_DIRECTIONS,
    compute_volume_factors,
)

# ------------------------------------------------------------------
# Master registry of all price/volume factors
# ------------------------------------------------------------------

ALL_FACTOR_DIRECTIONS: dict[str, int] = {
    **MOMENTUM_DIRECTIONS,
    **VOLATILITY_DIRECTIONS,
    **VOLUME_DIRECTIONS,
    **MONEY_FLOW_DIRECTIONS,
}

ALL_FACTOR_DESCRIPTIONS: dict[str, str] = {
    **MOMENTUM_DESCRIPTIONS,
    **VOLATILITY_DESCRIPTIONS,
    **VOLUME_DESCRIPTIONS,
    **MONEY_FLOW_DESCRIPTIONS,
}

PRICE_VOLUME_FACTORS: list[str] = (
    list(MOMENTUM_DIRECTIONS.keys())
    + list(VOLATILITY_DIRECTIONS.keys())
    + list(VOLUME_DIRECTIONS.keys())
    + list(MONEY_FLOW_DIRECTIONS.keys())
)


def get_default_factor_weights() -> dict[str, float]:
    """Equal-weight all available price/volume factors.

    Returns:
        {factor_name: 1.0 / n_factors} for all price/volume factors.
    """
    n = len(PRICE_VOLUME_FACTORS)
    w = 1.0 / n
    return dict.fromkeys(PRICE_VOLUME_FACTORS, w)


def compute_all_factors(df: pl.DataFrame) -> pl.DataFrame:
    """Compute all price/volume factors for a single stock in one pass.

    Factors computed (15 total):
      Momentum (5): Short_Term_Reversal_5D, Momentum_1M, Momentum_3M,
                     Momentum_6M, Momentum_3M_vol_adj
      Volatility (3): Volatility_20D, Volatility_60D, MaxDD_60D
      Volume (4): Volume_Ratio_5D, Volume_Trend_10D, Price_Volume_Corr,
                  Volume_Price_Trend
      Money Flow (3): Amplitude_5D, Volume_Concentration, Implied_Net_Flow

    Args:
        df: Single-stock DataFrame with [trade_date, open, high, low, close, volume].
            Must be sorted by trade_date ascending. Uses 'amount' if available.

    Returns:
        DataFrame with [trade_date] + all factor columns. Rows with NaN
        in any factor are dropped (insufficient history).
    """
    df = df.sort("trade_date")

    # Compute each category
    momentum = compute_momentum_factors(df)
    volatility = compute_volatility_factors(df)
    volume = compute_volume_factors(df)
    money_flow = compute_money_flow_factors(df)

    # Join all on trade_date
    result = momentum.join(volatility, on="trade_date", how="inner")
    result = result.join(volume, on="trade_date", how="inner")
    result = result.join(money_flow, on="trade_date", how="inner")

    return result.drop_nulls()
