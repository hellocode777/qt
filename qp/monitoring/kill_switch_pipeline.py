"""KillSwitchPipeline — daily automated safety check pipeline.

Runs all monitoring checks in sequence:
  1. Market Regime detection
  2. Drift detection (PSI + prediction distribution)
  3. Model Decay detection (rolling IC ratio)
  4. Strategy Health check (signals, turnover, drawdown)
  5. Kill Switch evaluation (drawdown/portfolio/PSI triggers)

Extends BasePipeline so it can be scheduled via the scheduler.

Relationship:
  - Model Decay: model-level early warning → triggers retrain
  - Kill Switch: strategy/portfolio-level final defense → pauses trading

Usage:
    pipeline = KillSwitchPipeline()
    result = pipeline.run(context)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from qp.monitoring.alerts import AlertManager, AlertSeverity
from qp.monitoring.model_decay import DecayStage, ModelDecayDetector
from qp.monitoring.regime import MarketRegimeEngine, Regime, RegimeResult
from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth
from qp.platform.pipeline.result import PipelineResult
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus


class MonitorAction(StrEnum):
    """Actions recommended by the Kill Switch Pipeline."""
    OK = "ok"  # All clear
    WATCH = "watch"  # Minor concern — increase monitoring
    PAUSE_BUY = "pause_buy"  # Stop new positions
    REDUCE = "reduce"  # Reduce existing positions
    STOP = "stop"  # Full stop — liquidate positions


@dataclass
class MonitorReport:
    """Aggregated monitoring report from a single pipeline run.

    Attributes:
        run_id: Pipeline run identifier.
        timestamp: When the check was performed.
        action: Recommended action.
        regime: Current market regime.
        kill_switch_triggered: Whether Kill Switch fired.
        kill_switch_triggers: Which triggers fired.
        model_decay_stage: Current model decay stage.
        strategy_health: Strategy health report.
        psi_value: Current PSI value.
        alerts: Active alerts.
        summary: One-line summary.
    """

    run_id: str = ""
    timestamp: str = ""
    action: MonitorAction = MonitorAction.OK
    regime: RegimeResult | None = None
    kill_switch_triggered: bool = False
    kill_switch_triggers: list[str] = field(default_factory=list)
    model_decay_stage: DecayStage = DecayStage.HEALTHY
    strategy_health: StrategyHealth | None = None
    psi_value: float = 0.0
    alerts: list[str] = field(default_factory=list)
    summary: str = ""


class KillSwitchPipeline(BasePipeline):
    """Daily automated monitoring and safety check pipeline.

    Runs checks, generates a MonitorReport, and sends alerts if thresholds
    are breached. Can be scheduled as a daily job.

    Usage:
        pipeline = KillSwitchPipeline(alert_manager=alerts)
        result = pipeline.run(context)
        # → PipelineResult with MonitorReport
    """

    def __init__(
        self,
        alert_manager: AlertManager | None = None,
        model_decay_detector: ModelDecayDetector | None = None,
        regime_engine: MarketRegimeEngine | None = None,
    ) -> None:
        super().__init__()
        self._alerts = alert_manager or AlertManager()
        self._model_decay = model_decay_detector
        self._regime_engine = regime_engine or MarketRegimeEngine()

    # ------------------------------------------------------------------
    # Pipeline interface
    # ------------------------------------------------------------------

    def run(self, context: Any) -> Any:
        """Execute the Kill Switch pipeline.

        Args:
            context: PipelineContext with runtime info.

        Returns:
            PipelineResult with MonitorReport as artifact.
        """

        run_id = getattr(context, "run_id", "ks-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
        logger = getattr(context, "logger", None)

        report = MonitorReport(
            run_id=run_id,
            timestamp=datetime.now(UTC).isoformat(),
        )

        try:
            # Step 1: Market Regime
            report.regime = self._check_regime(context)

            # Step 2: Drift detection
            psi, drift_alerts = self._check_drift(context)
            report.psi_value = psi

            # Step 3: Model decay
            report.model_decay_stage = self._check_model_decay(context)

            # Step 4: Strategy health
            report.strategy_health = self._check_strategy_health(context)

            # Step 5: Kill Switch
            ks_result = self._check_kill_switch(context)
            report.kill_switch_triggered = ks_result.get("triggered", False)
            report.kill_switch_triggers = ks_result.get("triggers", [])

            # Determine action
            report.action = self._determine_action(report)

            # Aggregate alerts
            report.alerts = self._aggregate_alerts(report, drift_alerts)
            report.summary = self._build_summary(report)

            # Send alerts if needed
            if report.action != MonitorAction.OK:
                self._send_alert(report, logger)

            if logger:
                logger.info(f"KillSwitchPipeline complete: {report.summary}")

            result = PipelineResult(status=PipelineStatus.SUCCESS)
            result.metrics = {
                "psi": report.psi_value,
                "kill_switch_triggered": float(report.kill_switch_triggered),
            }
            result.artifacts = ["MonitorReport"]
            result.metadata = {
                "action": report.action.value,
                "report": report,  # type: ignore[dict-item]
            }
            return result

        except Exception as exc:
            if logger:
                logger.error(f"KillSwitchPipeline failed: {exc}")

            result = PipelineResult(status=PipelineStatus.FAILED)
            result.errors = [str(exc)]
            return result

    # ------------------------------------------------------------------
    # Check methods — each can be overridden or extended
    # ------------------------------------------------------------------

    def _check_regime(self, context: Any) -> RegimeResult | None:
        """Detect current market regime from price data."""
        prices = getattr(context, "price_data", None)
        if prices is None:
            return None
        return self._regime_engine.classify(prices)

    def _check_drift(self, context: Any) -> tuple[float, list[str]]:
        """Check for feature/prediction distribution drift."""
        alerts: list[str] = []

        psi = getattr(context, "psi_value", 0.0)
        if psi >= 0.25:
            alerts.append(f"PSI {psi:.3f} ≥ 0.25 — significant feature drift")

        return psi, alerts

    def _check_model_decay(self, context: Any) -> DecayStage:
        """Check for model performance decay."""
        if self._model_decay is None:
            return DecayStage.HEALTHY

        rolling_ic = getattr(context, "rolling_ic", None)
        if rolling_ic is None:
            return DecayStage.HEALTHY

        status = self._model_decay.check(rolling_ic)
        return status.stage

    def _check_strategy_health(self, context: Any) -> StrategyHealth | None:
        """Check strategy health metrics."""
        monitor = getattr(context, "strategy_monitor", None)
        if monitor is None:
            return None
        return monitor.health_check()

    def _check_kill_switch(self, context: Any) -> dict[str, Any]:
        """Evaluate all Kill Switch triggers."""
        from qp.monitoring.kill_switch import KillSwitch

        ks = KillSwitch()
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            PortfolioDrawdownTrigger,
            PSITrigger,
        )
        ks.add_trigger(DrawdownTrigger())
        ks.add_trigger(PortfolioDrawdownTrigger())
        ks.add_trigger(PSITrigger())

        # Build metrics from context
        metrics = {
            "current_drawdown": getattr(context, "current_drawdown", 0.0),
            "monthly_return": getattr(context, "monthly_return", 0.0),
            "rolling_60d_drawdown": getattr(context, "rolling_60d_drawdown", 0.0),
            "psi": getattr(context, "psi_value", 0.0),
        }

        result = ks.check(**metrics)
        return {
            "triggered": result.triggered,
            "triggers": result.triggers,
            "recommendation": result.recommendation,
        }

    # ------------------------------------------------------------------
    # Action determination
    # ------------------------------------------------------------------

    def _determine_action(self, report: MonitorReport) -> MonitorAction:
        """Determine the escalation level from all checks.

        Priority: Kill Switch > Model Decay > Strategy Health > Regime.
        """
        # 1. Kill Switch is highest priority
        if report.kill_switch_triggered:
            return MonitorAction.PAUSE_BUY
        if report.psi_value >= 0.25:
            return MonitorAction.PAUSE_BUY

        # 2. Model Decay
        if report.model_decay_stage == DecayStage.STALE:
            return MonitorAction.STOP
        if report.model_decay_stage == DecayStage.DECAYING:
            return MonitorAction.REDUCE
        if report.model_decay_stage == DecayStage.WARNING:
            return MonitorAction.WATCH

        # 3. Strategy health
        if report.strategy_health and report.strategy_health.needs_attention:
            if report.strategy_health.health_level == HealthLevel.CRITICAL:
                return MonitorAction.PAUSE_BUY
            return MonitorAction.WATCH

        # 4. High vol regime
        if report.regime and report.regime.regime == Regime.HIGH_VOL:
            return MonitorAction.WATCH

        return MonitorAction.OK

    def _aggregate_alerts(
        self,
        report: MonitorReport,
        drift_alerts: list[str],
    ) -> list[str]:
        """Collect all alerts into a single list."""
        alerts = list(drift_alerts)

        if report.kill_switch_triggered:
            alerts.extend(report.kill_switch_triggers)

        if report.model_decay_stage in (DecayStage.DECAYING, DecayStage.STALE):
            alerts.append(f"Model {report.model_decay_stage.value} — needs retraining")

        if report.strategy_health and report.strategy_health.alerts:
            alerts.extend(report.strategy_health.alerts)

        return alerts

    def _build_summary(self, report: MonitorReport) -> str:
        """Build one-line summary."""
        parts = [f"Action={report.action.value.upper()}"]

        if report.regime:
            parts.append(f"Regime={report.regime.regime.value}")
        if report.kill_switch_triggered:
            parts.append(f"KS={len(report.kill_switch_triggers)} triggers")
        parts.append(f"Decay={report.model_decay_stage.value}")

        if report.strategy_health:
            parts.append(f"Health={report.strategy_health.health_score:.0f}")

        return " | ".join(parts)

    def _send_alert(self, report: MonitorReport, logger: object | None) -> None:
        """Route alerts through the AlertManager."""
        severity = AlertSeverity.WARNING
        if report.action in (MonitorAction.STOP, MonitorAction.REDUCE):
            severity = AlertSeverity.CRITICAL

        alert_title = f"KillSwitch: {report.action.value.upper()}"
        alert_message = report.summary
        alert_source = "kill_switch_pipeline"
        extra = {"triggers": ", ".join(report.alerts) if report.alerts else "none"}

        if severity == AlertSeverity.CRITICAL:
            self._alerts.critical(alert_title, alert_message, alert_source, **extra)
        else:
            self._alerts.warning(alert_title, alert_message, alert_source, **extra)
