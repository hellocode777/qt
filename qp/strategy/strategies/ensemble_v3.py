"""alpha_ensemble_v3 — 6-factor composite strategy (Multifactor v2).

Replaces the 16 raw factors with 6 composite Alpha Sources:
  LowVol_Composite (30%) + Momentum_Composite (20%) + Value_Composite (15%)
  + Quality_Composite (15%) + Volume_Composite (10%) + Reversal_Composite (10%)

Each composite merges correlated raw factors via rank-based blending,
eliminating factor redundancy and reducing overfitting.

Based on factor correlation analysis (2026-08-05):
  - Amplitude_5D ↔ Volatility_20D: 0.98 → merged into LowVol
  - Momentum_3M ↔ Residual_Momentum_3M: 0.96 → merged into Momentum
  - PCF_OCF ↔ PE_TTM: 0.96, PB ↔ PE: 0.91 → merged into Value
  - ROE ↔ net_profit_growth: 0.96 → merged into Quality
"""

from __future__ import annotations

from qp.strategy.config import StrategyConfig, register_config

# ------------------------------------------------------------------
# Composite weights (from correlation-optimized allocation)
# ------------------------------------------------------------------

COMPOSITE_WEIGHTS_V3: dict[str, float] = {
    "LowVol_Composite": +0.30,  # Low vol — only positive alpha in A-shares
    "Momentum_Composite": -0.20,  # Residual + raw momentum reversal
    "Value_Composite": -0.15,  # Cheap stocks → reversal (A-share daily)
    "Quality_Composite": -0.15,  # High quality → reversal (A-share daily)
    "Volume_Composite": -0.10,  # Volume patterns → reversal
    "Reversal_Composite": -0.10,  # Short-term mean reversion
}

# ------------------------------------------------------------------
# Strategy config
# ------------------------------------------------------------------

ALPHA_ENSEMBLE_V3_CONFIG = register_config(
    StrategyConfig(
        name="alpha_ensemble_v3",
        display_name="Alpha Ensemble v3 — 6 Composite Factors",
        factors=dict(COMPOSITE_WEIGHTS_V3),
        max_positions=10,
        rebalance_freq=20,
        sell_buffer_multiplier=2,
        model_mode=False,
        quality_filter=True,
        industry_neutral=True,
        orthogonalize=True,
        anti_chase=True,
        chase_threshold=0.20,
        chase_lookback=5,
        use_market_filter=True,
        use_regime_ensemble=False,  # v3 uses composites; regime ensemble not yet composite-aware
        factor_layers={
            "price_alpha": {
                "weight": 0.40,
                "description": "LowVol + Momentum + Reversal + Volume",
                "factors": {
                    "LowVol_Composite": +1,
                    "Momentum_Composite": -1,
                    "Reversal_Composite": -1,
                    "Volume_Composite": -1,
                },
            },
            "value": {
                "weight": 0.25,
                "description": "Value composite (PE+PB+PCF)",
                "factors": {
                    "Value_Composite": -1,
                },
            },
            "quality": {
                "weight": 0.20,
                "description": "Quality composite (ROE+Margin+Growth)",
                "factors": {
                    "Quality_Composite": +1,
                },
            },
            "growth": {
                "weight": 0.15,
                "description": "Growth trajectory",
                "factors": {
                    "revenue_growth": +1,
                    "net_profit_growth": +1,
                },
            },
        },
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
