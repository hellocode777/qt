"""StrategyRegistry — tracks and manages all registered strategies.

Dictionary-backed in-memory registry (Walking Skeleton).
Will be upgraded to database-backed in Phase 4 per dp.md §8.
"""

from __future__ import annotations

from qp.shared.protocols.base_strategy import BaseStrategy
from qp.shared.types import StrategyLifecycle


class StrategyRegistry:
    """Central registry for all investment strategies.

    Strategies are registered by their strategy_id and can be
    queried by lifecycle state (active, paper_trading, production, etc.).

    Usage:
        registry = StrategyRegistry()
        registry.register(MomentumRankStrategy())
        registry.register(VolatilityRankStrategy())
        active = registry.get_active()
    """

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}
        self._lifecycles: dict[str, StrategyLifecycle] = {}

    def register(
        self,
        strategy: BaseStrategy,
        lifecycle: StrategyLifecycle = StrategyLifecycle.RESEARCH,
    ) -> None:
        """Register a strategy.

        Args:
            strategy: The strategy instance to register.
            lifecycle: Initial lifecycle state (default RESEARCH).

        Raises:
            ValueError: If a strategy with the same ID is already registered.
        """
        sid = strategy.strategy_id
        if sid in self._strategies:
            raise ValueError(f"Strategy '{sid}' already registered")
        self._strategies[sid] = strategy
        self._lifecycles[sid] = lifecycle

    def get(self, strategy_id: str) -> BaseStrategy:
        """Get a registered strategy by ID."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._strategies[strategy_id]

    def list_strategies(self) -> list[str]:
        """List all registered strategy IDs."""
        return list(self._strategies.keys())

    def get_active(self) -> list[BaseStrategy]:
        """Get strategies eligible for signal generation.

        Active = PAPER_TRADING, SHADOW_PRODUCTION, or PRODUCTION.
        Excludes RESEARCH, BACKTEST_PASSED (pre-paper), and
        KILL_SWITCH, DEPRECATED, ARCHIVED (post-mortem).
        """
        active_states = {
            StrategyLifecycle.PAPER_TRADING,
            StrategyLifecycle.SHADOW_PRODUCTION,
            StrategyLifecycle.PRODUCTION,
        }
        return [
            s
            for sid, s in self._strategies.items()
            if self._lifecycles.get(sid) in active_states
        ]

    def get_backtest_ready(self) -> list[BaseStrategy]:
        """Get strategies ready for backtesting.

        Includes RESEARCH and BACKTEST_PASSED states.
        """
        ready_states = {
            StrategyLifecycle.RESEARCH,
            StrategyLifecycle.BACKTEST_PASSED,
        }
        return [
            s
            for sid, s in self._strategies.items()
            if self._lifecycles.get(sid) in ready_states
        ]

    def set_lifecycle(self, strategy_id: str, state: StrategyLifecycle) -> None:
        """Update a strategy's lifecycle state."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        self._lifecycles[strategy_id] = state

    def get_lifecycle(self, strategy_id: str) -> StrategyLifecycle:
        """Get a strategy's current lifecycle state."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._lifecycles[strategy_id]
