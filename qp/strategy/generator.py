"""SignalGenerator — unified Feature → Model → Score orchestrator.

Per docs/6_Strategy_Engine.md §模块三:
  "这是每个 Strategy 自己负责的部分：Feature → Model → Raw Score"

The SignalGenerator provides a standardized pipeline that any strategy
can delegate to. It wraps the three-step process:
  1. Feature computation (delegated to research/feature)
  2. Model inference (delegated to research/model)
  3. Score post-processing (via strategy/signal/*)

Usage:
    from qp.strategy.generator import SignalGenerator, GeneratorConfig

    config = GeneratorConfig(
        model_name="lgb_rank_v3",
        normalizer=SignalNormalizer(method=NormMethod.RANK),
        smoother=SignalSmoother(method=SmoothMethod.EMA, halflife=5),
    )
    gen = SignalGenerator(config)
    signals = gen.generate(features_df, as_of_date=today_cn())
    # → Polars DataFrame [symbol, raw_score, rank, confidence]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from qp.strategy.signal.confidence import ConfidenceScorer
from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer
from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod
from qp.strategy.signal.threshold import SignalClipper, SignalThreshold


@dataclass
class GeneratorConfig:
    """Configuration for SignalGenerator.

    Attributes:
        model_name: Name of the ML model for inference.
        model: Optional pre-loaded model instance.
        normalizer: Signal normalizer (default: rank percentile).
        smoother: Signal smoother (default: EMA halflife=5).
        clipper: Signal clipper (optional).
        threshold: Signal threshold gate (optional).
        confidence_scorer: Confidence scorer (optional).
        score_col: Name of the raw score column from model output.
        top_n: Maximum number of signals to return.
        min_score: Minimum alpha score threshold.
    """

    model_name: str = ""
    model: Any = None
    normalizer: SignalNormalizer | None = None
    smoother: SignalSmoother | None = None
    clipper: SignalClipper | None = None
    threshold: SignalThreshold | None = None
    confidence_scorer: ConfidenceScorer | None = None
    score_col: str = "raw_score"
    top_n: int = 100
    min_score: float = 0.0


@dataclass
class SignalGenerator:
    """Standardized Feature → Model → Score pipeline.

    Encapsulates the full signal generation chain so that concrete
    strategies (Momentum, Value, Quality) only need to provide:
      - Feature computation
      - Model (optional; can use rule-based scoring)

    The generator handles:
      - Normalization → Clipping → Smoothing → Threshold → Confidence

    Usage:
        gen = SignalGenerator(GeneratorConfig(model_name="lgb_rank_v3"))
        scores = gen.generate(features_df, as_of_date=today_cn())
    """

    config: GeneratorConfig = field(default_factory=GeneratorConfig)

    def __post_init__(self) -> None:
        if self.config.normalizer is None:
            self.config.normalizer = SignalNormalizer(method=NormMethod.RANK)
        if self.config.smoother is None:
            self.config.smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=5)
        if self.config.confidence_scorer is None:
            self.config.confidence_scorer = ConfidenceScorer()

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def generate(
        self,
        features: pl.DataFrame | None = None,
        *,
        as_of_date: date | None = None,
        scores: pl.DataFrame | None = None,
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        """Run the full signal generation pipeline.

        Args:
            features: Feature DataFrame (if model inference needed).
            as_of_date: Reference date (PIT).
            scores: Pre-computed raw scores (bypasses model inference).
            symbols: Symbol list for output construction.

        Returns:
            Polars DataFrame [symbol, raw_score, alpha_score, rank, confidence].
        """
        # Step 1: Model inference (if scores not provided)
        if scores is None and features is not None:
            scores = self._infer(features)
        elif scores is None:
            return pl.DataFrame(
                schema={
                    "symbol": pl.Utf8,
                    "raw_score": pl.Float64,
                    "alpha_score": pl.Float64,
                    "rank": pl.Int64,
                    "confidence": pl.Float64,
                }
            )

        if scores.is_empty():
            return scores

        # Step 2: Post-processing chain
        score_col = self.config.score_col

        # Determine score column in input
        actual_col = score_col
        if actual_col not in scores.columns:
            for c in ["raw_score", "feature_value", "score"]:
                if c in scores.columns:
                    actual_col = c
                    break

        # Normalize
        norm = self.config.normalizer
        if norm is None:
            norm = SignalNormalizer(method=NormMethod.RANK)
        out: pl.DataFrame = norm.normalize_polars(
            scores, score_col=actual_col, output_col="alpha_score"
        )

        # Clip
        if self.config.clipper:
            out = self.config.clipper.clip_polars(
                out, score_col="alpha_score", output_col="alpha_score"
            )

        # Smooth (per symbol across time if date column exists)
        if self.config.smoother and "date" in out.columns:
            out = self.config.smoother.smooth_polars(
                out, score_col="alpha_score", output_col="alpha_score"
            )

        # Threshold
        if self.config.threshold:
            out = self.config.threshold.filter(out, score_col="alpha_score")

        # Confidence
        if self.config.confidence_scorer:
            out = self.config.confidence_scorer.score_polars(
                out, score_col="alpha_score", output_col="confidence"
            )

        # Rank and sort
        if not out.is_empty():
            out = out.sort("alpha_score", descending=True)
            out = out.with_columns(
                pl.col("alpha_score").rank(descending=True).cast(pl.Int64).alias("rank")
            )
            if self.config.top_n > 0:
                out = out.head(self.config.top_n)

        # Min score filter
        if self.config.min_score > 0 and not out.is_empty():
            out = out.filter(pl.col("alpha_score") >= self.config.min_score)

        return out

    # ------------------------------------------------------------------
    # Generate with raw array
    # ------------------------------------------------------------------

    def generate_from_array(
        self,
        raw_scores: np.ndarray,
        symbols: list[str],
        *,
        as_of_date: date | None = None,
    ) -> pl.DataFrame:
        """Generate signals from a raw numpy score array.

        Convenience wrapper for strategies that produce scores
        outside of Polars (e.g., rule-based scoring).

        Args:
            raw_scores: 1-D array of raw alpha scores.
            symbols: Stock codes (same length).
            as_of_date: Reference date.

        Returns:
            Polars DataFrame [symbol, raw_score, alpha_score, rank, confidence].
        """
        if len(raw_scores) == 0 or len(symbols) == 0:
            return pl.DataFrame()

        date_str = as_of_date.isoformat() if as_of_date else ""

        df = pl.DataFrame(
            {
                "symbol": symbols,
                self.config.score_col: raw_scores,
            }
        )
        if date_str:
            df = df.with_columns(pl.lit(date_str).alias("date"))

        return self.generate(scores=df)

    # ------------------------------------------------------------------
    # Model inference
    # ------------------------------------------------------------------

    def _infer(self, features: pl.DataFrame) -> pl.DataFrame:
        """Run model inference on features.

        If a model is configured, delegates to model.predict().
        Otherwise, uses the last numeric column as raw scores.
        """
        model = self.config.model

        # Delegate to model when available
        if model is not None and hasattr(model, "predict"):
            raw = model.predict(features)
            if isinstance(raw, np.ndarray):
                feat_cols = [c for c in features.columns if c != "symbol"]
                symbol_col = "symbol" if "symbol" in features.columns else feat_cols[0]
                return pl.DataFrame(
                    {
                        "symbol": features[symbol_col].to_list(),
                        self.config.score_col: raw.tolist(),
                    }
                )

        # No model — use last numeric column as score
        numeric_cols = [
            c
            for c in features.columns
            if c != "symbol" and features[c].dtype in (pl.Float64, pl.Float32, pl.Int64)
        ]
        if numeric_cols:
            score_col = numeric_cols[-1]
            return features.select(
                [
                    pl.col("symbol")
                    if "symbol" in features.columns
                    else pl.lit("").alias("symbol"),
                    pl.col(score_col).alias(self.config.score_col),
                ]
            )

        return features
