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


def compute_all_factors(
    df: pl.DataFrame,
    subset: list[str] | None = None,
    index_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
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
        subset: If provided, only drop rows where these specific columns are NaN.
            This avoids the 121-day bottleneck from unused long-lookback factors
            (e.g. Momentum_6M, Trend_MA120) when the caller only needs short-lookback
            factors. When None (default), drops rows with NaN in ANY factor column
            (backward-compatible behavior).
        index_df: Optional index DataFrame with [trade_date, close] for
            computing Residual_Momentum_3M. Passed through to
            compute_momentum_factors.

    Returns:
        DataFrame with [trade_date] + all factor columns. Rows with NaN
        in the relevant columns are dropped (insufficient history).
    """
    df = df.sort("trade_date")

    # Compute each category
    momentum = compute_momentum_factors(df, index_df=index_df)
    volatility = compute_volatility_factors(df)
    volume = compute_volume_factors(df)
    money_flow = compute_money_flow_factors(df)

    # Join all on trade_date
    result = momentum.join(volatility, on="trade_date", how="inner")
    result = result.join(volume, on="trade_date", how="inner")
    result = result.join(money_flow, on="trade_date", how="inner")

    if subset:
        return result.drop_nulls(subset=subset)
    return result.drop_nulls()


def compute_composite_factors(
    factor_df: pl.DataFrame,
) -> pl.DataFrame:
    """Merge raw factors into composite Alpha Sources (DP-002 v3).

    Transforms 16 raw factors → 6 composites:
      LowVol_Composite, Momentum_Composite, Value_Composite,
      Quality_Composite, Volume_Composite, Reversal_Composite

    Each composite = rank-based average of its member factors.
    Missing members are skipped (composite still computed from available).

    Args:
        factor_df: DataFrame with [trade_date, symbol, factor_1, factor_2, ...].
            Must contain at least one member for each composite.

    Returns:
        Same DataFrame with composite columns added.
    """
    from qp.strategy.factor_composite import COMPOSITE_DEFINITIONS

    df = factor_df.clone()

    for comp_name, cfg in COMPOSITE_DEFINITIONS.items():
        members = cfg["members"]
        direction = cfg["direction"]

        # Find available members
        available = [m for m in members if m in df.columns]
        if not available:
            continue

        # Rank each member within cross-section (per date)
        ranked_cols = []
        for m in available:
            rank_col = f"__rank_{m}"
            df = df.with_columns(
                pl.col(m).rank().over("trade_date").alias(rank_col)
            )
            ranked_cols.append(rank_col)

        # Composite = mean of ranks × direction
        if ranked_cols:
            rank_exprs = [pl.col(c) for c in ranked_cols]
            df = df.with_columns(
                (pl.sum_horizontal(rank_exprs) / len(ranked_cols) * direction).alias(comp_name)
            )

            # Cleanup temp columns
            df = df.drop(ranked_cols)

    return df


# Update PRICE_VOLUME_FACTORS to include composites
COMPOSITE_FACTORS: list[str] = [
    "LowVol_Composite",
    "Momentum_Composite",
    "Value_Composite",
    "Quality_Composite",
    "Volume_Composite",
    "Reversal_Composite",
]

ALL_FACTORS_WITH_COMPOSITES: list[str] = PRICE_VOLUME_FACTORS + COMPOSITE_FACTORS
