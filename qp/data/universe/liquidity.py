"""Liquidity Cutoff — volume-based filtering for Dynamic Universe.

Implements data_layer.md §1.4 Dynamic Universe step 4:
  "流动性/成交量截断"

Filters out stocks that don't meet minimum volume thresholds, ensuring
the universe only contains realistically tradeable stocks.

Strategy:
  1. Compute median daily volume per symbol over a lookback window.
  2. Exclude symbols whose median volume falls below the threshold.
  3. Configurable: absolute threshold (shares) or percentile-based.

Usage::

    from qp.data.universe import compute_median_volume, filter_by_liquidity

    medians = compute_median_volume(df, lookback_days=20)
    liquid_symbols = filter_by_liquidity(df, min_volume=500_000)
"""

from __future__ import annotations

from typing import Any, cast

import polars as pl
from loguru import logger

# Default: 500k shares/day minimum (~CNY 5M at 10/share)
_DEFAULT_MIN_VOLUME = 500_000
_DEFAULT_LOOKBACK = 20  # trading days


# ------------------------------------------------------------------
# Volume computation
# ------------------------------------------------------------------


def compute_median_volume(
    df: pl.DataFrame,
    symbol_col: str = "symbol",
    volume_col: str = "volume",
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> pl.DataFrame:
    """Compute median daily volume per symbol over a lookback window.

    Args:
        df: OHLCV DataFrame with symbol and volume columns.
        symbol_col: Column name for stock identifier.
        volume_col: Column name for volume.
        lookback_days: Number of most recent trading days to use.

    Returns:
        Polars DataFrame with [symbol, median_volume].
    """
    if df.is_empty():
        return pl.DataFrame(schema={symbol_col: pl.Utf8, "median_volume": pl.Float64})

    # Get the most recent N trading days
    if "trade_date" in df.columns:
        dates = df["trade_date"].unique().sort(descending=True).head(lookback_days)
        recent = df.filter(pl.col("trade_date").is_in(pl.Series(dates)))
    else:
        recent = df

    # Compute median volume per symbol
    result = (
        recent.group_by(symbol_col)
        .agg(pl.col(volume_col).median().alias("median_volume"))
        .sort("median_volume", descending=True)
    )

    return result


def compute_avg_volume(
    df: pl.DataFrame,
    symbol_col: str = "symbol",
    volume_col: str = "volume",
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> pl.DataFrame:
    """Compute average daily volume per symbol over a lookback window.

    Alternative to median — median is more robust to outliers.
    """
    if df.is_empty():
        return pl.DataFrame(schema={symbol_col: pl.Utf8, "avg_volume": pl.Float64})

    if "trade_date" in df.columns:
        dates = df["trade_date"].unique().sort(descending=True).head(lookback_days)
        recent = df.filter(pl.col("trade_date").is_in(pl.Series(dates)))
    else:
        recent = df

    return (
        recent.group_by(symbol_col)
        .agg(pl.col(volume_col).mean().alias("avg_volume"))
        .sort("avg_volume", descending=True)
    )


# ------------------------------------------------------------------
# Liquidity filtering
# ------------------------------------------------------------------


def filter_by_liquidity(
    df: pl.DataFrame,
    min_volume: float = _DEFAULT_MIN_VOLUME,
    symbol_col: str = "symbol",
    volume_col: str = "volume",
    lookback_days: int = _DEFAULT_LOOKBACK,
    use_median: bool = True,
) -> list[str]:
    """Filter symbols by minimum volume threshold.

    Returns the list of symbols that pass the liquidity cutoff.

    Args:
        df: OHLCV DataFrame.
        min_volume: Minimum volume threshold (shares).
        symbol_col: Column name for stock identifier.
        volume_col: Column name for volume.
        lookback_days: Lookback window for volume calculation.
        use_median: Use median (True) or average (False).

    Returns:
        List of liquid symbols (sorted by volume descending).
    """
    if df.is_empty():
        return []

    if use_median:
        vol_df = compute_median_volume(df, symbol_col, volume_col, lookback_days)
        vol_col = "median_volume"
    else:
        vol_df = compute_avg_volume(df, symbol_col, volume_col, lookback_days)
        vol_col = "avg_volume"

    liquid = vol_df.filter(pl.col(vol_col) >= min_volume)
    excluded_count = vol_df.height - liquid.height

    if excluded_count > 0:
        excluded_syms = vol_df.filter(pl.col(vol_col) < min_volume)[symbol_col].to_list()
        logger.info(
            "流动性筛选: {} 只排除 (<{} 股/日, {}日{})",
            excluded_count,
            int(min_volume),
            lookback_days,
            "中位数" if use_median else "均值",
        )
        logger.debug("  排除: {}", excluded_syms[:10])

    return liquid[symbol_col].to_list()


def filter_by_percentile(
    df: pl.DataFrame,
    min_percentile: float = 20.0,
    symbol_col: str = "symbol",
    volume_col: str = "volume",
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> list[str]:
    """Filter symbols by volume percentile (keep top N%).

    Excludes the bottom `min_percentile`% of stocks by volume.
    E.g. min_percentile=20 keeps the top 80%.

    Args:
        df: OHLCV DataFrame.
        min_percentile: Exclude symbols below this percentile (0-100).
        symbol_col: Column name for stock identifier.
        volume_col: Column name for volume.
        lookback_days: Lookback window.

    Returns:
        List of liquid symbols.
    """
    if df.is_empty():
        return []

    vol_df = compute_median_volume(df, symbol_col, volume_col, lookback_days)
    if vol_df.height == 0:
        return []

    threshold = vol_df["median_volume"].quantile(min_percentile / 100.0)
    liquid = vol_df.filter(pl.col("median_volume") >= threshold)

    excluded_count = vol_df.height - liquid.height
    logger.info(
        "流动性筛选(百分位): {} 只排除 (P{}={:.0f}股), {} 只保留",
        excluded_count,
        int(min_percentile),
        threshold or 0,
        liquid.height,
    )

    return liquid[symbol_col].to_list()


def get_liquidity_stats(
    df: pl.DataFrame,
    symbol_col: str = "symbol",
    volume_col: str = "volume",
    lookback_days: int = _DEFAULT_LOOKBACK,
) -> dict[str, Any]:
    """Get descriptive statistics for volume distribution.

    Returns:
        Dict with count, mean, median, std, p10, p25, p75, p90.
    """
    vol_df = compute_median_volume(df, symbol_col, volume_col, lookback_days)
    if vol_df.is_empty():
        return {}

    vals = vol_df["median_volume"]
    return {
        "count": vals.len(),
        "mean": round(cast("float", vals.mean() or 0), 0),
        "median": round(cast("float", vals.median() or 0), 0),
        "std": round(cast("float", vals.std() or 0), 0),
        "p10": round(vals.quantile(0.10) or 0, 0),
        "p25": round(vals.quantile(0.25) or 0, 0),
        "p75": round(vals.quantile(0.75) or 0, 0),
        "p90": round(vals.quantile(0.90) or 0, 0),
    }
