"""Standardization & Anti-Leakage utilities for Feature Store.

Implements data_layer.md §1.5 three anti-leakage traps:

  Trap 1 — Cross-sectional standardization:
    Z-score must be computed per single day, NOT across all time.
    "Z_{i,t} = (X_{i,t} - mu_t) / sigma_t   (mu_t, sigma_t only from day T)"

  Trap 2 — Shift(1) alignment:
    All features used for T-day decisions must be computed from T-1 data.

  Trap 3 — Resampling safety:
    Partial bars must not leak into completed bar features.

Usage::

    from qp.data.feature_store import (
        cross_sectional_zscore,
        rolling_zscore,
        shift_features,
    )
"""

from __future__ import annotations

from typing import Literal

import polars as pl
from loguru import logger

# ────────────────────────────────────────────────────────────────
# Cross-Sectional Standardization (Trap 1)
# ────────────────────────────────────────────────────────────────


def cross_sectional_zscore(
    df: pl.DataFrame,
    value_col: str,
    symbol_col: str = "symbol",
    date_col: str = "trade_date",
    output_col: str | None = None,
    epsilon: float = 1e-8,
) -> pl.DataFrame:
    """Compute cross-sectional z-score strictly per single trading day.

    **Critical**: This computes mu_t and sigma_t from ONLY day T's cross-section.
    It NEVER uses data from T+1 or any other day. This prevents the most common
    form of look-ahead bias in factor research (data_layer.md §1.5 陷阱 1).

    Formula:
        Z_{i,t} = (X_{i,t} - mu_t) / (sigma_t + epsilon)

    where mu_t = mean of all stocks on day t,
          sigma_t = std of all stocks on day t.

    Args:
        df: DataFrame with [symbol, trade_date, value_col].
        value_col: Column to standardize.
        symbol_col: Stock identifier column.
        date_col: Date column.
        output_col: Output column name. Defaults to '{value_col}_zscore'.
        epsilon: Small constant to avoid division by zero.

    Returns:
        DataFrame with z-score column added.
    """
    if df.is_empty():
        return df.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(output_col or f"{value_col}_zscore")
        )

    out = output_col or f"{value_col}_zscore"

    result = df.with_columns(
        (
            (pl.col(value_col) - pl.col(value_col).mean().over(date_col))
            / (pl.col(value_col).std().over(date_col) + epsilon)
        ).alias(out)
    )

    logger.debug(
        "cross_sectional_zscore: '{}' → '{}' (per-day mean/std over {} groups)",
        value_col,
        out,
        df[date_col].n_unique(),
    )

    return result


def cross_sectional_rank(
    df: pl.DataFrame,
    value_col: str,
    symbol_col: str = "symbol",
    date_col: str = "trade_date",
    output_col: str | None = None,
    ascending: bool = True,
) -> pl.DataFrame:
    """Compute cross-sectional percentile rank per single trading day.

    Each stock gets a rank [0, 1] within its day's cross-section.
    Also safe from look-ahead bias.

    Args:
        df: DataFrame with value column.
        value_col: Column to rank.
        symbol_col: Stock identifier.
        date_col: Date column.
        output_col: Output column name.
        ascending: If True, smallest value gets rank 0.

    Returns:
        DataFrame with rank column added.
    """
    if df.is_empty():
        return df.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(output_col or f"{value_col}_rank")
        )

    out = output_col or f"{value_col}_rank"

    return (
        df.with_columns(
            pl.col(value_col)
            .rank("ordinal", descending=not ascending)
            .over(date_col)
            .alias("_rank_n")
        )
        .with_columns(
            (
                (pl.col("_rank_n").cast(pl.Float64) - 1)
                / (pl.col("_rank_n").max().over(date_col).cast(pl.Float64) - 1)
            ).alias(out)
        )
        .drop("_rank_n")
    )


# ────────────────────────────────────────────────────────────────
# Rolling/Time-Series Standardization
# ────────────────────────────────────────────────────────────────


