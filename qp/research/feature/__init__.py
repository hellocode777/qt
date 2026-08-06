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
    ALL_FACTORS_WITH_COMPOSITES,
    COMPOSITE_FACTORS,
    PRICE_VOLUME_FACTORS,
    compute_all_factors,
    compute_composite_factors,
    get_default_factor_weights,
)
from qp.research.feature.momentum import (
    Momentum1M,
    Momentum3M,
    Momentum3MVolAdjusted,
    Momentum6M,
    Momentum20dFeature,  # backward-compatible alias
    ResidualMomentum3M,
    ShortTermReversal5D,
    compute_momentum_factors,
)
from qp.research.feature.money_flow import (
    Amplitude5D,
    ImpliedNetFlow,
    VolumeConcentration,
    compute_money_flow_factors,
)
from qp.research.feature.quality import (
    QUALITY_DESCRIPTIONS,
    QUALITY_DIRECTIONS,
    EarningsQuality,
    MarginComposite,
    ProfitStability,
    ROELevel,
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
    "ALL_FACTORS_WITH_COMPOSITES",
    "ALL_FACTOR_DESCRIPTIONS",
    # Metadata
    "ALL_FACTOR_DIRECTIONS",
    "COMPOSITE_FACTORS",
    "PRICE_VOLUME_FACTORS",
    "QUALITY_DESCRIPTIONS",
    "QUALITY_DIRECTIONS",
    # Money Flow
    "Amplitude5D",
    "EarningsQuality",
    # Registry
    "FeatureRegistry",
    "ImpliedNetFlow",
    "MarginComposite",
    "MaxDrawdown60D",
    "Momentum1M",
    "Momentum3M",
    "Momentum3MVolAdjusted",
    "Momentum6M",
    "Momentum20dFeature",  # backward-compatible
    "PriceVolumeCorr",
    "ProfitStability",
    # Quality
    "ROELevel",
    "ResidualMomentum3M",
    # Momentum
    "ShortTermReversal5D",
    # Volatility
    "Volatility20D",
    "Volatility20dFeature",  # backward-compatible
    "Volatility60D",
    "VolumeConcentration",
    "VolumePriceTrend",
    # Volume
    "VolumeRatio5D",
    "VolumeTrend10D",
    # Batch computation
    "compute_all_factors",
    # Composite factors
    "compute_composite_factors",
    "compute_momentum_factors",
    "compute_money_flow_factors",
    "compute_volatility_factors",
    "compute_volume_factors",
    "get_default_factor_weights",
]
