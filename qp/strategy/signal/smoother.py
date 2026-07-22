"""SignalSmoother — reduce signal noise and turnover via temporal smoothing.

Per docs/6_Strategy_Engine.md 补充 §1:
  "Post-Processing 里加上 Smoother（比如指数移动平均 EMA 或近 N 天
   衰减）是极明智的做法，能极大地降低后续 Layer 7/8 的换手率
   （Turnover Cost）。"

Smoothing methods:
  - EMA: Exponential moving average (most common)
  - ROLLING_MEAN: Simple N-day rolling average
  - DECAY: Linear decay blend (current * alpha + previous * (1-alpha))
  - KALMAN: Placeholder for future Kalman filter

Usage:
    smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=5)
    smoothed = smoother.smooth(df, score_col="raw_score", date_col="date")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np


class SmoothMethod(Enum):
    """Temporal smoothing method."""

    EMA = "ema"            # Exponential moving average
    ROLLING_MEAN = "rolling_mean"  # Simple rolling average
    DECAY = "decay"        # Linear decay blend
    KALMAN = "kalman"      # Kalman filter (placeholder)


@dataclass
class SignalSmoother:
    """Apply temporal smoothing to alpha signals.

    Smooths each stock's signal series independently over time.
    Reduces signal turnover by dampening day-to-day noise.

    Attributes:
        method: Smoothing method.
        halflife: EMA halflife in days (used by EMA method).
        window: Rolling window size in days (used by ROLLING_MEAN method).
        alpha: Decay weight for current value (used by DECAY method).
            score_today = alpha * raw + (1-alpha) * score_yesterday.
    """

    method: SmoothMethod = SmoothMethod.EMA
    halflife: int = 5
    window: int = 5
    alpha: float = 0.3

    # ------------------------------------------------------------------
    # Core smoothing
    # ------------------------------------------------------------------

    def smooth_array(self, values: np.ndarray) -> np.ndarray:
        """Smooth a 1-D time series.

        Args:
            values: Raw signal values over time (oldest first).

        Returns:
            Smoothed values, same length.
        """
        if len(values) == 0:
            return np.array([], dtype=np.float64)

        values = np.asarray(values, dtype=np.float64)

        if self.method == SmoothMethod.EMA:
            return self._ema(values)
        if self.method == SmoothMethod.ROLLING_MEAN:
            return self._rolling_mean(values)
        if self.method == SmoothMethod.DECAY:
            return self._decay(values)
        # KALMAN — not implemented yet, return raw
        return values.copy()

    # ------------------------------------------------------------------
    # Polars: smooth by stock across dates
    # ------------------------------------------------------------------

    def smooth_polars(
        self,
        df: Any,
        score_col: str = "raw_score",
        symbol_col: str = "symbol",
        date_col: str = "date",
        output_col: str = "smoothed_score",
    ) -> Any:
        """Smooth each stock's signal series independently across dates.

        Args:
            df: Polars DataFrame with date_col + symbol_col + score_col.
            score_col: Raw score column.
            symbol_col: Stock identifier column.
            date_col: Date column (sorted per symbol).
            output_col: Output column for smoothed scores.

        Returns:
            DataFrame with output_col added.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(output_col))

        # Sort by symbol, then date
        df = df.sort([symbol_col, date_col])

        symbols = df[symbol_col].unique().to_list()
        parts: list[Any] = []

        for sym in symbols:
            sym_df = df.filter(pl.col(symbol_col) == sym).sort(date_col)
            values = sym_df[score_col].to_numpy()
            smoothed = self.smooth_array(values)
            parts.append(sym_df.with_columns(pl.Series(output_col, smoothed)))

        if not parts:
            return df

        return pl.concat(parts)

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _ema(self, values: np.ndarray) -> np.ndarray:
        """Exponential moving average with configurable halflife.

        Span = 2 * halflife, alpha = 2 / (span + 1).
        """
        n = len(values)
        result = np.empty(n, dtype=np.float64)
        if n == 0:
            return result

        span = 2 * self.halflife
        alpha = 2.0 / (span + 1.0)

        # Seed with first value
        result[0] = values[0]
        for i in range(1, n):
            if np.isnan(values[i]):
                result[i] = result[i - 1]
            else:
                result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]

        return result

    def _rolling_mean(self, values: np.ndarray) -> np.ndarray:
        """Simple N-day rolling mean (backward-looking, PIT-safe)."""
        n = len(values)
        result = np.empty(n, dtype=np.float64)
        window = min(self.window, n)

        for i in range(n):
            start = max(0, i - window + 1)
            win = values[start : i + 1]
            win_clean = win[~np.isnan(win)]
            if len(win_clean) == 0:
                result[i] = values[i] if not np.isnan(values[i]) else 0.0
            else:
                result[i] = float(win_clean.mean())

        return result

    def _decay(self, values: np.ndarray) -> np.ndarray:
        """Linear decay blend: current * alpha + previous * (1-alpha)."""
        n = len(values)
        result = np.empty(n, dtype=np.float64)
        if n == 0:
            return result

        result[0] = values[0] if not np.isnan(values[0]) else 0.0
        for i in range(1, n):
            if np.isnan(values[i]):
                result[i] = result[i - 1]
            else:
                result[i] = self.alpha * values[i] + (1 - self.alpha) * result[i - 1]

        return result

    # ------------------------------------------------------------------
    # Batch: smooth entire score matrix
    # ------------------------------------------------------------------

    def smooth_cross_sectional(
        self,
        scores_by_date: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Smooth per-stock scores across dates.

        Args:
            scores_by_date: {date_str: {symbol: raw_score}} — dates sorted.

        Returns:
            {date_str: {symbol: smoothed_score}}.
        """
        dates = sorted(scores_by_date.keys())
        if not dates:
            return {}

        # Collect all symbols
        all_symbols: set[str] = set()
        for d in dates:
            all_symbols.update(scores_by_date[d].keys())

        # Build series per symbol
        symbol_series: dict[str, list[float]] = {s: [] for s in all_symbols}
        for d in dates:
            day_scores = scores_by_date[d]
            for sym in all_symbols:
                symbol_series[sym].append(day_scores.get(sym, np.nan))

        # Smooth each symbol
        smoothed_series: dict[str, np.ndarray] = {}
        for sym in all_symbols:
            arr = np.array(symbol_series[sym], dtype=np.float64)
            smoothed_series[sym] = self.smooth_array(arr)

        # Rebuild dict
        result: dict[str, dict[str, float]] = {}
        for i, d in enumerate(dates):
            result[d] = {}
            for sym in all_symbols:
                val = float(smoothed_series[sym][i])
                if not np.isnan(val):
                    result[d][sym] = val

        return result
