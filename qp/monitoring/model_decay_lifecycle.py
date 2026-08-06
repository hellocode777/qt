"""Model Decay ↔ Kill Switch Lifecycle Bridge.

Links model decay detection to strategy lifecycle state changes.
Implements the automatic downgrade pathway per rule.md §7.9.8:

  Model Decay detected → Strategy downgraded to Shadow → Retrain triggered
  Kill Switch triggered → Strategy PAUSED → Manual review required

This module bridges the gap between monitoring/ (observe-only) and
strategy/ (lifecycle management). It is NOT observe-only — it invokes
lifecycle transitions in response to monitoring signals.

Usage:
    bridge = ModelDecayLifecycle(StrategyRegistry(), ModelDecayDetector(0.035))
    bridge.set_alert_manager(AlertManager())

    # Weekly automated check
    actions = bridge.check_and_act(
        strategy_id="momentum_v1",
        rolling_ic=0.008,
        daily_ic_series=[...],
    )
    # → {strategy_id, old_lifecycle, new_lifecycle, action, reason}
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from qp.monitoring.model_decay import DecayStage, ModelDecayDetector
from qp.shared.types import StrategyLifecycle

# Strategy lifecycle downgrade map when decay is detected
_DECAY_LIFECYCLE_MAP: dict[DecayStage, StrategyLifecycle | None] = {
    DecayStage.HEALTHY: None,  # No change
    DecayStage.WARNING: None,  # No change — monitor only
    DecayStage.DECAYING: StrategyLifecycle.SHADOW_PRODUCTION,  # Downgrade to Shadow
    DecayStage.STALE: StrategyLifecycle.KILL_SWITCH,  # Full stop
}


@dataclass
class LifecycleAction:
    """Result of a model decay lifecycle check.

    Attributes:
        strategy_id: Which strategy.
        decay_stage: Current decay stage from detector.
        old_lifecycle: Previous strategy lifecycle state.
        new_lifecycle: New strategy lifecycle state (None if no change).
        action: Recommended action (OK / WATCH / DOWNGRADE / KILL).
        downgraded: Whether a downgrade was performed.
        reason: Human-readable reason.
        ic_ratio: Current IC ratio.
        rolling_ic: Current rolling IC.
        training_ic: Reference training IC.
        consecutive_decay_days: Consecutive days below threshold.
    """

    strategy_id: str = ""
    decay_stage: DecayStage = DecayStage.HEALTHY
    old_lifecycle: StrategyLifecycle = StrategyLifecycle.PRODUCTION
    new_lifecycle: StrategyLifecycle | None = None
    action: str = "OK"
    downgraded: bool = False
    reason: str = ""
    ic_ratio: float = 1.0
    rolling_ic: float = 0.0
    training_ic: float = 0.0
    consecutive_decay_days: int = 0

    def summary(self) -> str:
        if self.downgraded:
            return (
                f"DOWNGRADE: {self.strategy_id} {self.old_lifecycle.value} "
                f"→ {self.new_lifecycle.value if self.new_lifecycle else 'N/A'} "
                f"({self.reason})"
            )
        return (
            f"{self.action}: {self.strategy_id} {self.decay_stage.value} "
            f"(IC ratio={self.ic_ratio:.0%}, rolling={self.rolling_ic:.4f})"
        )


class ModelDecayLifecycle:
    """Bridges Model Decay detection to Strategy Lifecycle management.

    On DECAYING: automatically downgrades strategy to SHADOW_PRODUCTION.
    On STALE: triggers KILL_SWITCH (full pause, manual review required).

    This is the glue between monitoring/ and strategy/ layers.
    Per rule.md §7.9.8, Model Decay is a softer intervention than
    Kill Switch — first downgrade to Shadow, then escalate if needed.

    Usage:
        bridge = ModelDecayLifecycle(strategy_registry, model_decay_detector)
        bridge.set_alert_manager(AlertManager())

        result = bridge.check_and_act(
            strategy_id="momentum_v1",
            rolling_ic=0.008,  # Below 30% of training IC 0.035
        )
        if result.downgraded:
            print(f"Strategy downgraded: {result.summary()}")
    """

    # Allowable states from which to downgrade
    _DOWNGRADEABLE_STATES: tuple[StrategyLifecycle, ...] = (
        StrategyLifecycle.PRODUCTION,
        StrategyLifecycle.SHADOW_PRODUCTION,
        StrategyLifecycle.PAPER_TRADING,
        StrategyLifecycle.BACKTEST_PASSED,
    )

    def __init__(
        self,
        strategy_registry: Any = None,
        model_decay_detector: ModelDecayDetector | None = None,
    ) -> None:
        self._registry = strategy_registry
        self._detector = model_decay_detector or ModelDecayDetector(0.035)
        self._alert_manager: Any = None

    def set_alert_manager(self, alert_manager: Any) -> None:
        """Set AlertManager for sending notifications on lifecycle changes."""
        self._alert_manager = alert_manager

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def check_and_act(
        self,
        strategy_id: str,
        rolling_ic: float,
        daily_ic_series: list[float] | None = None,
        consecutive_decay_days: int = 5,
        force: bool = False,
    ) -> LifecycleAction:
        """Check model decay and automatically adjust strategy lifecycle.

        Args:
            strategy_id: Strategy to check.
            rolling_ic: Current rolling-window OOS IC.
            daily_ic_series: Optional series of daily ICs for persistence check.
            consecutive_decay_days: Days below threshold before triggering.
            force: If True, skip persistence check and act immediately.

        Returns:
            LifecycleAction describing what happened.
        """
        # Detect decay
        if daily_ic_series:
            decay_status = self._detector.check_series(
                daily_ic_series, consecutive_decay_days
            )
        elif force:
            decay_status = self._detector.check(rolling_ic)
        else:
            decay_status = self._detector.check(rolling_ic)

        # Get current lifecycle
        old_lifecycle = self._get_lifecycle(strategy_id)

        # Determine new lifecycle
        new_lifecycle = _DECAY_LIFECYCLE_MAP.get(decay_status.stage)

        # Build result
        action = LifecycleAction(
            strategy_id=strategy_id,
            decay_stage=decay_status.stage,
            old_lifecycle=old_lifecycle,
            new_lifecycle=new_lifecycle,
            ic_ratio=decay_status.ic_ratio,
            rolling_ic=decay_status.rolling_ic,
            training_ic=decay_status.training_ic_mean,
            reason=decay_status.summary,
            action=decay_status.stage.value.upper(),
        )

        # Perform lifecycle change if needed
        if (
            new_lifecycle is not None
            and old_lifecycle in self._DOWNGRADEABLE_STATES
            and new_lifecycle != old_lifecycle
        ):
            self._apply_lifecycle(strategy_id, new_lifecycle)
            action.downgraded = True
            action.reason = (
                f"Model {decay_status.stage.value}: rolling IC "
                f"{decay_status.rolling_ic:.4f} / training IC "
                f"{decay_status.training_ic_mean:.4f} = "
                f"{decay_status.ic_ratio:.0%}. "
                f"Downgraded {old_lifecycle.value} → {new_lifecycle.value}."
            )

            # Send alert
            self._send_alert(action)

        return action

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_lifecycle(self, strategy_id: str) -> StrategyLifecycle:
        """Get current lifecycle state for a strategy."""
        if self._registry is not None:
            try:
                return self._registry.get_lifecycle(strategy_id)
            except (KeyError, AttributeError):
                pass
        return StrategyLifecycle.PRODUCTION  # Default assumption

    def _apply_lifecycle(
        self,
        strategy_id: str,
        new_lifecycle: StrategyLifecycle,
    ) -> None:
        """Apply a lifecycle state change to the strategy registry."""
        if self._registry is not None:
            with contextlib.suppress(KeyError, AttributeError):
                self._registry.set_lifecycle(strategy_id, new_lifecycle)

    def _send_alert(self, action: LifecycleAction) -> None:
        """Send alert notification on lifecycle change."""
        if self._alert_manager is None:
            return

        if action.new_lifecycle == StrategyLifecycle.KILL_SWITCH:
            self._alert_manager.critical(
                title=f"Strategy KILL_SWITCH: {action.strategy_id}",
                message=action.reason,
                source="model_decay_lifecycle",
                strategy_id=action.strategy_id,
                old_state=action.old_lifecycle.value,
                new_state=action.new_lifecycle.value,
            )
        else:
            self._alert_manager.warning(
                title=f"Strategy Downgrade: {action.strategy_id}",
                message=action.reason,
                source="model_decay_lifecycle",
                strategy_id=action.strategy_id,
                old_state=action.old_lifecycle.value,
                new_state=action.new_lifecycle.value
                if action.new_lifecycle
                else "unchanged",
            )
