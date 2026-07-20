"""Feature Engineering — first-class assets with versioning (ADR-019).

15+ factors across 5 categories:
  - Momentum (5): Short_Term_Reversal_5D, Momentum_1M/3M/6M, Momentum_3M_vol_adj
  - Volatility (3): Volatility_20D, Volatility_60D, MaxDD_60D
  - Volume (4): Volume_Ratio_5D, Volume_Trend_10D, Price_Volume_Corr, Volume_Price_Trend
  - Money Flow (3): Amplitude_5D, Volume_Concentration, Implied_Net_Flow
  - Valuation (external data): PE_TTM, PB, Dividend_Yield, PS_TTM, PCF_OCF
"""

from qp.research.feature.compute import (
    ALL_FACTOR_DESCRIPTIONS,
    ALL_FACTOR_DIRECTIONS,
    PRICE_VOLUME_FACTORS,
    compute_all_factors,
    get_default_factor_weights,
)
from qp.research.feature.momentum import (
    Momentum1M,
    Momentum3M,
    Momentum3MVolAdjusted,
    Momentum6M,
    Momentum20dFeature,  # backward-compatible alias
    ShortTermReversal5D,
    compute_momentum_factors,
)
from qp.research.feature.money_flow import (
    Amplitude5D,
    ImpliedNetFlow,
    VolumeConcentration,
    compute_money_flow_factors,
)
from qp.research.feature.registry import FeatureRegistry
from qp.research.feature.volatility import (
    MaxDrawdown60D,
    Volatility20D,
    Volatility20dFeature,  # backward-compatible alias
    Volatility60D,
    compute_volatility_factors,
)
from qp.research.feature.volume import (
    PriceVolumeCorr,
    VolumePriceTrend,
    VolumeRatio5D,
    VolumeTrend10D,
    compute_volume_factors,
)

__all__ = [
    # Registry
    "FeatureRegistry",
    # Momentum
    "ShortTermReversal5D",
    "Momentum1M",
    "Momentum3M",
    "Momentum6M",
    "Momentum3MVolAdjusted",
    "Momentum20dFeature",  # backward-compatible
    # Volatility
    "Volatility20D",
    "Volatility60D",
    "MaxDrawdown60D",
    "Volatility20dFeature",  # backward-compatible
    # Volume
    "VolumeRatio5D",
    "VolumeTrend10D",
    "PriceVolumeCorr",
    "VolumePriceTrend",
    # Money Flow
    "Amplitude5D",
    "VolumeConcentration",
    "ImpliedNetFlow",
    # Batch computation
    "compute_all_factors",
    "compute_momentum_factors",
    "compute_volatility_factors",
    "compute_volume_factors",
    "compute_money_flow_factors",
    "get_default_factor_weights",
    # Metadata
    "ALL_FACTOR_DIRECTIONS",
    "ALL_FACTOR_DESCRIPTIONS",
    "PRICE_VOLUME_FACTORS",
]
