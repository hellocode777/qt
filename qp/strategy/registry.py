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

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from qp.shared.protocols.base_strategy import BaseStrategy
from qp.shared.types import RebalanceSchedule, StrategyLifecycle
from qp.strategy.approved import cast_dict

# Persistence path for strategy metadata (no strategy instances,
# just lifecycle + metadata — enough for WebUI listing)
_REGISTRY_FILE = Path("data/strategy_registry.json")

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
        weights: Frozen factor weights (ADR-031 — ApprovedStrategy snapshot).
        parameters: Frozen strategy parameters (top_n, rebalance, filters, etc.).
        backtest_ic: Mean Rank IC from experiment validation.
        backtest_sharpe: Sharpe ratio from experiment backtest.
        backtest_max_dd: Max drawdown (%) from experiment backtest.
        backtest_excess_return: Excess return (%) vs benchmark.
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

    # Frozen strategy snapshot (ADR-031)
    weights: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, object] = field(default_factory=dict)
    backtest_ic: float = 0.0
    backtest_sharpe: float = 0.0
    backtest_max_dd: float = 0.0
    backtest_excess_return: float = 0.0

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
            # Frozen snapshot
            "weights": self.weights,
            "parameters": self.parameters,
            "backtest_ic": self.backtest_ic,
            "backtest_sharpe": self.backtest_sharpe,
            "backtest_max_dd": self.backtest_max_dd,
            "backtest_excess_return": self.backtest_excess_return,
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

        weights_raw = data.get("weights", {})
        weights: dict[str, float] = (
            {str(k): float(str(v)) for k, v in cast("dict[object, object]", weights_raw).items()}
            if weights_raw
            else {}
        )
        params_raw = data.get("parameters", {})
        parameters: dict[str, object] = (
            {str(k): v for k, v in cast("dict[object, object]", params_raw).items()}
            if params_raw
            else {}
        )

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
            weights=weights,
            parameters=parameters,
            backtest_ic=float(str(data.get("backtest_ic", 0.0))),
            backtest_sharpe=float(str(data.get("backtest_sharpe", 0.0))),
            backtest_max_dd=float(str(data.get("backtest_max_dd", 0.0))),
            backtest_excess_return=float(str(data.get("backtest_excess_return", 0.0))),
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

    def __init__(self, registry_path: Path | str | None = None) -> None:
        self._strategies: dict[str, BaseStrategy] = {}
        self._lifecycles: dict[str, StrategyLifecycle] = {}
        self._metadata: dict[str, StrategyMeta] = {}
        self._approved: dict[str, object] = {}  # ApprovedStrategy snapshots (ADR-031)
        self._active_versions: dict[str, bool] = {}  # Which versions are active
        self._lineage_registry: LineageRegistry | None = None
        self._registry_file: Path = Path(registry_path) if registry_path else _REGISTRY_FILE
        self._load()

    # ------------------------------------------------------------------
    # Persistence — metadata only (strategy instances can't be serialized)
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load lifecycle, metadata, and approved snapshots from disk."""
        if not self._registry_file.exists():
            return
        try:
            data = json.loads(self._registry_file.read_text())
            for sid, entry in data.get("strategies", {}).items():
                lifecycle_raw = entry.get("lifecycle", "research")
                try:
                    self._lifecycles[sid] = StrategyLifecycle(lifecycle_raw)
                except ValueError:
                    self._lifecycles[sid] = StrategyLifecycle.RESEARCH
                self._metadata[sid] = StrategyMeta.from_dict(entry.get("meta", {}))

                # Load approved snapshot if present (ADR-031)
                approved_raw = entry.get("approved")
                if approved_raw and isinstance(approved_raw, dict):
                    self._approved[sid] = cast_dict(approved_raw)
                    self._active_versions[sid] = bool(entry.get("active", False))
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        """Persist lifecycle, metadata, and approved snapshots to disk."""
        data: dict[str, dict[str, object]] = {}
        for sid in set(self._strategies.keys()) | set(self._lifecycles.keys()):
            lifecycle = self._lifecycles.get(sid, StrategyLifecycle.RESEARCH)
            meta = self._metadata.get(sid, StrategyMeta())
            entry: dict[str, object] = {
                "lifecycle": lifecycle.value,
                "meta": meta.to_dict(),
                "active": self._active_versions.get(sid, False),
            }
            # Persist approved snapshot
            if sid in self._approved:
                entry["approved"] = self._approved[sid]
            data[sid] = entry
        try:
            self._registry_file.parent.mkdir(parents=True, exist_ok=True)
            self._registry_file.write_text(
                json.dumps(
                    {"strategies": data},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        except OSError:
            pass

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
        # Preserve metadata loaded from disk if no explicit meta provided
        self._metadata[sid] = meta or self._metadata.get(sid, StrategyMeta())
        self._save()

    def get(self, strategy_id: str) -> BaseStrategy:
        """Get a registered strategy by ID."""
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._strategies[strategy_id]

    def list_strategies(self) -> list[str]:
        """List all registered strategy IDs.

        Includes strategies from persisted metadata (WebUI / cross-process)
        even when strategy instances aren't loaded into this process.
        """
        sids = set(self._strategies.keys()) | set(self._lifecycles.keys())
        return sorted(sids)

    def get_active(self) -> list[BaseStrategy]:
        """Get strategies eligible for signal generation.

        Active = PAPER_TRADING, SHADOW_PRODUCTION, or PRODUCTION.
        Excludes RESEARCH, BACKTEST_PASSED (pre-paper), and
        KILL_SWITCH, DEPRECATED, ARCHIVED (post-mortem).
        """
        active_states = {
            StrategyLifecycle.PAPER_TRADING,
            StrategyLifecycle.APPROVED,
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
        if strategy_id not in self._strategies and strategy_id not in self._lifecycles:
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
        self._save()

    def get_lifecycle(self, strategy_id: str) -> StrategyLifecycle:
        """Get a strategy's current lifecycle state."""
        if strategy_id in self._lifecycles:
            return self._lifecycles[strategy_id]
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
        if strategy_id in self._metadata:
            return self._metadata[strategy_id]
        if strategy_id not in self._strategies:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        return self._metadata.get(strategy_id, StrategyMeta())

    def set_meta(self, strategy_id: str, meta: StrategyMeta) -> None:
        """Update a strategy's metadata.

        Args:
            strategy_id: Strategy to update.
            meta: New metadata.

        Raises:
            KeyError: If strategy is not registered (in _strategies
                      or _lifecycles — supports metadata-only entries
                      loaded from disk for cross-process workflows).
        """
        if strategy_id not in self._strategies and strategy_id not in self._lifecycles:
            raise KeyError(f"Strategy '{strategy_id}' not registered")
        self._metadata[strategy_id] = meta
        self._save()

    # ------------------------------------------------------------------
    # Approved strategy snapshots (ADR-031 Step 3)
    # ------------------------------------------------------------------

    def approve(
        self,
        strategy_id: str,
        approved_by: str = "",
        version: str | None = None,
    ) -> object:
        """Freeze a strategy as an ApprovedStrategy snapshot.

        Creates an immutable ApprovedStrategy from the current StrategyMeta,
        sets the lifecycle to APPROVED, marks it as active, and persists.

        Args:
            strategy_id: Strategy to approve.
            approved_by: Person or system approving the strategy.
            version: Freeze version string (default: "v" + today).

        Returns:
            ApprovedStrategy instance.

        Raises:
            KeyError: If strategy is not registered.
            ValueError: If strategy has no weights set in metadata.
        """
        from qp.strategy.approved import ApprovedStrategy

        if strategy_id not in self._strategies and strategy_id not in self._lifecycles:
            raise KeyError(f"Strategy '{strategy_id}' not registered")

        meta = self._metadata.get(strategy_id, StrategyMeta())
        if not meta.weights:
            raise ValueError(
                f"Strategy '{strategy_id}' has no weights in metadata. "
                f"Set meta.weights before approving."
            )

        if version is None:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            version = "v" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")

        approved = ApprovedStrategy.from_strategy_meta(
            strategy_id=strategy_id,
            version=version,
            approved_by=approved_by,
            meta=meta,
        )

        self._approved[strategy_id] = approved.to_dict()
        self._active_versions[strategy_id] = True
        self.set_lifecycle(strategy_id, StrategyLifecycle.APPROVED)
        self._save()

        return approved

    def load_active(self) -> list[object]:
        """Return all active ApprovedStrategy snapshots.

        Can be called without strategy instances loaded (e.g., from WebUI
        or Daily Pipeline before registration).  Reads from in-memory
        approved dict (populated by _load() at init).

        Returns:
            List of ApprovedStrategy instances for active strategies.
        """
        from qp.strategy.approved import ApprovedStrategy

        results: list[object] = []
        for sid, approved_raw in self._approved.items():
            if self._active_versions.get(sid, False):
                with contextlib.suppress(TypeError, KeyError):
                    results.append(ApprovedStrategy.from_dict(cast_dict(approved_raw)))
        return results

    def load_active_as_meta(self) -> list[StrategyMeta]:
        """Return StrategyMeta for all active APPROVED strategies.

        Convenience for Daily Pipeline — returns StrategyMeta with frozen
        weights/parameters ready for strategy construction.

        Returns:
            List of StrategyMeta for active, approved strategies.
        """
        results: list[StrategyMeta] = []
        for sid, lifecycle in self._lifecycles.items():
            if lifecycle == StrategyLifecycle.APPROVED and self._active_versions.get(sid, False):
                meta = self._metadata.get(sid)
                if meta and meta.weights:
                    results.append(meta)
        return results

    def get_approved(self, strategy_id: str) -> object | None:
        """Get an ApprovedStrategy snapshot by ID.

        Args:
            strategy_id: Strategy to retrieve.

        Returns:
            ApprovedStrategy instance, or None if not approved.
        """
        from qp.strategy.approved import ApprovedStrategy

        approved_raw = self._approved.get(strategy_id)
        if approved_raw is None:
            return None
        try:
            return ApprovedStrategy.from_dict(cast_dict(approved_raw))
        except (TypeError, KeyError):
            return None

    def deactivate(self, strategy_id: str) -> None:
        """Deactivate an approved strategy.

        Sets the active flag to False and reverts lifecycle to
        BACKTEST_PASSED.  The approved snapshot is preserved for audit.

        Args:
            strategy_id: Strategy to deactivate.

        Raises:
            KeyError: If strategy is not registered.
        """
        if strategy_id not in self._strategies and strategy_id not in self._lifecycles:
            raise KeyError(f"Strategy '{strategy_id}' not registered")

        self._active_versions[strategy_id] = False
        self.set_lifecycle(strategy_id, StrategyLifecycle.BACKTEST_PASSED)
        self._save()

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
