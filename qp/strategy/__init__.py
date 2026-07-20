"""Strategy Layer — investment policy, produces Decisions (not Orders).

See ADR-026: Strategy Produces Decision.
"""

from qp.strategy.aggregator import SignalAggregator
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
from qp.strategy.multifactor import (
    compute_cross_sectional_scores,
    generate_rebalance_signals,
    run_multifactor_strategy,
)
from qp.strategy.paper_trading import (
    PaperTradingResult,
    PaperTradingRun,
    PaperTradingTracker,
)
from qp.strategy.quality_filter import apply_quality_filter, get_filter_report
from qp.strategy.registry import StrategyRegistry
from qp.strategy.simple_rank import Decision, SimpleRankStrategy

__all__ = [
    # Simple (walking skeleton, backward-compatible)
    "Decision",
    "SimpleRankStrategy",
    "SignalAggregator",
    "StrategyRegistry",
    # Multi-factor (full engine)
    "run_multifactor_strategy",
    "compute_cross_sectional_scores",
    "generate_rebalance_signals",
    # Quality filter
    "apply_quality_filter",
    "get_filter_report",
    # Market filter
    "check_market_environment",
    "filter_signals",
    "apply_regime_gating",
    "MarketStatus",
    # Market regime detection
    "MarketRegimeDetector",
    "RegimeResult",
    "regime_to_position_pct",
    "regime_allows_buy",
    "DEFAULT_REGIME_POSITIONS",
    # Paper trading
    "PaperTradingTracker",
    "PaperTradingRun",
    "PaperTradingResult",
]
