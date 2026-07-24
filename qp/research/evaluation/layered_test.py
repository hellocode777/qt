"""Layered (quantile) backtest — monotonicity and spread validation.

Computes forward returns for each factor quantile group and validates:
  - Monotonicity: higher-factor quantile → higher forward return
  - Top-Bottom spread: statistically significant difference
  - Monotonicity t-stat ≥ 2.0 (rule.md §10.1)

This is the core validation that a factor has real predictive power
beyond just a favorable IC (which can be driven by a few outliers).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl


@dataclass
class LayeredTestResult:
    """Result of a quantile-based factor evaluation."""

    n_quantiles: int
    quantile_returns: dict[int, float]  # quantile → mean forward return
    quantile_counts: dict[int, int]
    top_bottom_spread: float  # Q_top - Q_bottom mean return
    spread_t_stat: float  # t-stat of spread significance
    monotonicity_t_stat: float  # regression of returns on quantile rank
    is_monotonic: bool  # monotonicity_t_stat ≥ 2.0
    n_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_quantiles": self.n_quantiles,
            "quantile_returns": self.quantile_returns,
            "quantile_counts": self.quantile_counts,
            "top_bottom_spread": self.top_bottom_spread,
            "spread_t_stat": self.spread_t_stat,
            "monotonicity_t_stat": self.monotonicity_t_stat,
            "is_monotonic": self.is_monotonic,
            "n_days": self.n_days,
        }

    def summary(self) -> str:
        status = "✅" if self.is_monotonic else "❌"
        return (
            f"{status} Q{self.n_quantiles}-Q1 spread={self.top_bottom_spread:+.4f} "
            f"| t_spread={self.spread_t_stat:.2f} | t_mono={self.monotonicity_t_stat:.2f} "
            f"| N={self.n_days}d"
        )


def compute_layered_returns(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    n_quantiles: int = 5,
    forward_days: int = 5,
    min_stocks_per_day: int = 50,
) -> LayeredTestResult:
    """Compute forward returns for each factor quantile group.

    On each date:
      1. Rank stocks by factor score
      2. Assign to n_quantiles equal-sized groups
      3. Compute mean forward return per group
      4. Accumulate across dates

    Args:
        score_df: [trade_date, symbol, score].
        price_df: [trade_date, symbol, close].
        n_quantiles: Number of quantile groups (default 5).
        forward_days: Forward return horizon.
        min_stocks_per_day: Skip dates with fewer stocks.

    Returns:
        LayeredTestResult with quantile-level statistics.
    """
    # Compute forward returns
    px = price_df.sort(["symbol", "trade_date"])
    px = px.with_columns(
        (pl.col("close").shift(-forward_days).over("symbol") / pl.col("close") - 1).alias(
            "forward_return"
        )
    )
    px = px.drop_nulls(subset=["forward_return"])

    # Join
    score_df = score_df.with_columns(pl.col("trade_date").cast(pl.Utf8))
    px = px.with_columns(pl.col("trade_date").cast(pl.Utf8))

    merged = score_df.join(
        px.select(["trade_date", "symbol", "forward_return"]),
        on=["trade_date", "symbol"],
        how="inner",
    )
    if merged.is_empty():
        return LayeredTestResult(
            n_quantiles=n_quantiles,
            quantile_returns={},
            quantile_counts={},
            top_bottom_spread=0.0,
            spread_t_stat=0.0,
            monotonicity_t_stat=0.0,
            is_monotonic=False,
            n_days=0,
        )

    dates = sorted(merged["trade_date"].unique().to_list())

    # Accumulate returns per quantile across dates
    quantile_daily_rets: dict[int, list[float]] = {q: [] for q in range(1, n_quantiles + 1)}
    quantile_total_count: dict[int, int] = dict.fromkeys(range(1, n_quantiles + 1), 0)

    for d in dates:
        day_data = merged.filter(pl.col("trade_date") == d)
        n = day_data.height
        if n < min_stocks_per_day:
            continue

        # Rank by score (higher score = better)
        day_data = day_data.sort("score", descending=True)

        # Assign quantiles (equal-sized groups)
        rets_arr = day_data["forward_return"].to_numpy()
        quantile_edges = np.linspace(0, n, n_quantiles + 1, dtype=int)

        for q in range(1, n_quantiles + 1):
            start = quantile_edges[q - 1]
            end = quantile_edges[q]
            if start < end:
                q_ret = float(np.mean(rets_arr[start:end]))
                quantile_daily_rets[q].append(q_ret)
                quantile_total_count[q] += end - start

    # Compute statistics
    quantile_returns: dict[int, float] = {}
    for q in range(1, n_quantiles + 1):
        rets = quantile_daily_rets[q]
        if rets:
            quantile_returns[q] = round(float(np.mean(rets)), 6)
        else:
            quantile_returns[q] = 0.0

    n_days = max(len(quantile_daily_rets.get(1, [])), 0)

    # Top-bottom spread
    top_ret = quantile_returns.get(n_quantiles, 0.0)
    bottom_ret = quantile_returns.get(1, 0.0)
    spread = top_ret - bottom_ret

    # t-stat of spread: paired t-test (same dates, top vs bottom)
    top_daily = np.array(quantile_daily_rets.get(n_quantiles, []))
    bottom_daily = np.array(quantile_daily_rets.get(1, []))
    min_len = min(len(top_daily), len(bottom_daily))
    if min_len > 1:
        spread_daily = top_daily[:min_len] - bottom_daily[:min_len]
        spread_mean = float(np.mean(spread_daily))
        spread_std = float(np.std(spread_daily, ddof=1))
        spread_t = abs(spread_mean) / (spread_std / np.sqrt(min_len)) if spread_std > 0 else 0.0
    else:
        spread_t = 0.0

    # Monotonicity: regress quantile mean returns on quantile rank
    q_ranks = np.array(list(range(1, n_quantiles + 1)))
    q_rets = np.array([quantile_returns[q] for q in range(1, n_quantiles + 1)])
    if n_quantiles >= 3 and np.std(q_rets) > 0:
        # Simple OLS slope t-stat
        X = np.column_stack([np.ones(n_quantiles), q_ranks])
        try:
            beta = np.linalg.lstsq(X, q_rets, rcond=None)[0]
            residuals = q_rets - X @ beta
            se = np.sqrt(np.sum(residuals**2) / (n_quantiles - 2))
            se_beta = se / np.sqrt(np.sum((q_ranks - q_ranks.mean()) ** 2))
            mono_t = abs(beta[1]) / se_beta if se_beta > 0 else 0.0
        except np.linalg.LinAlgError:
            mono_t = 0.0
    else:
        mono_t = 0.0

    return LayeredTestResult(
        n_quantiles=n_quantiles,
        quantile_returns=quantile_returns,
        quantile_counts=quantile_total_count,
        top_bottom_spread=round(spread, 6),
        spread_t_stat=round(spread_t, 2),
        monotonicity_t_stat=round(mono_t, 2),
        is_monotonic=mono_t >= 2.0,
        n_days=n_days,
    )


def compute_quantile_spread_series(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    n_quantiles: int = 5,
    forward_days: int = 5,
    min_stocks_per_day: int = 50,
) -> pl.DataFrame:
    """Compute daily top-bottom quantile spread series.

    Useful for time-series analysis of factor performance stability.

    Args:
        score_df: [trade_date, symbol, score].
        price_df: [trade_date, symbol, close].
        n_quantiles: Number of quantile groups.
        forward_days: Forward return horizon.
        min_stocks_per_day: Minimum stocks per day.

    Returns:
        [trade_date, Q1_return, QN_return, spread] per date.
    """
    px = price_df.sort(["symbol", "trade_date"])
    px = px.with_columns(
        (pl.col("close").shift(-forward_days).over("symbol") / pl.col("close") - 1).alias(
            "forward_return"
        )
    )
    px = px.drop_nulls(subset=["forward_return"])

    score_df = score_df.with_columns(pl.col("trade_date").cast(pl.Utf8))
    px = px.with_columns(pl.col("trade_date").cast(pl.Utf8))

    merged = score_df.join(
        px.select(["trade_date", "symbol", "forward_return"]),
        on=["trade_date", "symbol"],
        how="inner",
    )

    dates = sorted(merged["trade_date"].unique().to_list())
    rows: list[dict[str, Any]] = []

    for d in dates:
        day_data = merged.filter(pl.col("trade_date") == d)
        n = day_data.height
        if n < min_stocks_per_day:
            continue

        day_data = day_data.sort("score", descending=True)
        rets = day_data["forward_return"].to_numpy()
        quantile_edges = np.linspace(0, n, n_quantiles + 1, dtype=int)

        q1_ret = float(np.mean(rets[quantile_edges[0] : quantile_edges[1]]))
        qn_ret = float(np.mean(rets[quantile_edges[-2] : quantile_edges[-1]]))

        rows.append(
            {
                "trade_date": d,
                "q1_return": q1_ret,
                f"q{n_quantiles}_return": qn_ret,
                "spread": qn_ret - q1_ret,
                "n_stocks": n,
            }
        )

    if not rows:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Utf8,
                "q1_return": pl.Float64,
                f"q{n_quantiles}_return": pl.Float64,
                "spread": pl.Float64,
                "n_stocks": pl.Int64,
            }
        )

    return pl.DataFrame(rows).sort("trade_date")
