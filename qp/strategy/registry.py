"""StrategyRegistry — tracks and manages all registered strategies.

Dictionary-backed in-memory registry (Walking Skeleton).
Will be upgraded to database-backed in Phase 4 per dp.md §8.

Lineage gate (2.5): When a LineageRegistry is attached, strategies
promoted beyond BACKTEST_PASSED are validated for complete lineage
before the lifecycle change is committed. Per docs/4_Registry_
LineageLayer.md §1④:
  "只有通过 Layer 3 Purged CV 检疫、且具备完整血缘链条的策略，
   才能被分配 Strategy_ID 并下发到实盘柜台。"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from qp.shared.protocols.base_strategy import BaseStrategy
from qp.shared.types import RebalanceSchedule, StrategyLifecycle

if TYPE_CHECKING:
    from qp.lineage.engine import LineageRegistry


# Lifecycle states that require complete lineage before promotion
_LINEAGE_REQUIRED_STATES: frozenset[StrategyLifecycle] = frozenset(
    {
        StrategyLifecycle.PAPER_TRADING,
        StrategyLifecycle.SHADOW_PRODUCTION,
        StrategyLifecycle.PRODUCTION,
    }
)


@dataclass
class StrategyMeta:
    """Metadata for a registered strategy.

    Per docs/6_Strategy_Engine.md §模块一, the registry should store:
    strategy_id, strategy_version, model_version, feature_version,
    feature_set, rebalance_frequency, status, owner.

    Attributes:
        strategy_version: Semantic version of the strategy logic.
        model_version: Version of the underlying model.
        feature_version: Version of the feature set used.
        feature_set: List of factor/feature names used by this strategy.
        rebalance_frequency: How often this strategy rebalances.
        rebalance_day: For WEEKLY schedules, day of week (0=Mon, 4=Fri).
        owner: Person or team responsible for this strategy.
        description: Human-readable description.
        tags: Free-form tags for categorisation.
    """

    strategy_version: str = "1.0.0"
    model_version: str = ""
    feature_version: str = ""
    feature_set: list[str] = field(default_factory=list)
    rebalance_frequency: RebalanceSchedule = RebalanceSchedule.DAILY
    rebalance_day: int = 0
    owner: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_version": self.strategy_version,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "feature_set": self.feature_set,
            "rebalance_frequency": self.rebalance_frequency.value,
            "rebalance_day": self.rebalance_day,
            "owner": self.owner,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StrategyMeta:
        freq_raw = data.get("rebalance_frequency", "daily")
        if isinstance(freq_raw, RebalanceSchedule):
            freq = freq_raw
        else:
            try:
                freq = RebalanceSchedule(str(freq_raw))
            except ValueError:
                freq = RebalanceSchedule.DAILY
        return cls(
            strategy_version=str(data.get("strategy_version", "1.0.0")),
            model_version=str(data.get("model_version", "")),
            feature_version=str(data.get("feature_version", "")),
            feature_set=list(cast("list[str]", data.get("feature_set", []))),
            rebalance_frequency=freq,
            rebalance_day=int(cast("int", data.get("rebalance_day", 0))),
            owner=str(data.get("owner", "")),
            description=str(data.get("description", "")),
            tags=list(cast("list[str]", data.get("tags", []))),
        )


class StrategyRegistry:
    """Central registry for all investment strategies.

    Strategies are registered by their strategy_id and can be
    queried by lifecycle state (active, paper_trading, production, etc.).

    Optional lineage gate: attach a LineageRegistry to enforce
    complete Data → Feature → Model → Strategy lineage before
    promoting strategies to PAPER_TRADING or above.

    Usage:
        registry = StrategyRegistry()
        registry.register(MomentumRankStrategy())

        # With lineage gate
        from qp.lineage import LineageRegistry
        lineage = LineageRegistry()
        registry.set_lineage_registry(lineage)
        registry.set_lifecycle("momentum_v1", StrategyLifecycle.PRODUCTION)
        # → ValueError if lineage is incomplete
    """

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}
        self._lifecycles: dict[str, StrategyLifecycle] = {}
        self._metadata: dict[str, StrategyMeta] = {}
        self._lineage_registry: LineageRegistry | None = None

    # ------------------------------------------------------------------
    # Lineage gate
    # ------------------------------------------------------------------

    def set_lineage_registry(self, lineage: LineageRegistry) -> None:
        """Attach a LineageRegistry for lineage validation.

        Once set, lifecycle promotions to PAPER_TRADING or above
        will be blocked unless the strategy has a complete lineage chain.

        Args:
            lineage: A LineageRegistry instance with the strategy's
                     full dependency chain registered.
        """
        self._lineage_registry = lineage

    def get_lineage_registry(self) -> LineageRegistry | None:
        """Return the attached LineageRegistry, if any."""
        return self._lineage_registry

    @property
    def lineage_gate_enabled(self) -> bool:
        """Whether lineage validation is active."""
        return self._lineage_registry is not None

    def validate_lineage(self, strategy_id: str) -> dict[str, object]:
        """Check whether a strategy has complete lineage.

        Args:
            strategy_id: Strategy to check.

        Returns:
            Dict with:
              - valid: bool
              - complete: bool (alias for valid)
              - missing: list[str] of gaps
              - message: human-readable summary
        """
        from qp.lineage.types import make_strategy_node_id

        if self._lineage_registry is None:
            return {
                "valid": True,
                "complete": True,
                "missing": [],
                "message": "No lineage registry attached — gate bypassed.",
            }

        strategy_node = make_strategy_node_id(strategy_id)
        result = self._lineage_registry.validate_lineage(strategy_node)
        return {
            "valid": result["complete"],
            "complete": result["complete"],
            "missing": result["missing"],
            "message": (
                "Lineage complete."
                if result["complete"]
                else f"Lineage incomplete: {', '.join(result['missing'])}"
            ),
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        strategy: BaseStrategy,
        lifecycle: StrategyLifecycle = StrategyLifecycle.RESEARCH,
        meta: StrategyMeta | None = None,
    ) -> None:
        """Register a strategy.

        Args:
            strategy: The strategy instance to register.
            lifecycle: Initial lifecycle state (default RESEARCH).
            meta: Optional metadata (feature_set, model_version, owner, etc.).

        Raises:
            ValueError: If a strategy with the same ID is already registered,
                        or if the lifecycle requires lineage validation and
                        no LineageRegistry is attached.
        """
        sid = strategy.strategy_id
        if sid in self._strategies:
            raise ValueError(f"Strategy '{sid}' already registered")

        # Lineage gate: warn but don't block initial registration
        # (the gate is enforced at lifecycle promotion, not registration)
        if lifecycle in _LINEAGE_REQUIRED_STATES:
            if self._lineage_registry is None:
                raise ValueError(
                    f"Strategy '{sid}' is registered with lifecycle "
                    f"'{lifecycle.value}' which requires lineage validation, "
                    f"but no LineageRegistry is attached. "
                    f"Call set_lineage_registry() first."
                )
            validation = self.validate_lineage(sid)
            if not validation["valid"]:
                raise ValueError(
                    f"Strategy '{sid}' cannot be registered as "
                    f"'{lifecycle.value}': {validation['message']}"
                )

        self._strategies[sid] = strategy
        self._lifecycles[sid] = lifecycle
        self._metadata[sid] = meta or StrategyMeta()

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
            s for sid, s in self._strategies.items() if self._lifecycles.get(sid) in active_states
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
            s for sid, s in self._strategies.items() if self._lifecycles.get(sid) in ready_states
        ]

    def set_lifecycle(
        self,
        strategy_id: str,
        state: StrategyLifecycle,
        require_proposal: bool = False,
    ) -> None:
        """Update a strategy's lifecycle state.

        Enforces lineage validation when promoting to PAPER_TRADING,
        SHADOW_PRODUCTION, or PRODUCTION.

        Optionally requires an approved proposal for gated promotions
        (G-011: human-in-the-loop approval workflow).  Set
        ``require_proposal=True`` to enable the proposal gate.

        Args:
            strategy_id: Strategy to update.
            state: New lifecycle state.
            require_proposal: If True, requires an approved proposal
                from the ProposalStore for promotions to PAPER_TRADING
                or above.

        Raises:
            KeyError: If strategy is not registered.
            ValueError: If lineage validation fails or no approved
                proposal exists (when require_proposal=True).
        """
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")

        if state in _LINEAGE_REQUIRED_STATES:
            validation = self.validate_lineage(strategy_id)
            if not validation["valid"]:
                raise ValueError(
                    f"Cannot promote '{strategy_id}' to '{state.value}': {validation['message']}"
                )

            # G-011: Proposal gate for human-in-the-loop approval
            if require_proposal:
                from qp.platform.proposals.store import ProposalStore

                store = ProposalStore()
                active = store.get_active_for_strategy(strategy_id)
                if active is None or active.status != "approved":
                    raise ValueError(
                        f"Cannot promote '{strategy_id}' to '{state.value}': "
                        f"no approved proposal found. "
                        f"Create one with: qp proposal create --strategy {strategy_id} "
                        f"--target {state.value}"
                    )
                if active.target_lifecycle != state.value:
                    raise ValueError(
                        f"Cannot promote '{strategy_id}' to '{state.value}': "
                        f"approved proposal targets '{active.target_lifecycle}'"
                    )

        self._lifecycles[strategy_id] = state

    def get_lifecycle(self, strategy_id: str) -> StrategyLifecycle:
        """Get a strategy's current lifecycle state."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._lifecycles[strategy_id]

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_meta(self, strategy_id: str) -> StrategyMeta:
        """Get a strategy's metadata.

        Args:
            strategy_id: Strategy to query.

        Returns:
            StrategyMeta for the strategy.

        Raises:
            KeyError: If strategy is not registered.
        """
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._metadata.get(strategy_id, StrategyMeta())

    def set_meta(self, strategy_id: str, meta: StrategyMeta) -> None:
        """Update a strategy's metadata.

        Args:
            strategy_id: Strategy to update.
            meta: New metadata.

        Raises:
            KeyError: If strategy is not registered.
        """
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        self._metadata[strategy_id] = meta

    def get_by_owner(self, owner: str) -> list[str]:
        """List strategy IDs owned by a specific person/team."""
        return [
            sid
            for sid, meta in self._metadata.items()
            if meta.owner == owner and sid in self._strategies
        ]

    def get_by_frequency(self, freq: RebalanceSchedule) -> list[str]:
        """List strategy IDs with a specific rebalance frequency."""
        return [
            sid
            for sid, meta in self._metadata.items()
            if meta.rebalance_frequency == freq and sid in self._strategies
        ]

    def get_by_tag(self, tag: str) -> list[str]:
        """List strategy IDs with a specific tag."""
        return [
            sid
            for sid, meta in self._metadata.items()
            if tag in meta.tags and sid in self._strategies
        ]

    def list_metadata(self) -> dict[str, StrategyMeta]:
        """Get all strategy metadata keyed by strategy_id."""
        return dict(self._metadata)

    @property
    def count(self) -> int:
        """Total number of registered strategies."""
        return len(self._strategies)
