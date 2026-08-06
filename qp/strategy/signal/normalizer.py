"""SignalNormalizer — normalise raw alpha scores to a unified [0, 1] range.

Per docs/6_Strategy_Engine.md §模块四:
  "Raw Score → Normalize → Clip → Threshold → Confidence → Final Score
   以后所有策略输出都是 0~1，方便融合。"

Supports four normalization methods:
  - min_max: (x - min) / (max - min)
  - z_score: sigmoid(z) = 1 / (1 + exp(-z))
  - rank: rank percentile
  - sigmoid: direct 1 / (1 + exp(-scale * x))

All methods are cross-sectional (per-date / per-batch) unless
global_min/max are provided.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np


class NormMethod(Enum):
    """Normalization method."""

    MIN_MAX = "min_max"
    Z_SCORE = "z_score"
    RANK = "rank"
    SIGMOID = "sigmoid"


@dataclass
class SignalNormalizer:
    """Normalise raw alpha scores cross-sectionally.

    Usage:
        norm = SignalNormalizer(method=NormMethod.RANK)
        scores = norm.normalize(raw_scores)
        # → np.ndarray of floats in [0, 1]

        # With named arrays:
        result = norm.normalize_with_symbols(raw_scores, symbols)

        # With Polars DataFrame:
        df = norm.normalize_polars(df, score_col="raw_score")
    """

    method: NormMethod = NormMethod.RANK
    clip_range: tuple[float, float] = (0.0, 1.0)
    sigmoid_scale: float = 1.0

    # ------------------------------------------------------------------
    # Core normalization
    # ------------------------------------------------------------------

    def normalize(self, scores: np.ndarray) -> np.ndarray:
        """Normalise an array of raw scores to [0, 1].

        Args:
            scores: 1-D array of raw alpha scores.

        Returns:
            1-D array of normalised scores in [0, 1].
        """
        if len(scores) == 0:
            return np.array([], dtype=np.float64)

        scores = np.asarray(scores, dtype=np.float64)

        # Handle NaN
        nan_mask = np.isnan(scores)
        clean = np.where(nan_mask, 0.0, scores)

        if self.method == NormMethod.MIN_MAX:
            result = self._min_max(clean)
        elif self.method == NormMethod.Z_SCORE:
            result = self._z_score(clean)
        elif self.method == NormMethod.RANK:
            result = self._rank(clean)
        elif self.method == NormMethod.SIGMOID:
            result = self._sigmoid(clean)
        else:
            result = clean

        # Clip to [0, 1]
        result = np.clip(result, self.clip_range[0], self.clip_range[1])

        # Restore NaN
        return np.where(nan_mask, 0.0, result)

    # ------------------------------------------------------------------
    # Convenience: with symbols
    # ------------------------------------------------------------------

    def normalize_with_symbols(
        self,
        scores: np.ndarray,
        symbols: list[str],
    ) -> dict[str, float]:
        """Normalise scores and return a {symbol: normalized_score} map.

        Args:
            scores: Raw scores, same length as symbols.
            symbols: Stock codes.

        Returns:
            Dict mapping each symbol to its normalised score.
        """
        normalized = self.normalize(scores)
        return dict(zip(symbols, normalized, strict=True))

    # ------------------------------------------------------------------
    # Convenience: Polars
    # ------------------------------------------------------------------

    def normalize_polars(
        self,
        df: Any,
        score_col: str = "raw_score",
        output_col: str = "alpha_score",
        symbol_col: str = "symbol",
    ) -> Any:
        """Normalise a Polars DataFrame column cross-sectionally.

        Args:
            df: Polars DataFrame.
            score_col: Column with raw scores.
            output_col: Column to write normalised scores to.
            symbol_col: Symbol column (preserved in output).

        Returns:
            DataFrame with original columns + output_col.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(output_col))

        scores = df[score_col].to_numpy()
        normalized = self.normalize(scores)

        return df.with_columns(pl.Series(output_col, normalized))

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    @staticmethod
    def _min_max(scores: np.ndarray) -> np.ndarray:
        """Min-max normalize to [0, 1]."""
        mn = scores.min()
        mx = scores.max()
        if mx - mn < 1e-12:
            return np.full_like(scores, 0.5)
        return (scores - mn) / (mx - mn)

    def _z_score(self, scores: np.ndarray) -> np.ndarray:
        """Z-score → sigmoid to [0, 1]."""
        std = scores.std(ddof=1)
        if std < 1e-12:
            return np.full_like(scores, 0.5)
        z = (scores - scores.mean()) / std
        return 1.0 / (1.0 + np.exp(-self.sigmoid_scale * z))

    @staticmethod
    def _rank(scores: np.ndarray) -> np.ndarray:
        """Rank percentile (0 = worst, 1 = best)."""
        from scipy.stats import rankdata

        n = len(scores)
        if n <= 1:
            return np.full_like(scores, 0.5, dtype=np.float64)
        ranks = rankdata(scores, method="average")
        return (ranks - 1.0) / (n - 1.0)

    def _sigmoid(self, scores: np.ndarray) -> np.ndarray:
        """Direct sigmoid transformation."""
        # Shift to zero-mean first
        shifted = scores - scores.mean()
        return 1.0 / (1.0 + np.exp(-self.sigmoid_scale * shifted))

    # ------------------------------------------------------------------
    # Batch normalization (multi-date)
    # ------------------------------------------------------------------

    def normalize_by_date(
        self,
        df: Any,
        date_col: str = "date",
        score_col: str = "raw_score",
        output_col: str = "alpha_score",
    ) -> Any:
        """Cross-sectional normalize per date group.

        Args:
            df: Polars DataFrame with date_col + score_col.
            date_col: Column identifying trading days.
            score_col: Raw score column.
            output_col: Output column for normalised scores.

        Returns:
            DataFrame with output_col added.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(output_col))

        dates = df[date_col].unique().to_list()
        parts: list[Any] = []

        for d in dates:
            mask = df[date_col] == d
            group = df.filter(mask)
            scores = group[score_col].to_numpy()
            normalized = self.normalize(scores)
            parts.append(group.with_columns(pl.Series(output_col, normalized)))

        if not parts:
            return df

        return pl.concat(parts)
