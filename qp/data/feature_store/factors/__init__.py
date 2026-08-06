"""Concrete factor/feature implementations for the Feature Store.

These are production-ready feature operators that can be registered
with FeatureRegistry and computed via FeatureEngine.

Factor categories:
  - momentum: Price trend and reversal factors
  - volatility: Risk and volatility measures
  - volume: Volume-based activity and liquidity factors
  - technical: Moving average, MACD, and positioning indicators

Usage::

    from qp.data.feature_store import FeatureRegistry, FeatureEngine
    from qp.data.feature_store.factors import (
        Momentum20,
        RSI14,
        RollingVolatility20,
        VolumeRatio5,
        SMACross,
        MACD,
    )

    registry = FeatureRegistry()
    registry.register(Momentum20())
    registry.register(RSI14())
    registry.register(RollingVolatility20())
    registry.register(VolumeRatio5())
    registry.register(SMACross(fast=5, slow=20))
    registry.register(MACD())

    engine = FeatureEngine(registry)
    features = engine.compute(ohlcv_df)
    # → DataFrame with all computed factor columns
"""

from qp.data.feature_store.factors.momentum import (
    RSI,
    RSI14,
    Momentum,
    Momentum5,
    Momentum20,
    Momentum60,
    ShortTermReversal,
)
from qp.data.feature_store.factors.technical import (
    MACD,
    PricePosition,
    SMACross,
)
from qp.data.feature_store.factors.volatility import (
    ATR,
    ATR14,
    RollingVolatility,
    RollingVolatility20,
    RollingVolatility60,
)
from qp.data.feature_store.factors.volume import (
    AvgVolume,
    TurnoverRate,
    VolumeRatio,
    VolumeRatio5,
    VolumeRatio20,
)

__all__ = [
    "ATR",
    "ATR14",
    "MACD",
    "RSI",
    "RSI14",
    "AvgVolume",
    # Momentum
    "Momentum",
    "Momentum5",
    "Momentum20",
    "Momentum60",
    "PricePosition",
    # Volatility
    "RollingVolatility",
    "RollingVolatility20",
    "RollingVolatility60",
    # Technical
    "SMACross",
    "ShortTermReversal",
    "TurnoverRate",
    # Volume
    "VolumeRatio",
    "VolumeRatio5",
    "VolumeRatio20",
]
