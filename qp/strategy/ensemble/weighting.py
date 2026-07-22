"""Dynamic Weighting — allocate fusion weights across strategies.

Per docs/6_Strategy_Engine.md §模块五:
  "Final Score = 0.4 × Momentum + 0.4 × Quality + 0.2 × Value"

Weighting schemes:
  - FIXED: Static user-defined weights
  - IC_WEIGHTED: Weights proportional to recent rolling IC
  - SHARPE_WEIGHTED: Weights proportional to strategy Sharpe ratio
  - REGIME: Pre-configured per-regime weight maps
  - EQUAL: Equal weight fallback (1/N)

Usage:
    from qp.strategy.ensemble.weighting import WeightEngine

    engine = WeightEngine(method=WeightMethod.IC_WEIGHTED)
    weights = engine.compute(
        strategy_ids=["momentum_v1", "value_v1"],
        ic_history={"momentum_v1": 0.08, "value_v1": 0.04},
    )
    # → {"momentum_v1": 0.667, "value_v1": 0.333}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class WeightMethod(Enum):
    """Strategy weight allocation method."""

    FIXED = "fixed"
    EQUAL = "equal"
    IC_WEIGHTED = "ic_weighted"
    SHARPE_WEIGHTED = "sharpe_weighted"
    REGIME = "regime"


# Default regime → strategy weights (bull favors momentum, bear favors defensive)
DEFAULT_REGIME_WEIGHTS: dict[str, dict[str, dict[str, float]]] = {
    "bull": {
        "momentum": 0.50,
        "quality": 0.30,
        "growth": 0.10,
        "value": 0.10,
    },
    "sideways_up": {
        "momentum": 0.35,
        "quality": 0.35,
        "growth": 0.10,
        "value": 0.20,
    },
    "sideways_down": {
        "momentum": 0.10,
        "quality": 0.30,
        "defensive": 0.40,
        "value": 0.20,
    },
    "neutral": {
        "momentum": 0.25,
        "quality": 0.25,
        "growth": 0.15,
        "value": 0.25,
        "defensive": 0.10,
    },
    "bear": {
        "momentum": 0.05,
        "quality": 0.20,
        "defensive": 0.60,
        "value": 0.15,
    },
    "crisis": {
        "cash": 1.0,
    },
}


@dataclass
class WeightEngine:
    """Compute per-strategy fusion weights dynamically.

    Usage:
        engine = WeightEngine(method=WeightMethod.SHARPE_WEIGHTED)
        weights = engine.compute(
            strategy_ids=["mom", "val", "qual"],
            sharpe_history={"mom": 1.2, "val": 0.8, "qual": 1.5},
        )
        # → {"mom": 0.343, "val": 0.229, "qual": 0.429}
    """

    method: WeightMethod = WeightMethod.EQUAL
    fixed_weights: dict[str, float] = field(default_factory=dict)
    regime_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    min_weight: float = 0.05  # Floor per strategy (0 = can be zeroed)
    smoothing_halflife: int = 10  # EMA halflife for weight updating

    # Internal state (smoothed weights for EMA)
    _smoothed: dict[str, float] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def compute(
        self,
        strategy_ids: list[str],
        *,
        ic_history: dict[str, float] | None = None,
        sharpe_history: dict[str, float] | None = None,
        regime: str | None = None,
        strategy_tags: dict[str, list[str]] | None = None,
    ) -> dict[str, float]:
        """Compute fusion weights for a set of strategies.

        Args:
            strategy_ids: Strategy IDs to weight.
            ic_history: {strategy_id: rolling_IC_mean} for IC weighting.
            sharpe_history: {strategy_id: rolling_sharpe} for Sharpe weighting.
            regime: Current market regime for regime-based weighting.
            strategy_tags: {strategy_id: [tags]} for tag-based regime matching.

        Returns:
            {strategy_id: weight} dict, guaranteed to sum to 1.0.
        """
        if not strategy_ids:
            return {}

        if self.method == WeightMethod.FIXED:
            weights = self._fixed(strategy_ids)
        elif self.method == WeightMethod.IC_WEIGHTED:
            weights = self._ic_weighted(strategy_ids, ic_history or {})
        elif self.method == WeightMethod.SHARPE_WEIGHTED:
            weights = self._sharpe_weighted(strategy_ids, sharpe_history or {})
        elif self.method == WeightMethod.REGIME:
            weights = self._regime_weighted(
                strategy_ids,
                regime or "neutral",
                strategy_tags or {},
            )
        else:  # EQUAL
            weights = self._equal(strategy_ids)

        # Apply minimum weight floor
        weights = self._apply_floor(weights)

        # Normalize to sum 1.0
        weights = self._normalize(weights)

        # EMA smoothing
        weights = self._ema_smooth(weights)

        return weights

    # ------------------------------------------------------------------
    # Weighting schemes
    # ------------------------------------------------------------------

    def _equal(self, ids: list[str]) -> dict[str, float]:
        n = len(ids)
        return {sid: 1.0 / n for sid in ids}

    def _fixed(self, ids: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for sid in ids:
            result[sid] = self.fixed_weights.get(sid, 0.0)
        return result

    def _ic_weighted(
        self,
        ids: list[str],
        ic: dict[str, float],
    ) -> dict[str, float]:
        """Weight proportional to absolute IC."""
        result: dict[str, float] = {}
        for sid in ids:
            raw_ic = ic.get(sid, 0.0)
            result[sid] = max(abs(raw_ic), 0.001)
        return result

    def _sharpe_weighted(
        self,
        ids: list[str],
        sharpe: dict[str, float],
    ) -> dict[str, float]:
        """Weight proportional to Sharpe (clamp negative to 0.01)."""
        result: dict[str, float] = {}
        for sid in ids:
            s = sharpe.get(sid, 0.0)
            result[sid] = max(s, 0.01)
        return result

    def _regime_weighted(
        self,
        ids: list[str],
        regime: str,
        tags: dict[str, list[str]],
    ) -> dict[str, float]:
        """Match strategy tags to regime-configured weights."""
        regime_cfg = self.regime_weights.get(regime, {})
        if not regime_cfg:
            # Fall back to built-in defaults
            regime_cfg = DEFAULT_REGIME_WEIGHTS.get(regime, {})

        result: dict[str, float] = {}
        for sid in ids:
            strategy_tags = tags.get(sid, [sid])
            weight = 0.0
            for tag in strategy_tags:
                weight += regime_cfg.get(tag, 0.0)
            result[sid] = max(weight, 0.0)

        return result

    # ------------------------------------------------------------------
    # Normalization & smoothing
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(weights: dict[str, float]) -> dict[str, float]:
        total = sum(weights.values())
        if total < 1e-12:
            # All-zero — fall back to equal
            n = len(weights)
            return {k: 1.0 / n for k in weights}
        return {k: v / total for k, v in weights.items()}

    def _apply_floor(self, weights: dict[str, float]) -> dict[str, float]:
        """Apply minimum weight, redistributing the difference."""
        if self.min_weight <= 0:
            return weights

        # Identify strategies below floor
        floored: dict[str, float] = {}
        surplus = 0.0
        above_count = 0

        for sid, w in weights.items():
            if w < self.min_weight:
                surplus += self.min_weight - w
                floored[sid] = self.min_weight
            else:
                floored[sid] = w
                above_count += 1

        # Redistribute surplus from above-floor strategies
        if surplus > 0 and above_count > 0:
            per_above = surplus / above_count
            for sid in list(floored.keys()):
                if floored[sid] > self.min_weight:
                    floored[sid] -= per_above

        return floored

    def _ema_smooth(self, weights: dict[str, float]) -> dict[str, float]:
        """Exponentially smooth weights toward new values."""
        if not self._smoothed:
            self._smoothed = dict(weights)
            return dict(weights)

        alpha = 2.0 / (self.smoothing_halflife * 2 + 1)

        smoothed: dict[str, float] = {}
        for sid, w in weights.items():
            prev = self._smoothed.get(sid, w)
            smoothed[sid] = alpha * w + (1 - alpha) * prev

        # Remove stale entries
        for sid in list(self._smoothed.keys()):
            if sid not in weights:
                del self._smoothed[sid]

        self._smoothed = smoothed
        # Re-normalize after smoothing
        return self._normalize(smoothed)
