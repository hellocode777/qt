"""Factor Layer v2 — Multi-source alpha ensemble with 4 layers.

Replaces the flat {factor_name: weight} dict with a hierarchical structure:

  FactorEnsemble
    ├── price_alpha (30%): Residual Momentum, Reversal, Low Vol, Amplitude, Volume
    ├── value (25%): PE_TTM, PB, PCF_OCF
    ├── quality (25%): ROE_Level, Profit_Stability, Earnings_Quality, Margin_Composite, debt_ratio
    └── growth (20%): revenue_growth, net_profit_growth

Each layer has its own factors and directions. Within each layer, factors are
equally weighted by default (can be overridden). The layer weight determines
how much that layer contributes to the final composite score.

When combined with regime information (see regime_ensemble.py), layer weights
can be dynamically adjusted per market regime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------
# Factor Layer v2 Definition
# ------------------------------------------------------------------

FACTOR_LAYERS_V2: dict[str, dict[str, Any]] = {
    "price_alpha": {
        "weight": 0.30,
        "description": "Market microstructure alpha — reversal, low vol, volume patterns",
        "factors": {
            "Residual_Momentum_3M": -1,
            "Short_Term_Reversal_5D": -1,
            "Volatility_20D": +1,
            "Amplitude_5D": -1,
            "Volume_Concentration": -1,
        },
    },
    "value": {
        "weight": 0.25,
        "description": "Valuation anchor — cheap stocks outperform in the long run",
        "factors": {
            "PE_TTM": -1,
            "PB": -1,
            "PCF_OCF": -1,
        },
    },
    "quality": {
        "weight": 0.25,
        "description": "Profitability & earnings quality — high-quality companies compound",
        "factors": {
            "ROE": +1,
            "gross_margin": +1,
            "net_margin": +1,
            "debt_ratio": -1,
        },
    },
    "growth": {
        "weight": 0.20,
        "description": "Growth trajectory — revenue and profit expansion",
        "factors": {
            "revenue_growth": +1,
            "net_profit_growth": +1,
        },
    },
}


# ------------------------------------------------------------------
# Factor-to-layer mapping (reverse index for fast lookup)
# ------------------------------------------------------------------


def get_factor_to_layer_map() -> dict[str, str]:
    """Build {factor_name: layer_name} reverse index."""
    result: dict[str, str] = {}
    for layer_name, layer_cfg in FACTOR_LAYERS_V2.items():
        for fname in layer_cfg["factors"]:
            result[fname] = layer_name
    return result


# ------------------------------------------------------------------
# Core classes
# ------------------------------------------------------------------


@dataclass
class FactorLayerConfig:
    """Configuration for a single factor layer.

    Attributes:
        name: Layer identifier (e.g. "price_alpha").
        weight: Layer weight in the ensemble (0-1). All layer weights
            should sum to 1.0.
        factors: {factor_name: direction} within the layer. Within-layer
            factors are equal-weighted by default.
        active_in_regimes: Regimes where this layer is active. Empty
            list means active in all regimes.
    """

    name: str = ""
    weight: float = 0.0
    factors: dict[str, float] = field(default_factory=dict)
    active_in_regimes: list[str] = field(default_factory=list)

    @property
    def is_active_in_all_regimes(self) -> bool:
        return len(self.active_in_regimes) == 0

    def is_active_in(self, regime: str) -> bool:
        if self.is_active_in_all_regimes:
            return True
        return regime in self.active_in_regimes

    def get_within_layer_weights(self) -> dict[str, float]:
        """Equal-weight factors within the layer."""
        n = len(self.factors)
        if n == 0:
            return {}
        w = 1.0 / n
        return dict.fromkeys(self.factors, w)

    def get_effective_weights(self) -> dict[str, float]:
        """Factor weights scaled by layer weight.

        effective_weight = layer_weight * within_layer_weight * direction

        Returns:
            {factor_name: signed_effective_weight} where sum(|w|) = layer_weight.
        """
        within = self.get_within_layer_weights()
        return {f: self.weight * within[f] * self.factors[f] for f in self.factors}


class FactorEnsemble:
    """Multi-source factor ensemble with regime-aware activation.

    Usage:
        ensemble = FactorEnsemble.from_config()

        # Flat weights for all factors (all layers active)
        weights = ensemble.get_active_weights()

        # Regime-aware weights
        weights = ensemble.get_active_weights(regime="bear")

        # Per-layer weights for diagnostics
        layer_weights = ensemble.get_layer_weights(regime="bull")
    """

    def __init__(self, layers: dict[str, FactorLayerConfig]) -> None:
        self._layers = layers
        # Normalize layer weights to sum to 1.0
        total = sum(layer_cfg.weight for layer_cfg in layers.values())
        if total > 0:
            for layer_cfg in layers.values():
                layer_cfg.weight = layer_cfg.weight / total

    @classmethod
    def from_config(
        cls,
        layer_config: dict[str, dict[str, Any]] | None = None,
    ) -> FactorEnsemble:
        """Create from dictionary configuration.

        Args:
            layer_config: Dict matching FACTOR_LAYERS_V2 structure.
                Uses FACTOR_LAYERS_V2 if None.

        Returns:
            Configured FactorEnsemble.
        """
        cfg = layer_config or FACTOR_LAYERS_V2
        layers: dict[str, FactorLayerConfig] = {}
        for name, lc in cfg.items():
            layers[name] = FactorLayerConfig(
                name=name,
                weight=lc["weight"],
                factors=dict(lc["factors"]),
            )
        return cls(layers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_weights(
        self,
        regime: str = "",
        layer_overrides: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Get factor weights active in the given regime.

        Args:
            regime: Market regime label (e.g. "bull", "bear", "crisis").
                If empty, uses base layer weights (all layers active).
            layer_overrides: Optional per-layer weight overrides for this
                regime. Maps layer_name → new_weight. Layers not in the
                override keep their base weight. Disabled layers get
                weight=0.0.

        Returns:
            {factor_name: signed_effective_weight} flat dict suitable
            for passing to combine_factors().
        """
        result: dict[str, float] = {}

        for layer_name, layer in self._layers.items():
            # Determine effective layer weight
            if layer_overrides is not None:
                eff_weight = layer_overrides.get(layer_name, layer.weight)
            else:
                eff_weight = layer.weight

            if eff_weight <= 0:
                continue

            # Within-layer factor weights
            within = layer.get_within_layer_weights()
            for fname, direction in layer.factors.items():
                result[fname] = eff_weight * within[fname] * direction

        return result

    def get_layer_weights(self, regime: str = "") -> dict[str, float]:
        """Get per-layer weights for the given regime.

        Args:
            regime: Market regime label. If empty, returns base weights.

        Returns:
            {layer_name: weight} where weights sum to 1.0.
        """
        from qp.strategy.regime_ensemble import get_regime_layer_weights

        if regime:
            return get_regime_layer_weights(regime)

        return {name: layer_cfg.weight for name, layer_cfg in self._layers.items()}

    def get_active_weights_with_health(
        self,
        regime: str = "",
        layer_overrides: dict[str, float] | None = None,
        health_multipliers: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Get factor weights with health-based adjustments applied.

        Each factor's effective weight is multiplied by its health multiplier
        (1.0 = healthy, 0.5 = degraded, 0.0 = stale).

        DP-002 §4.4, H10: Auto weight reduction on DEGRADED/STALE.

        Args:
            regime: Market regime label.
            layer_overrides: Optional per-layer weight overrides.
            health_multipliers: {factor_name: multiplier (0.0–1.0)}.
                Factors not in the dict default to 1.0 (healthy).

        Returns:
            {factor_name: signed_effective_weight} with health adjustments.
        """
        base_weights = self.get_active_weights(regime=regime, layer_overrides=layer_overrides)

        if not health_multipliers:
            return base_weights

        result: dict[str, float] = {}
        for fname, w in base_weights.items():
            multiplier = health_multipliers.get(fname, 1.0)
            # STALE factors (multiplier=0.0) are dropped entirely
            if multiplier <= 0:
                continue
            result[fname] = w * multiplier

        # Re-normalize so |weights| sum to 1.0 (keeps score magnitude consistent)
        total_abs = sum(abs(w) for w in result.values())
        if total_abs > 0:
            result = {f: w / total_abs for f, w in result.items()}

        return result

    def get_weights_with_layers(
        self,
        regime: str = "",
    ) -> dict[str, float]:
        """Get factor weights using regime-adjusted layer weights.

        This combines get_layer_weights(regime) with within-layer factor
        weights to produce the final flat factor weight dict.

        Args:
            regime: Market regime label.

        Returns:
            {factor_name: signed_effective_weight}.
        """
        layer_weights = self.get_layer_weights(regime)
        return self.get_active_weights(regime=regime, layer_overrides=layer_weights)

    # ------------------------------------------------------------------
    # Layer weight optimization from IC (DP-002 E7)
    # ------------------------------------------------------------------

    def optimize_layer_weights_from_ic(
        self,
        factor_ics: dict[str, float],
        factor_icirs: dict[str, float] | None = None,
        shrinkage: float = 0.30,
    ) -> dict[str, float]:
        """Optimize layer weights from per-factor IC/ICIR values.

        Instead of using flat/equal layer weights, this computes optimal
        layer weights proportional to the predictive power of factors
        within each layer.

        Uses IC_IR (signal consistency) as the quality metric for each
        factor, then aggregates to layer level.

        Args:
            factor_ics: {factor_name: mean_IC}. Absolute value is used.
            factor_icirs: {factor_name: IC_IR}. If None, computed from IC
                assuming std=0.05 (conservative).
            shrinkage: Blending weight toward prior (0 = pure IC-based,
                1 = pure prior/base weights). Default 0.30.

        Returns:
            {layer_name: optimized_weight} where weights sum to 1.0.
        """
        if not factor_ics:
            return self.get_layer_weights()

        # Compute IC_IR for each factor (use IC magnitude as quality proxy)
        factor_quality: dict[str, float] = {}
        for fname, ic in factor_ics.items():
            if factor_icirs and fname in factor_icirs:
                factor_quality[fname] = abs(factor_icirs[fname])
            else:
                # Conservative: assume std(IC) ≈ 0.05
                factor_quality[fname] = abs(ic)

        # Aggregate quality per layer
        layer_quality: dict[str, float] = {}
        layer_counts: dict[str, int] = {}
        for lname, layer in self._layers.items():
            quality_sum = 0.0
            count = 0
            for fname in layer.factors:
                if fname in factor_quality:
                    quality_sum += factor_quality[fname]
                    count += 1
            layer_quality[lname] = quality_sum
            layer_counts[lname] = count

        # Normalize to get IC-based layer weights
        total_quality = sum(layer_quality.values())
        if total_quality <= 0:
            return self.get_layer_weights()

        ic_weights = {lname: q / total_quality for lname, q in layer_quality.items()}

        # Shrinkage: blend with prior (base layer weights)
        prior = self.get_layer_weights()
        optimized: dict[str, float] = {}
        for lname in self._layers:
            prior_w = prior.get(lname, 0.0)
            ic_w = ic_weights.get(lname, 0.0)
            optimized[lname] = shrinkage * prior_w + (1 - shrinkage) * ic_w

        # Re-normalize
        total = sum(optimized.values())
        if total > 0:
            optimized = {k: v / total for k, v in optimized.items()}

        return optimized

    def get_optimized_weights(
        self,
        factor_ics: dict[str, float],
        factor_icirs: dict[str, float] | None = None,
        regime: str = "",
        shrinkage: float = 0.30,
    ) -> dict[str, float]:
        """Get factor weights with IC-optimized layer weights.

        Combines optimize_layer_weights_from_ic with get_active_weights
        to produce the final flat factor weight dict.

        Args:
            factor_ics: {factor_name: mean_IC}.
            factor_icirs: {factor_name: IC_IR}.
            regime: Market regime label.
            shrinkage: Prior shrinkage weight.

        Returns:
            {factor_name: signed_effective_weight}.
        """
        layer_weights = self.optimize_layer_weights_from_ic(
            factor_ics=factor_ics,
            factor_icirs=factor_icirs,
            shrinkage=shrinkage,
        )
        return self.get_active_weights(regime=regime, layer_overrides=layer_weights)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def layer_names(self) -> list[str]:
        return list(self._layers.keys())

    @property
    def all_factor_names(self) -> list[str]:
        result: list[str] = []
        for layer in self._layers.values():
            result.extend(layer.factors.keys())
        return result

    def get_layer_for_factor(self, factor_name: str) -> str | None:
        """Return which layer a factor belongs to."""
        for lname, layer in self._layers.items():
            if factor_name in layer.factors:
                return lname
        return None

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for logging/debugging."""
        result: dict[str, Any] = {
            "n_layers": len(self._layers),
            "n_factors": len(self.all_factor_names),
            "layers": {},
        }
        for lname, layer in self._layers.items():
            flattened = layer.get_effective_weights()
            result["layers"][lname] = {
                "weight": round(layer.weight, 3),
                "n_factors": len(layer.factors),
                "top_factor": max(flattened, key=lambda k: abs(flattened[k])),
            }
        return result
