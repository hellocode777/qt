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
        return {f: w for f in self.factors}

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
