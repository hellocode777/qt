"""EnsembleEngine — multi-strategy fusion with dynamic weighting.

Per docs/6_Strategy_Engine.md §模块五:
  "输入多个策略 → 融合 → Final Score = w1*S1 + w2*S2 + w3*S3"

The EnsembleEngine orchestrates:
  1. Weight allocation (fixed / IC / Sharpe / regime)
  2. Universe alignment (cross-section consistency)
  3. Signal fusion (rank_blend / equal_weight / vote via SignalAggregator)
  4. Output as AlphaSignalBatch

Cross-Section Universe Alignment (per docs 补充 §1):
  "策略 A 可能是针对全 A 股（5000只），策略 B 可能只针对沪深300（300只）。
   在融合前，缺失值（NaN）是当做 0 处置，还是直接在权重计算中重新归一化？"

Supported strategies:
  - fill_zero: missing symbol → score = 0
  - fill_median: missing symbol → cross-sectional median
  - renormalize: re-normalize per-strategy scores to fill the gap
  - intersection: only include symbols present in ALL strategies
  - union: include all symbols (fill gaps)

Usage:
    from qp.strategy.ensemble import EnsembleEngine, UniversePolicy

    engine = EnsembleEngine(
        universe_policy=UniversePolicy.FILL_ZERO,
        weight_method=WeightMethod.IC_WEIGHTED,
    )
    batch = engine.fuse(
        signals={"momentum_v1": df1, "value_v1": df2},
        ic_history={"momentum_v1": 0.08, "value_v1": 0.04},
        date_str="2026-08-01",
    )
    # → AlphaSignalBatch with fused scores
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import polars as pl

from qp.strategy.aggregator import SignalAggregator
from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod
from qp.strategy.models.alpha_signal import AlphaSignal, AlphaSignalBatch


class UniversePolicy(Enum):
    """How to handle symbols present in one strategy but not another."""

    FILL_ZERO = "fill_zero"  # Missing → score 0.0
    FILL_MEDIAN = "fill_median"  # Missing → cross-sectional median
    RENORMALIZE = "renormalize"  # Re-normalize after filling
    INTERSECTION = "intersection"  # Only common symbols
    UNION = "union"  # All symbols (same as fill_zero)


@dataclass
class EnsembleEngine:
    """Orchestrate multi-strategy signal fusion.

    Takes signals from multiple strategies, aligns universes,
    applies dynamic weighting, and fuses into a single AlphaSignalBatch.

    Attributes:
        universe_policy: How to handle mismatched symbols across strategies.
        weight_engine: WeightEngine for dynamic weight allocation.
        aggregator: SignalAggregator for combining signals.
        default_score: Fill value for missing symbols (when policy=FILL_ZERO).
    """

    universe_policy: UniversePolicy = UniversePolicy.FILL_ZERO
    weight_engine: WeightEngine | None = None
    aggregator: SignalAggregator | None = None
    default_score: float = 0.0

    def __post_init__(self) -> None:
        if self.weight_engine is None:
            self.weight_engine = WeightEngine(method=WeightMethod.EQUAL)
        if self.aggregator is None:
            self.aggregator = SignalAggregator(method="rank_blend")

    # ------------------------------------------------------------------
    # Main fusion entry point
    # ------------------------------------------------------------------

    def fuse(
        self,
        signals: dict[str, pl.DataFrame],
        *,
        date_str: str = "",
        ic_history: dict[str, float] | None = None,
        sharpe_history: dict[str, float] | None = None,
        regime: str | None = None,
        strategy_tags: dict[str, list[str]] | None = None,
        fixed_weights: dict[str, float] | None = None,
        score_col: str = "raw_score",
    ) -> AlphaSignalBatch:
        """Fuse multi-strategy signals into a unified AlphaSignalBatch.

        Args:
            signals: {strategy_id: DataFrame[symbol, raw_score]}.
            date_str: Trading date for the output batch.
            ic_history: Rolling IC for IC-weighted allocation.
            sharpe_history: Rolling Sharpe for Sharpe-weighted allocation.
            regime: Market regime for regime-weighted allocation.
            strategy_tags: {strategy_id: [tags]} for regime matching.
            fixed_weights: Direct fixed weights (overrides weight engine).
            score_col: Name of the score column in each DataFrame.

        Returns:
            AlphaSignalBatch with fused alpha scores.
        """
        if not signals:
            return AlphaSignalBatch(date=date_str)

        # Filter empty
        valid = {k: v for k, v in signals.items() if v is not None and not v.is_empty()}
        if not valid:
            return AlphaSignalBatch(date=date_str)

        strategy_ids = list(valid.keys())

        # ── 1. Universe alignment ──
        aligned = self._align_universes(valid, score_col=score_col)

        # ── 2. Compute weights ──
        if fixed_weights:
            weights = self._normalize_weights(fixed_weights, strategy_ids)
        else:
            assert self.weight_engine is not None
            weights = self.weight_engine.compute(
                strategy_ids,
                ic_history=ic_history,
                sharpe_history=sharpe_history,
                regime=regime,
                strategy_tags=strategy_tags,
            )

        # ── 3. Apply weights and fuse per-symbol ──
        # Instead of filling missing with 0 (which penalizes uncovered stocks),
        # normalize by valid-strategy weight so only active strategies vote.
        all_symbols: set[str] = set()
        for df in aligned.values():
            all_symbols.update(df["symbol"].to_list())

        # Per-strategy weighted scores keyed by symbol
        strategy_scores: dict[str, dict[str, float | None]] = {sym: {} for sym in all_symbols}
        for sid, df in aligned.items():
            w = weights.get(sid, 1.0 / max(len(aligned), 1))
            if w <= 0:
                continue
            for row in df.iter_rows(named=True):
                sym = str(row["symbol"])
                s = row[score_col]
                s_val = float(s) if s is not None and s == s else None  # NaN check
                strategy_scores[sym][sid] = s_val * w if s_val is not None else None

        # Compute ensemble score per symbol (weighted avg of available strategies)
        rows: list[dict] = []
        for sym, sid_scores in strategy_scores.items():
            valid_vals = [v for v in sid_scores.values() if v is not None]
            valid_weights = [
                weights.get(sid, 1.0 / max(len(aligned), 1))
                for sid, v in sid_scores.items()
                if v is not None
            ]
            total_w = sum(valid_weights)
            ensemble_score = sum(valid_vals) / total_w if total_w > 0 else 0.0
            coverage = len(valid_vals) / max(len(aligned), 1)

            row = {
                "symbol": sym,
                "aggregated_score": round(ensemble_score, 6),
                "strategy_coverage": round(coverage, 2),
                "n_strategies": len(valid_vals),
            }
            # Add per-strategy scores
            for sid in aligned:
                row[f"score_{sid}"] = sid_scores.get(sid)
            rows.append(row)

        fused = pl.DataFrame(rows)
        if fused.is_empty():
            return AlphaSignalBatch(date=date_str)

        # ── 4. Convert to AlphaSignalBatch ──
        return self._to_batch(
            fused,
            date_str=date_str,
            weights=weights,
            raw_components=aligned,
        )

    # ------------------------------------------------------------------
    # Universe alignment
    # ------------------------------------------------------------------

    def _align_universes(
        self,
        signals: dict[str, pl.DataFrame],
        score_col: str = "raw_score",
    ) -> dict[str, pl.DataFrame]:
        """Align cross-sections across strategies.

        Ensures all DataFrames have the same set of symbols before fusion.
        """
        if self.universe_policy == UniversePolicy.INTERSECTION:
            return self._align_intersection(signals, score_col)
        if self.universe_policy == UniversePolicy.RENORMALIZE:
            return self._align_renormalize(signals, score_col)
        if self.universe_policy == UniversePolicy.FILL_MEDIAN:
            return self._align_fill(signals, score_col, use_median=True)
        # UNION / FILL_ZERO
        return self._align_fill(signals, score_col, use_median=False)

    @staticmethod
    def _align_intersection(
        signals: dict[str, pl.DataFrame],
        score_col: str,
    ) -> dict[str, pl.DataFrame]:
        """Keep only symbols present in ALL strategies."""
        symbol_sets = [set(df["symbol"].to_list()) for df in signals.values()]
        common = symbol_sets[0]
        for s in symbol_sets[1:]:
            common = common & s
        if not common:
            return signals

        result: dict[str, pl.DataFrame] = {}
        for sid, df in signals.items():
            result[sid] = df.filter(pl.col("symbol").is_in(list(common)))
        return result

    def _align_fill(
        self,
        signals: dict[str, pl.DataFrame],
        score_col: str,
        use_median: bool = False,
    ) -> dict[str, pl.DataFrame]:
        """Fill missing symbols with default value or median."""
        # Collect all symbols
        all_symbols: set[str] = set()
        for df in signals.values():
            all_symbols.update(df["symbol"].to_list())

        result: dict[str, pl.DataFrame] = {}
        for sid, df in signals.items():
            existing = set(df["symbol"].to_list())
            missing = all_symbols - existing

            if not missing:
                result[sid] = df
                continue

            fill_val = self.default_score
            if use_median and not df.is_empty():
                scores = df[score_col].to_numpy()
                fill_val = float(np.median(scores))

            # Append missing rows
            missing_df = pl.DataFrame(
                {
                    "symbol": list(missing),
                    score_col: [fill_val] * len(missing),
                }
            )

            # Preserve other columns
            for col in df.columns:
                if col not in missing_df.columns:
                    missing_df = missing_df.with_columns(pl.lit(None).alias(col))

            result[sid] = pl.concat([df, missing_df])

        return result

    def _align_renormalize(
        self,
        signals: dict[str, pl.DataFrame],
        score_col: str,
    ) -> dict[str, pl.DataFrame]:
        """Fill zeros then re-normalize each strategy to preserve distribution."""
        filled = self._align_fill(signals, score_col, use_median=False)

        result: dict[str, pl.DataFrame] = {}
        for sid, df in filled.items():
            scores = df[score_col].to_numpy()
            mn = float(scores.min())
            mx = float(scores.max())
            normalized = (scores - mn) / (mx - mn) if mx - mn > 1e-12 else np.full_like(scores, 0.5)
            result[sid] = df.with_columns(pl.Series(score_col, normalized))

        return result

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def _to_batch(
        self,
        fused_df: pl.DataFrame,
        *,
        date_str: str,
        weights: dict[str, float],
        raw_components: dict[str, pl.DataFrame],
    ) -> AlphaSignalBatch:
        """Convert a fused Polars DataFrame to AlphaSignalBatch."""
        signals: list[AlphaSignal] = []

        # Determine score column
        score_col = (
            "aggregated_score"
            if "aggregated_score" in fused_df.columns
            else "feature_value"
            if "feature_value" in fused_df.columns
            else "votes"
            if "votes" in fused_df.columns
            else None
        )

        if score_col is None:
            return AlphaSignalBatch(date=date_str)

        for row in fused_df.iter_rows(named=True):
            sym = str(row.get("symbol", ""))
            score = float(row.get(score_col, 0.0))
            coverage = float(row.get("strategy_coverage", 1.0))
            n_strategies = int(row.get("n_strategies", len(raw_components)))

            # Per-strategy scores from fused DataFrame (already computed)
            components: dict[str, float] = {}
            for sid in raw_components:
                col_name = f"score_{sid}"
                if col_name in fused_df.columns:
                    val = row.get(col_name)
                    if val is not None and val == val:  # not NaN
                        components[sid] = float(val)

            signals.append(
                AlphaSignal(
                    date=date_str,
                    symbol=sym,
                    alpha_score=score,
                    raw_components=components,
                    confidence=coverage,  # strategy coverage as confidence
                    strategy_id=f"ensemble_{n_strategies}",
                )
            )

        # Rank-normalize if needed (for non-rank_blend methods)
        if signals:
            scores_arr = np.array([s.alpha_score for s in signals])
            mn, mx = scores_arr.min(), scores_arr.max()
            if mx - mn > 1e-12:
                for s in signals:
                    s.alpha_score = float((s.alpha_score - mn) / (mx - mn))
                    s.alpha_score = max(0.0, min(1.0, s.alpha_score))

        return AlphaSignalBatch(date=date_str, signals=signals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_weights(
        weights: dict[str, float],
        strategy_ids: list[str],
    ) -> dict[str, float]:
        """Normalize weights to sum to 1.0, filling missing with 0."""
        result: dict[str, float] = {}
        for sid in strategy_ids:
            result[sid] = weights.get(sid, 0.0)
        total = sum(result.values())
        if total < 1e-12:
            n = len(strategy_ids)
            return dict.fromkeys(strategy_ids, 1.0 / n)
        return {k: v / total for k, v in result.items()}
