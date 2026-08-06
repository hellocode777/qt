"""Gate → Registry Bridge — auto lifecycle management from Validation Gate.

DP-002 §4.5, V11: When a factor passes/fails the Validation Gate, its
lifecycle in the StrategyRegistry must be updated automatically:
  - PASSED → BACKTEST_PASSED (or advance to next stage)
  - RESEARCH_ONLY → RESEARCH (has predictive power but fails portfolio checks)
  - BLOCKED → DEPRECATED (fails data/factor checks — needs fixes)

This module bridges the Validation Layer and Strategy Registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from qp.shared.types import StrategyLifecycle
from qp.validation.result import GateDecision, GateResult

if TYPE_CHECKING:
    from qp.strategy.registry import StrategyRegistry

# ------------------------------------------------------------------
# GateDecision → StrategyLifecycle mapping
# ------------------------------------------------------------------

GATE_TO_LIFECYCLE: dict[GateDecision, StrategyLifecycle] = {
    GateDecision.PASSED: StrategyLifecycle.BACKTEST_PASSED,
    GateDecision.RESEARCH_ONLY: StrategyLifecycle.RESEARCH,
    GateDecision.BLOCKED: StrategyLifecycle.DEPRECATED,
    # OVERRIDDEN: no automatic promotion — human decision overrides
}

LIFECYCLE_TRANSITION_LOG: dict[tuple[StrategyLifecycle, GateDecision], StrategyLifecycle] = {
    # Current state → Gate decision → New state
    (
        StrategyLifecycle.RESEARCH,
        GateDecision.PASSED,
    ): StrategyLifecycle.BACKTEST_PASSED,
    (
        StrategyLifecycle.BACKTEST_PASSED,
        GateDecision.PASSED,
    ): StrategyLifecycle.PAPER_TRADING,
    (StrategyLifecycle.PAPER_TRADING, GateDecision.PASSED): StrategyLifecycle.APPROVED,
    # Degradation paths
    (
        StrategyLifecycle.BACKTEST_PASSED,
        GateDecision.BLOCKED,
    ): StrategyLifecycle.DEPRECATED,
    (
        StrategyLifecycle.PAPER_TRADING,
        GateDecision.BLOCKED,
    ): StrategyLifecycle.BACKTEST_PASSED,
    (StrategyLifecycle.PRODUCTION, GateDecision.BLOCKED): StrategyLifecycle.WARNING,
}


# ------------------------------------------------------------------
# Bridge
# ------------------------------------------------------------------


class GateRegistryBridge:
    """Bridges Validation Gate output to StrategyRegistry lifecycle updates.

    Usage:
        bridge = GateRegistryBridge(registry)
        gate_result = GateResult(
            strategy_id="alpha_ensemble_v2",
            stage="backtest_passed",
            decision=GateDecision.PASSED,
            score=85.0,
            confidence=0.95,
        )
        bridge.apply(gate_result)
    """

    def __init__(self, registry: StrategyRegistry | None = None) -> None:
        self._registry = registry

    @property
    def registry(self) -> StrategyRegistry | None:
        return self._registry

    def set_registry(self, registry: StrategyRegistry) -> None:
        """Attach a StrategyRegistry for lifecycle updates."""
        self._registry = registry

    # ------------------------------------------------------------------
    # Apply gate result to registry
    # ------------------------------------------------------------------

    def apply(self, gate_result: GateResult) -> bool:
        """Apply a Validation Gate result to the Strategy Registry.

        Updates the strategy's lifecycle based on the GateDecision.
        If no registry is attached, logs the decision but takes no action.

        Args:
            gate_result: GateResult from Validation Gate evaluation.

        Returns:
            True if the lifecycle was updated, False otherwise.
        """
        strategy_id = gate_result.strategy_id
        decision = gate_result.decision

        if self._registry is None:
            logger.warning(
                "GateRegistryBridge: no registry attached. "
                "Gate decision '{}' for '{}' not applied.",
                decision.value,
                strategy_id,
            )
            return False

        # Check if strategy exists in registry
        try:
            current_lifecycle = self._registry.get_lifecycle(strategy_id)
        except KeyError:
            logger.warning(
                "GateRegistryBridge: strategy '{}' not in registry. "
                "Register it first before applying gate results.",
                strategy_id,
            )
            return False

        # Determine target lifecycle
        target_lifecycle = self._resolve_lifecycle(current_lifecycle, decision)

        if target_lifecycle == current_lifecycle:
            logger.info(
                "GateRegistryBridge: '{}' lifecycle unchanged ({}) — gate decision '{}'",
                strategy_id,
                current_lifecycle.value,
                decision.value,
            )
            return False

        # Apply lifecycle update
        try:
            self._registry.set_lifecycle(strategy_id, target_lifecycle)
            logger.info(
                "GateRegistryBridge: '{}' {} → {} (gate={}, score={:.0f})",
                strategy_id,
                current_lifecycle.value,
                target_lifecycle.value,
                decision.value,
                gate_result.score,
            )

            # Update metadata with gate results
            self._update_meta_from_gate(strategy_id, gate_result)

            return True

        except Exception as exc:
            logger.error(
                "GateRegistryBridge: failed to update lifecycle for '{}': {}",
                strategy_id,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Lifecycle resolution
    # ------------------------------------------------------------------

    def _resolve_lifecycle(
        self,
        current: StrategyLifecycle,
        decision: GateDecision,
    ) -> StrategyLifecycle:
        """Determine target lifecycle from current state + gate decision.

        Uses the transition table first, then falls back to the simple
        GATE_TO_LIFECYCLE mapping.

        Args:
            current: Current lifecycle state.
            decision: Gate decision to apply.

        Returns:
            Target lifecycle state.
        """
        # Check transition table first (state-aware)
        transition = LIFECYCLE_TRANSITION_LOG.get((current, decision))
        if transition is not None:
            return transition

        # Fallback: simple mapping (ignores current state)
        fallback = GATE_TO_LIFECYCLE.get(decision)
        if fallback is not None:
            return fallback

        # OVERRIDDEN: keep current state
        return current

    # ------------------------------------------------------------------
    # Metadata sync
    # ------------------------------------------------------------------

    def _update_meta_from_gate(self, strategy_id: str, gate_result: GateResult) -> None:
        """Update strategy metadata with gate evaluation results.

        Args:
            strategy_id: Strategy to update.
            gate_result: GateResult to record in metadata.
        """
        if self._registry is None:
            return

        try:
            meta = self._registry.get_meta(strategy_id)
        except KeyError:
            return

        # Store gate-level metadata in StrategyMeta tags/description
        existing_tags = set(meta.tags)
        if gate_result.passed:
            existing_tags.add("gate:passed")
            existing_tags.discard("gate:failed")
        else:
            existing_tags.add("gate:failed")
            existing_tags.discard("gate:passed")

        # Add decision-specific tag
        existing_tags.add(f"gate:{gate_result.decision.value}")

        meta.tags = sorted(existing_tags)
        meta.backtest_ic = gate_result.score / 100.0  # Normalize score to IC-like
        meta.description = (
            f"{meta.description}\n"
            f"[Gate {gate_result.stage}] {gate_result.decision.value.upper()} "
            f"(score={gate_result.score:.0f}, confidence={gate_result.confidence:.0%})"
        ).strip()

        try:
            self._registry.set_meta(strategy_id, meta)
        except Exception as exc:
            logger.warning(
                "GateRegistryBridge: failed to update meta for '{}': {}",
                strategy_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def apply_batch(self, gate_results: list[GateResult]) -> dict[str, bool]:
        """Apply multiple gate results at once.

        Args:
            gate_results: List of GateResults to apply.

        Returns:
            Dict mapping strategy_id → success status.
        """
        results: dict[str, bool] = {}
        for gr in gate_results:
            results[gr.strategy_id] = self.apply(gr)
        return results

    def sync_from_experiment(
        self,
        strategy_id: str,
        metrics: dict[str, float],
        stage: str = "backtest_passed",
    ) -> GateResult:
        """Build and apply a GateResult from experiment metrics.

        Convenience for the pipeline flow: experiment → gate → registry.

        Args:
            strategy_id: Strategy identifier.
            metrics: Dict with keys like ic_mean, ic_ir, sharpe_ratio, etc.
            stage: Lifecycle stage.

        Returns:
            GateResult that was applied to the registry.
        """
        # Determine gate decision from metrics
        ic_mean = abs(metrics.get("ic_mean", 0.0))
        ic_ir = abs(metrics.get("ic_ir", 0.0))
        sharpe = metrics.get("sharpe_ratio", 0.0)
        max_dd = metrics.get("max_drawdown_pct", 100.0)

        # Factor quality assessment
        factor_pass = ic_mean >= 0.02 and ic_ir >= 0.3
        portfolio_pass = sharpe >= 0.5 and max_dd <= 30.0

        if factor_pass and portfolio_pass:
            decision = GateDecision.PASSED
        elif factor_pass and not portfolio_pass:
            decision = GateDecision.RESEARCH_ONLY
        else:
            decision = GateDecision.BLOCKED

        score = min(100.0, (ic_ir / 1.0) * 50.0 + (sharpe / 2.0) * 50.0)
        confidence = min(1.0, abs(ic_mean) / 0.10)

        gate_result = GateResult(
            strategy_id=strategy_id,
            stage=stage,
            decision=decision,
            score=round(score, 2),
            confidence=round(confidence, 2),
            factor_validity="PASS" if factor_pass else "FAIL",
            portfolio_conversion="PASS" if portfolio_pass else "FAIL",
            recommendation=(
                "All checks passed — strategy ready for next stage."
                if decision == GateDecision.PASSED
                else (
                    "Factor has predictive power but portfolio conversion is weak."
                    if decision == GateDecision.RESEARCH_ONLY
                    else "Factor/data checks failed — fix issues and re-run."
                )
            ),
        )

        self.apply(gate_result)
        return gate_result


# ------------------------------------------------------------------
# Standalone helper — gate an experiment result directly
# ------------------------------------------------------------------


def gate_and_promote(
    strategy_id: str,
    experiment_metrics: dict[str, float],
    registry: StrategyRegistry | None = None,
    stage: str = "backtest_passed",
) -> GateResult:
    """One-shot: gate an experiment result and auto-promote in registry.

    Args:
        strategy_id: Strategy identifier.
        experiment_metrics: Dict from experiment.metrics (ic_mean, ic_ir, sharpe, etc.).
        registry: StrategyRegistry to update. None = log only.
        stage: Lifecycle stage for the gate check.

    Returns:
        GateResult with the evaluation and lifecycle decision.
    """
    bridge = GateRegistryBridge(registry)
    return bridge.sync_from_experiment(strategy_id, experiment_metrics, stage)
