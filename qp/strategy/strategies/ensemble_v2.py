"""Alpha Ensemble v2 — Multi-source factor ensemble with regime-aware activation.

4-layer factor system:
  - price_alpha (30%): Residual Momentum, Reversal, Low Vol, Amplitude, Volume
  - value (25%): PE_TTM, PB, PCF_OCF
  - quality (25%): ROE_Level, Profit_Stability, Earnings_Quality, Margin_Composite, debt_ratio
  - growth (20%): revenue_growth, net_profit_growth

Regime-adaptive: layer weights shift per market regime (bull/bear/crisis/etc.)
"""

from __future__ import annotations

from qp.strategy.config import StrategyConfig, register_config
from qp.strategy.factor_layers import FACTOR_LAYERS_V2, FactorEnsemble

# Build flat weights from the ensemble (base weights, no regime tilt)
_ensemble = FactorEnsemble.from_config(FACTOR_LAYERS_V2)
_flat_weights = _ensemble.get_active_weights()

ALPHA_ENSEMBLE_V2_CONFIG = register_config(
    StrategyConfig(
        name="alpha_ensemble_v2",
        display_name="Alpha Ensemble v2 (Price+Value+Quality+Growth)",
        factors=_flat_weights,
        max_positions=10,
        rebalance_freq=20,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        quality_filter=True,
        use_market_filter=True,
        use_regime_ensemble=True,
        factor_layers=FACTOR_LAYERS_V2,
        regime_positions={
            "bull": 5,
            "sideways_up": 8,
            "neutral": 10,
            "sideways_down": 12,
            "bear": 15,
            "crisis": 20,
        },
        regime_freq={
            "bull": 15,
            "sideways_up": 20,
            "neutral": 20,
            "sideways_down": 30,
            "bear": 40,
            "crisis": 60,
        },
    )
)