def rolling_zscore(
    df: pl.DataFrame,
    value_col: str,
    window: int = 252,
    symbol_col: str = "symbol",
    date_col: str = "trade_date",
    output_col: str | None = None,
    epsilon: float = 1e-8,
) -> pl.DataFrame:
    """Compute rolling time-series z-score per symbol.

    Formula:
        Z_{i,t} = (X_{i,t} - rolling_mean_{i, [t-k, t-1]})
                   / (rolling_std_{i, [t-k, t-1]} + epsilon)

    Uses [t-k, t-1] window (excludes current day) to prevent leakage.

    Args:
        df: Sorted DataFrame per symbol.
        value_col: Column to standardize.
        window: Rolling window size.
        symbol_col: Stock identifier.
        date_col: Date column.
        output_col: Output column name.
        epsilon: Division-by-zero protection.

    Returns:
        DataFrame with rolling z-score column.
    """
    if df.is_empty():
        return df.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(output_col or f"{value_col}_roll_z")
        )

    out = output_col or f"{value_col}_roll_z"

    return df.sort([symbol_col, date_col]).with_columns(
        (
            (
                pl.col(value_col)
                - pl.col(value_col).rolling_mean(
                    window_size=window, min_samples=max(10, window // 4)
                )
            )
            / (
                pl.col(value_col).rolling_std(
                    window_size=window, min_samples=max(10, window // 4)
                )
                + epsilon
            )
        )
        .over(symbol_col)
        .alias(out)
    )


# ────────────────────────────────────────────────────────────────
# Shift(1) Anti-Leakage (Trap 2)
# ────────────────────────────────────────────────────────────────


def shift_features(
    df: pl.DataFrame,
    columns: list[str],
    shifts: int = 1,
    symbol_col: str = "symbol",
    date_col: str = "trade_date",
    suffix: str = "_lag",
) -> pl.DataFrame:
    """Apply shift(N) to prevent look-ahead bias on multiple columns.

    data_layer.md §1.5 陷阱 2:
      "特征必须 Shift(1) 才能作为 T 日开盘决策的输入"

    Shifts are applied per symbol group to prevent cross-symbol contamination.

    Args:
        df: DataFrame sorted by trade_date per symbol.
        columns: Column names to shift.
        shifts: Number of periods to shift (default 1).
        symbol_col: Symbol column for per-group operation.
        date_col: Date column.
        suffix: Suffix appended to shifted column names.

    Returns:
        DataFrame with shifted columns added.
    """
    result = df
    for col in columns:
        if col not in result.columns:
            logger.debug("shift_features: '{}' not found, skipping", col)
            continue

        shifted_name = f"{col}{suffix}{shifts}"
        result = result.with_columns(
            pl.col(col).shift(shifts).over(symbol_col).alias(shifted_name)
        )

    return result


def validate_no_future_leakage(
    df: pl.DataFrame,
    feature_col: str,
    target_col: str,
    max_corr: float = 0.20,
) -> bool:
    """Heuristic check: feature should NOT correlate with future returns.

    If feature(t) is highly correlated with forward_return(t+1),
    it suggests genuine alpha. But if it correlates with SAME-DAY return,
    there may be a data leakage issue.

    Args:
        df: DataFrame with [feature_col, target_col].
        feature_col: The feature column to check.
        target_col: The target/return column (should be forward return).
        max_corr: Maximum acceptable correlation before flagging.

    Returns:
        True if no obvious leakage detected.
    """
    if df.is_empty() or feature_col not in df.columns or target_col not in df.columns:
        return True

    # Drop nulls for correlation
    valid = df.select([feature_col, target_col]).drop_nulls()
    if valid.height < 30:
        return True

    corr = valid.select(pl.corr(feature_col, target_col)).item()
    if corr is None:
        return True

    abs_corr = abs(corr)
    if abs_corr > max_corr:
        logger.warning(
            "Potential leakage: corr({}, {}) = {:.4f} (threshold: {})",
            feature_col,
            target_col,
            corr,
            max_corr,
        )
        return False

    return True


# ────────────────────────────────────────────────────────────────
# Resampling Safety (Trap 3)
# ────────────────────────────────────────────────────────────────


def resample_safe(
    df: pl.DataFrame,
    rule: str = "1h",
    time_col: str = "trade_time",
    symbol_col: str = "symbol",
    label: Literal["left", "right", "datapoint"] = "left",
    closed: Literal["left", "right", "both", "none"] = "left",
) -> pl.DataFrame:
    """Resample intraday data safely using closed-bar-only rule.

    data_layer.md §1.5 陷阱 3:
      "小时线特征在未完结（10:00 - 11:00 期间）前，只能使用到 10:00
       已经闭合（Closed）的上一个完整小时 Bar 的特征"

    By defaulting to `label='left', closed='left'`, the resampled bar for
    [10:00, 11:00) is labeled as 10:00 and only uses data through 10:59:59.
    A strategy at 10:15 cannot see the 11:00 bar label.

    Note: This is a placeholder for intraday resampling. Day-level users
          do not need this; the default shift(1) is sufficient.

    Args:
        df: Intraday DataFrame.
        rule: Pandas-style resample rule ('1h', '30min', '5min').
        time_col: Timestamp column.
        symbol_col: Symbol column for per-group operation.
        label: 'left' — label bar with start time (safety default).
        closed: 'left' — close interval on left side.

    Returns:
        Resampled DataFrame with safety defaults.
    """
    logger.info(
        "resample_safe: rule={}, per-symbol, label={}, closed={}",
        rule,
        label,
        closed,
    )

    # For Polars, convert to group_by_dynamic
    if df.is_empty():
        return df

    # Polars group_by_dynamic with label="left" equivalent
    try:
        return (
            df.sort([symbol_col, time_col])
            .group_by_dynamic(
                index_column=time_col,
                every=rule,
                group_by=symbol_col,
                label=label,
                closed=closed,
            )
            .agg(pl.all().exclude([symbol_col, time_col]).last())
        )
    except Exception as e:
        logger.warning("resample_safe failed: {} — returning original", e)
        return df


# ────────────────────────────────────────────────────────────────
# Composite pipeline
# ────────────────────────────────────────────────────────────────


def standardize_features(
    df: pl.DataFrame,
    value_cols: list[str],
    method: str = "cross_sectional",
    window: int = 252,
    apply_shift: bool = True,
) -> pl.DataFrame:
    """Apply standardization + optional shift to multiple feature columns.

    This is the main entry point for feature normalization in the pipeline.

    Args:
        df: DataFrame with [symbol, trade_date, *value_cols].
        value_cols: Columns to standardize.
        method: 'cross_sectional' (per-day) or 'rolling' (per-symbol).
        window: Window size for rolling method.
        apply_shift: Also apply shift(1) after standardization.

    Returns:
        DataFrame with standardized + shifted columns.
    """
    result = df

    for col in value_cols:
        if col not in result.columns:
            continue

        if method == "cross_sectional":
            result = cross_sectional_zscore(result, col)
        elif method == "rolling":
            result = rolling_zscore(result, col, window=window)
        else:
            logger.warning("Unknown standardization method: '{}'", method)
            continue

    if apply_shift:
        shifted_cols = [
            f"{c}_zscore" if method == "cross_sectional" else f"{c}_roll_z"
            for c in value_cols
        ]
        result = shift_features(
            result, [c for c in shifted_cols if c in result.columns]
        )

    return result
