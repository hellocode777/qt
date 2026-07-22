"""Multi-Strategy Ensemble — fusion with dynamic weighting.

Per docs/6_Strategy_Engine.md §模块五:
  "输入多个策略 → 融合 → Final Score"

Pipeline: WeightEngine → Universe Align → Signal Aggregation → AlphaSignalBatch
"""

from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy
from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

__all__ = [
    "EnsembleEngine",
    "UniversePolicy",
    "WeightEngine",
    "WeightMethod",
]
