"""Strategy Layer — investment policy, produces Decisions (not Orders).

See ADR-026: Strategy Produces Decision.
"""

from qp.strategy.aggregator import SignalAggregator
from qp.strategy.ensemble import (
    EnsembleEngine,
    UniversePolicy,
    WeightEngine,
    WeightMethod,
)
from qp.strategy.generator import GeneratorConfig, SignalGenerator
from qp.strategy.loader import StrategyLoader
from qp.strategy.market_filter import (
    MarketStatus,
    apply_regime_gating,
    check_market_environment,
    filter_signals,
)
from qp.strategy.market_regime import (
    DEFAULT_REGIME_POSITIONS,
    MarketRegimeDetector,
    RegimeResult,
    regime_allows_buy,
    regime_to_position_pct,
)
from qp.strategy.models import AlphaSignal, AlphaSignalBatch, StrategyResult
from qp.strategy.multifactor import (
    compute_cross_sectional_scores,
    generate_rebalance_signals,
    run_multifactor_strategy,
)
from qp.strategy.quality_filter import apply_quality_filter, get_filter_report
from qp.strategy.registry import StrategyMeta, StrategyRegistry
from qp.strategy.runner import RunnerResult, StrategyRunner
from qp.strategy.signal import (
    ClipMethod,
    ConfidenceScorer,
    NormMethod,
    SignalClipper,
    SignalNormalizer,
    SignalSmoother,
    SignalThreshold,
    SmoothMethod,
)
from qp.strategy.simple_rank import Decision, SimpleRankStrategy
from qp.strategy.strategies import MomentumStrategy, QualityStrategy, ValueStrategy

__all__ = [
    "DEFAULT_REGIME_POSITIONS",
    # Models
    "AlphaSignal",
    "AlphaSignalBatch",
    "ClipMethod",
    "ConfidenceScorer",
    # Simple (walking skeleton, backward-compatible)
    "Decision",
    # Ensemble
    "EnsembleEngine",
    "GeneratorConfig",
    # Market regime detection
    "MarketRegimeDetector",
    "MarketStatus",
    # Concrete strategies
    "MomentumStrategy",
    "NormMethod",
    # Paper trading (actual classes live in qp.simulation.paper_trading)
    "QualityStrategy",
    "RegimeResult",
    "RunnerResult",
    "SignalAggregator",
    "SignalClipper",
    # Generator
    "SignalGenerator",
    # Signal post-processing
    "SignalNormalizer",
    "SignalSmoother",
    "SignalThreshold",
    "SimpleRankStrategy",
    "SmoothMethod",
    # Loader
    "StrategyLoader",
    "StrategyMeta",
    "StrategyRegistry",
    "StrategyResult",
    # Runner
    "StrategyRunner",
    "UniversePolicy",
    "ValueStrategy",
    "WeightEngine",
    "WeightMethod",
    # Quality filter
    "apply_quality_filter",
    "apply_regime_gating",
    # Market filter
    "check_market_environment",
    "compute_cross_sectional_scores",
    "filter_signals",
    "generate_rebalance_signals",
    "get_filter_report",
    "regime_allows_buy",
    "regime_to_position_pct",
    # Multi-factor (full engine)
    "run_multifactor_strategy",
]
