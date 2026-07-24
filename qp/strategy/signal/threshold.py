"""Signal threshold and clipping — gate signals by quality and magnitude.

Per docs/6_Strategy_Engine.md §模块四:
  "Raw Score → Normalize → Clip → Threshold → Confidence → Final Score"

Two processing stages:
  1. Clipping (SignalClipper): winsorize extreme values, cap outliers
  2. Threshold (SignalThreshold): minimum signal gate, remove weak signals

Usage:
    clipper = SignalClipper(method="winsorize", lower_pct=0.01, upper_pct=0.99)
    clipped = clipper.clip(scores)

    gate = SignalThreshold(min_score=0.3, max_per_day=50)
    passed = gate.filter(signals_df, score_col="alpha_score")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np


class ClipMethod(Enum):
    """Extreme value handling method."""

    WINSORIZE = "winsorize"  # Clip to percentile bounds
    SIGMA = "sigma"  # Clip to mean ± N*std
    ABSOLUTE = "absolute"  # Hard min/max caps


@dataclass
class SignalClipper:
    """Clip extreme signal values to reduce outlier influence.

    Usage:
        clipper = SignalClipper(method="winsorize", lower_pct=0.01, upper_pct=0.99)
        clipped = clipper.clip(scores)
    """

    method: ClipMethod = ClipMethod.WINSORIZE
    lower_pct: float = 0.01  # Winsorize: lower percentile
    upper_pct: float = 0.99  # Winsorize: upper percentile
    sigma_n: float = 3.0  # Sigma: number of std deviations
    min_val: float = 0.0  # Absolute: hard minimum
    max_val: float = 1.0  # Absolute: hard maximum

    # ------------------------------------------------------------------
    # Core clip
    # ------------------------------------------------------------------

    def clip(self, scores: np.ndarray) -> np.ndarray:
        """Clip extreme values in an array.

        Args:
            scores: 1-D array of scores.

        Returns:
            Clipped array (same shape).
        """
        if len(scores) == 0:
            return np.array([], dtype=np.float64)

        scores = np.asarray(scores, dtype=np.float64)

        if self.method == ClipMethod.WINSORIZE:
            return self._winsorize(scores)
        if self.method == ClipMethod.SIGMA:
            return self._sigma_clip(scores)
        if self.method == ClipMethod.ABSOLUTE:
            return self._absolute_clip(scores)
        return scores.copy()

    # ------------------------------------------------------------------
    # Polars
    # ------------------------------------------------------------------

    def clip_polars(
        self,
        df: Any,
        score_col: str = "alpha_score",
        output_col: str = "clipped_score",
    ) -> Any:
        """Clip a score column cross-sectionally.

        Args:
            df: Polars DataFrame.
            score_col: Score column to clip.
            output_col: Output column.

        Returns:
            DataFrame with output_col added.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(output_col))

        scores = df[score_col].to_numpy()
        clipped = self.clip(scores)
        return df.with_columns(pl.Series(output_col, clipped))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _winsorize(self, scores: np.ndarray) -> np.ndarray:
        """Winsorize to percentile bounds."""
        lo = np.percentile(scores, self.lower_pct * 100)
        hi = np.percentile(scores, self.upper_pct * 100)
        return np.clip(scores, lo, hi)

    def _sigma_clip(self, scores: np.ndarray) -> np.ndarray:
        """Clip to mean ± N * std."""
        mu = scores.mean()
        std = scores.std(ddof=1)
        if std < 1e-12:
            return scores.copy()
        lo = mu - self.sigma_n * std
        hi = mu + self.sigma_n * std
        return np.clip(scores, lo, hi)

    def _absolute_clip(self, scores: np.ndarray) -> np.ndarray:
        """Hard min/max caps."""
        return np.clip(scores, self.min_val, self.max_val)


@dataclass
class SignalThreshold:
    """Gate signals by minimum quality and daily count.

    Usage:
        gate = SignalThreshold(min_score=0.3, max_per_day=50, min_confidence=0.5)
        passed = gate.filter(df, score_col="alpha_score")
    """

    min_score: float = 0.3  # Minimum alpha_score to pass
    max_per_day: int = 100  # Max signals per day (take top-N)
    min_confidence: float = 0.0  # Minimum confidence
    keep_top_only: bool = True  # Take top-N or reject all if over max

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def filter(
        self,
        df: Any,
        score_col: str = "alpha_score",
        confidence_col: str = "confidence",
    ) -> Any:
        """Filter signals by threshold and daily count.

        Args:
            df: Polars DataFrame with score_col + optionally confidence_col.
            score_col: Alpha score column.
            confidence_col: Confidence column (if absent, no confidence filter).

        Returns:
            Filtered DataFrame.
        """
        import polars as pl

        if df.is_empty():
            return df

        result = df

        # Minimum score
        result = result.filter(pl.col(score_col) >= self.min_score)

        # Minimum confidence (if column exists)
        if self.min_confidence > 0 and confidence_col in result.columns:
            result = result.filter(pl.col(confidence_col) >= self.min_confidence)

        # Max per day
        if self.max_per_day > 0 and not result.is_empty():
            result = result.sort(score_col, descending=True)
            if result.height > self.max_per_day:
                if self.keep_top_only:
                    result = result.head(self.max_per_day)
                else:
                    return pl.DataFrame(schema=result.columns)

        return result

    # ------------------------------------------------------------------
    # Array-based filter
    # ------------------------------------------------------------------

    def filter_array(
        self,
        scores: np.ndarray,
        symbols: list[str] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Filter a 1-D score array, returning (scores, indices).

        Args:
            scores: Raw alpha scores.
            symbols: Optional stock symbols for tiebreaking.

        Returns:
            (filtered_scores, original_indices) tuple.
        """
        scores = np.asarray(scores, dtype=np.float64)
        n = len(scores)

        # Min score mask
        mask = scores >= self.min_score

        # Max per day: take top-N
        if self.max_per_day > 0 and mask.sum() > self.max_per_day:
            # Get indices of scores above threshold, sorted by score desc
            above_idx = np.where(mask)[0]
            above_scores = scores[above_idx]
            top_n = np.argsort(-above_scores)[: self.max_per_day]
            # Create new mask with only top-N
            new_mask = np.zeros(n, dtype=bool)
            new_mask[above_idx[top_n]] = True
            mask = new_mask

        idx = np.where(mask)[0]
        return scores[idx], idx
