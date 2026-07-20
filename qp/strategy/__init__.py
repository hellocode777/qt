"""Strategy Layer — investment policy, produces Decisions (not Orders).

See ADR-026: Strategy Produces Decision.
"""

from qp.strategy.aggregator import SignalAggregator
from qp.strategy.paper_trading import (
    PaperTradingResult,
    PaperTradingRun,
    PaperTradingTracker,
)
from qp.strategy.registry import StrategyRegistry
from qp.strategy.simple_rank import Decision, SimpleRankStrategy

__all__ = [
    "Decision",
    "PaperTradingResult",
    "PaperTradingRun",
    "PaperTradingTracker",
    "SignalAggregator",
    "SimpleRankStrategy",
    "StrategyRegistry",
]
