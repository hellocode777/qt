"""ConfidenceScorer — estimate per-signal confidence for quality gating.

Per docs/6_Strategy_Engine.md §模块四:
  "Confidence: 信号置信度/有效度"

Confidence is estimated from:
  1. IC stability: higher rolling IC_IR → higher confidence
  2. Signal dispersion: higher cross-sectional std → more informative
  3. Coverage quality: too few or too many signals → lower confidence
  4. Score magnitude: extreme scores are more trustworthy than middling ones

Usage:
    scorer = ConfidenceScorer()
    signals_with_conf = scorer.score(df, score_col="alpha_score")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class ConfidenceScorer:
    """Compute per-signal confidence scores.

    Confidence is a value in [0, 1] representing how trustworthy
    each signal is. It combines multiple sub-scores:

      confidence = w1 * score_magnitude + w2 * dispersion + w3 * coverage

    Where:
      - score_magnitude: how extreme the score is (far from 0.5)
      - dispersion: how well-separated the cross-section is
      - coverage: whether the universe size is reasonable

    Attributes:
        magnitude_weight: Weight for score extremity.
        dispersion_weight: Weight for cross-sectional dispersion.
        coverage_weight: Weight for universe coverage quality.
        ideal_coverage: Ideal number of stocks in universe.
    """

    magnitude_weight: float = 0.3
    dispersion_weight: float = 0.4
    coverage_weight: float = 0.3
    ideal_coverage: int = 300  # ~沪深300 size

    # ------------------------------------------------------------------
    # Array-based scoring
    # ------------------------------------------------------------------

    def score_array(self, scores: np.ndarray) -> np.ndarray:
        """Compute confidence for each signal in a cross-section.

        Args:
            scores: 1-D array of alpha scores (assumed [0, 1]).

        Returns:
            Confidence scores, same shape, in [0, 1].
        """
        if len(scores) == 0:
            return np.array([], dtype=np.float64)

        scores = np.asarray(scores, dtype=np.float64)
        n = len(scores)

        # 1. Score magnitude: distance from 0.5 (mild scores are uncertain)
        magnitude = 2.0 * np.abs(scores - 0.5)  # [0, 1]

        # 2. Cross-sectional dispersion (same for all signals in a batch)
        std = float(np.std(scores, ddof=1))
        # Dispersion of ~0.15 is "good" (typical cross-sectional std)
        dispersion_raw = min(std / 0.15, 1.0)

        # 3. Coverage quality (same for all)
        coverage_ratio = n / max(self.ideal_coverage, 1)
        if coverage_ratio < 0.05:
            coverage = 0.1   # Too few stocks
        elif coverage_ratio > 5.0:
            coverage = 0.7   # Very large universe — diluted
        else:
            # Bell-shaped: optimal around 1.0
            coverage = max(0.3, 1.0 - abs(coverage_ratio - 1.0) * 0.5)

        # Combine
        confidence = (
            self.magnitude_weight * magnitude
            + self.dispersion_weight * dispersion_raw
            + self.coverage_weight * coverage
        )

        return np.clip(confidence, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Historical IC-based confidence
    # ------------------------------------------------------------------

    def score_from_ic(
        self,
        scores: np.ndarray,
        ic_series: np.ndarray | None = None,
    ) -> np.ndarray:
        """Compute confidence using historical IC stability.

        Args:
            scores: Current cross-section of alpha scores.
            ic_series: Historical IC values (optional). If provided,
                       IC_IR is used as an additional factor.

        Returns:
            Confidence scores in [0, 1].
        """
        base = self.score_array(scores)

        if ic_series is None or len(ic_series) == 0:
            return base

        ic = np.asarray(ic_series, dtype=np.float64)
        ic_mean = float(ic.mean())
        ic_std = float(ic.std(ddof=1))
        ic_ir = abs(ic_mean) / ic_std if ic_std > 0 else 0.0

        # IC_IR >= 0.5 is "good"
        ic_factor = min(ic_ir / 0.5, 1.0)

        # Blend: 70% base + 30% IC factor
        confidence = 0.7 * base + 0.3 * ic_factor
        return np.clip(confidence, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Polars
    # ------------------------------------------------------------------

    def score_polars(
        self,
        df: Any,
        score_col: str = "alpha_score",
        output_col: str = "confidence",
    ) -> Any:
        """Add confidence scores to a Polars DataFrame.

        Args:
            df: Polars DataFrame with score_col.
            score_col: Alpha score column.
            output_col: Output column for confidence.

        Returns:
            DataFrame with output_col added.
        """
        import polars as pl

        if df.is_empty():
            return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(output_col))

        scores = df[score_col].to_numpy()
        conf = self.score_array(scores)
        return df.with_columns(pl.Series(output_col, conf))

    # ------------------------------------------------------------------
    # Batch per-date
    # ------------------------------------------------------------------

    def score_by_date(
        self,
        df: Any,
        date_col: str = "date",
        score_col: str = "alpha_score",
        output_col: str = "confidence",
        ic_series: np.ndarray | None = None,
    ) -> Any:
        """Compute confidence per trading day.

        Args:
            df: Polars DataFrame with date and score columns.
            date_col: Date column.
            score_col: Score column.
            output_col: Output column.
            ic_series: Optional historical IC for IC-based blending.

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
            if ic_series is not None and len(ic_series) > 0:
                conf = self.score_from_ic(scores, ic_series)
            else:
                conf = self.score_array(scores)
            parts.append(group.with_columns(pl.Series(output_col, conf)))

        if not parts:
            return df

        return pl.concat(parts)
