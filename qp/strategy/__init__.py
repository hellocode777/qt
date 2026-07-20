"""Strategy Layer — investment policy, produces Decisions (not Orders).

See ADR-026: Strategy Produces Decision.
"""

from qp.strategy.aggregator import SignalAggregator
from qp.strategy.registry import StrategyRegistry
from qp.strategy.simple_rank import Decision, SimpleRankStrategy

__all__ = [
    "Decision",
    "SignalAggregator",
    "SimpleRankStrategy",
    "StrategyRegistry",
]
