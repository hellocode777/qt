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
from qp.monitoring.factor_health_pipeline import FactorHealthPipeline, FactorHealthReport
from qp.monitoring.model_decay import DecayStage, ModelDecayDetector
from qp.monitoring.regime import MarketRegimeEngine, RegimeResult
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
    factor_health: FactorHealthReport | None = None
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

    @property
    def name(self) -> str:
        return "kill_switch_pipeline"

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

            # Step 3.5: Factor health (per-factor IC + decay)
            report.factor_health = self._check_factor_health(context)

            # Step 4: Strategy health
            report.strategy_health = self._check_strategy_health(context)

            # Step 5: Kill Switch
            ks_result = self._check_kill_switch(context)
            report.kill_switch_triggered = ks_result.get("triggered", False)
            report.kill_switch_triggers = ks_result.get("triggers", [])
            report._ks_result = ks_result  # type: ignore[attr-defined]

            # Determine action
            report.action = self._determine_action(report)

            # Aggregate alerts
            report.alerts = self._aggregate_alerts(report, drift_alerts)
            report.summary = self._build_summary(report)

            # Send alerts if needed
            if report.action != MonitorAction.OK:
                self._send_alert(report, logger)

            # Persist to system health log (T1 table per docs/11_12.md)
            self._log_health(report)

            # Auto-archive non-OK events to Knowledge layer (C1 per docs/11_12.md)
            self._archive_to_knowledge(report)

            # Emit retrain/weight-adjustment signal (P3 per docs/11_12.md)
            self._emit_retrain_signal(report)

            # Update system state machine (#15 fix)
            self._update_system_state(report)

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
        """Check for feature/prediction distribution drift.

        PSI compares recent window vs reference window (#5 fix).
        Reference must be explicitly set — defaults to training period.

        Reference window context (from context attributes):
          - psi_reference_window: description of reference period
            e.g. "training_2024_Q1" or "last_90_days"
        """
        alerts: list[str] = []

        psi = getattr(context, "psi_value", 0.0)
        ref_window = getattr(context, "psi_reference_window", "training_period")

        if psi >= 0.25:
            alerts.append(f"PSI {psi:.3f} ≥ 0.25 vs {ref_window} — significant feature drift")

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

    def _check_factor_health(self, context: Any) -> FactorHealthReport | None:
        """Check per-factor health (IC, decay, consistency).

        Runs FactorHealthPipeline as a sub-step. Factor health data is
        extracted from context.parameters["factor_daily_ics"] if available.
        If no factor IC data is provided, returns None gracefully.
        """
        params = getattr(context, "parameters", {}) or {}
        factor_ics = params.get("factor_daily_ics")
        if not factor_ics:
            # No factor IC data available — skip factor health check
            return None

        try:
            pipeline = FactorHealthPipeline()
            result = pipeline.run(context)
            if result.status == PipelineStatus.SUCCESS:
                return result.metadata.get("factor_health_report")  # type: ignore[return-value]
        except Exception:
            pass
        return None

    def _check_kill_switch(self, context: Any) -> dict[str, Any]:
        """Evaluate all Kill Switch triggers including P0 safety triggers."""
        from qp.monitoring.kill_switch import (
            AbnormalTurnoverTrigger,
            ConsecutiveLossTrigger,
            DrawdownTrigger,
            KillSwitch,
            ModelDecayTrigger,
            PortfolioDrawdownTrigger,
            PSITrigger,
            WeeklyDrawdownTrigger,
        )

        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger())
        ks.add_trigger(PortfolioDrawdownTrigger())
        ks.add_trigger(PSITrigger())

        # P0 safety: weekly drawdown trigger
        ks.add_trigger(WeeklyDrawdownTrigger(weekly_limit=0.05))

        # P0 safety: consecutive loss trigger
        ks.add_trigger(ConsecutiveLossTrigger(consecutive_days=5))

        # P0 safety: abnormal turnover trigger (code bug protection)
        ks.add_trigger(AbnormalTurnoverTrigger(turnover_ratio=0.80))

        # Model Decay trigger — links monitoring to kill switch
        training_ic = getattr(context, "training_ic_mean", 0.035)
        ks.add_trigger(
            ModelDecayTrigger(
                training_ic_mean=training_ic,
                decay_ratio=0.30,
                warning_ratio=0.50,
            )
        )

        # Build metrics from context
        metrics = {
            "current_drawdown": getattr(context, "current_drawdown", 0.0),
            "monthly_return": getattr(context, "monthly_return", 0.0),
            "rolling_60d_drawdown": getattr(context, "rolling_60d_drawdown", 0.0),
            "psi": getattr(context, "psi_value", 0.0),
            "rolling_ic": getattr(context, "rolling_ic", 0.0),
            "training_ic_mean": training_ic,
            # P0 safety metrics
            "weekly_drawdown": getattr(context, "weekly_drawdown", 0.0),
            "consecutive_loss_days": getattr(context, "consecutive_loss_days", 0),
            "daily_trade_count": getattr(context, "daily_trade_count", 0),
            "total_holdings": getattr(context, "total_holdings", 1),
        }

        result = ks.check(**metrics)
        return {
            "triggered": result.triggered,
            "triggers": result.triggers,
            "recommendation": result.recommendation,
            "level": result.level,
        }

    # ------------------------------------------------------------------
    # Action determination
    # ------------------------------------------------------------------

    def _determine_action(self, report: MonitorReport) -> MonitorAction:
        """Determine the escalation level from all checks.

        Priority: Kill Switch (FULL_STOP > HALT_BUY > WARNING) > Model Decay > Strategy Health > Regime.

        Maps KillSwitchLevel to MonitorAction:
          FULL_STOP → STOP
          HALT_BUY  → PAUSE_BUY
          WARNING   → WATCH
          NORMAL    → (continue to next check)
        """
        # 1. Kill Switch escalation (highest priority)
        ks_result = getattr(report, "_ks_result", None)
        if ks_result is not None:
            from qp.monitoring.kill_switch import KillSwitchLevel

            ks_level = ks_result.get("level", KillSwitchLevel.NORMAL)
            if ks_level == KillSwitchLevel.FULL_STOP:
                return MonitorAction.STOP
            if ks_level == KillSwitchLevel.HALT_BUY:
                return MonitorAction.PAUSE_BUY
            if ks_level == KillSwitchLevel.WARNING:
                return MonitorAction.WATCH

        # 1b. Legacy: Kill Switch triggered
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

        # 3.5. Factor health — escalate if majority of factors are degraded
        if report.factor_health and report.factor_health.has_degradation:
            total = len(report.factor_health.factors)
            degraded = report.factor_health.n_degraded + report.factor_health.n_stale
            if total > 0 and degraded / total >= 0.50:
                return MonitorAction.WATCH

        # 4. Regime context — logged but does NOT trigger kill switch (#4 fix)
        #    Market regime is information, not a risk event.
        #    LIQUIDITY_CRUNCH and STYLE_REVERSAL are noted in the summary
        #    but do not automatically halt trading.

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

        if report.factor_health and report.factor_health.alerts:
            alerts.extend(report.factor_health.alerts)

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

        if report.factor_health:
            parts.append(
                f"Factors={report.factor_health.n_healthy}H/"
                f"{report.factor_health.n_warning}W/"
                f"{report.factor_health.n_degraded}D/"
                f"{report.factor_health.n_stale}S"
            )

        return " | ".join(parts)

    def _log_health(self, report: MonitorReport) -> None:
        """Persist daily health snapshot to system_health_log (Parquet)."""
        try:
            from qp.monitoring.health_logger import SystemHealthLogger

            health_logger = SystemHealthLogger()
            health_logger.log_from_report(report)
        except Exception:
            pass  # Health logging is best-effort, never blocks the pipeline

    def _archive_to_knowledge(self, report: MonitorReport) -> None:
        """Auto-archive significant events to KnowledgeArchive (#14 fix).

        Only archives on PAUSE_BUY, REDUCE, or STOP — WATCH is informational
        and should not generate noise. Creates failure_analysis entries when
        Kill Switch fires at actionable levels.
        """
        if report.action in (MonitorAction.OK, MonitorAction.WATCH):
            return  # Don't archive routine or watch-only events

        try:
            from qp.knowledge.archive import KnowledgeArchive

            archive = KnowledgeArchive()

            # Build event summary from report
            regime_str = report.regime.regime.value if report.regime else "UNKNOWN"
            triggers_str = (
                ", ".join(report.kill_switch_triggers) if report.kill_switch_triggers else "none"
            )

            event_summary = (
                f"**Action**: {report.action.value}\n"
                f"**Regime**: {regime_str}\n"
                f"**Kill Switch Triggers**: {triggers_str}\n"
                f"**Model Decay Stage**: {report.model_decay_stage}\n"
                f"**PSI**: {report.psi_value:.3f}\n"
                f"**Health Score**: {report.strategy_health.health_score:.0f}"
                if report.strategy_health
                else "N/A"
            )

            root_cause = (
                f"Monitoring pipeline detected escalation to {report.action.value}. "
                f"Market regime was {regime_str}. "
                + (f"Triggers: {triggers_str}." if triggers_str != "none" else "No KS triggers.")
            )

            severity = "4" if report.action in (MonitorAction.STOP, MonitorAction.REDUCE) else "2"

            archive.create_failure_analysis(
                title=f"KillSwitch: {report.action.value} on {report.timestamp[:10]}",
                event_summary=event_summary,
                root_cause=root_cause,
                impact=f"Action taken: {report.action.value}. See system_health_log for full context.",
                category="Market Regime"
                if report.regime and report.regime.is_crisis
                else "Implementation",
                severity=severity,
                tags=[
                    "auto-archived",
                    "kill-switch",
                    report.action.value.lower(),
                    regime_str.lower(),
                ],
            )
        except Exception:
            pass  # Archive is best-effort, never blocks the pipeline

    def _update_system_state(self, report: MonitorReport) -> None:
        """Update cross-pipeline system state (#15 fix).

        After each KillSwitchPipeline run, transition the SystemState
        based on the determined action. Downstream pipelines (DailyPipeline)
        read this state before executing.
        """
        try:
            from qp.monitoring.system_state import SystemStateManager

            mgr = SystemStateManager()
            regime_str = report.regime.regime.value if report.regime else "UNKNOWN"
            reason = (
                f"KillSwitchPipeline: action={report.action.value} "
                f"regime={regime_str} psi={report.psi_value:.3f}"
            )
            details = ""
            if report.kill_switch_triggers:
                details = "triggers: " + ", ".join(report.kill_switch_triggers[:3])

            mgr.auto_transition(
                monitor_action=report.action.value,
                reason=reason,
                source="KillSwitchPipeline",
                details=details,
            )
        except Exception:
            pass  # Best-effort — state machine failure should not block pipeline

    def _emit_retrain_signal(self, report: MonitorReport) -> None:
        """Emit retrain/weight-adjustment signal based on monitoring state.

        Evaluates PSI drift, IC decay, and model decay stage to determine
        if retraining or weight reduction is needed (L11-1.5, L11-1.7).
        """
        try:
            from qp.monitoring.retrain_signal import (
                RetrainSignalLogger,
                evaluate_retrain_need,
            )

            regime_str = report.regime.regime.value if report.regime else "UNKNOWN"

            signal = evaluate_retrain_need(
                strategy_name=getattr(report, "strategy_name", ""),
                psi_value=report.psi_value,
                rolling_ic=getattr(report, "rolling_ic", 0.0),
                training_ic=0.035,
                current_regime=regime_str,
                model_decay_stage=str(report.model_decay_stage),
            )

            if signal.is_actionable():
                logger = RetrainSignalLogger()
                logger.log(signal)
        except Exception:
            pass  # Best-effort

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
