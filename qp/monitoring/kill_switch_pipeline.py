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

from loguru import logger

from qp.monitoring.alerts import AlertManager, AlertSeverity
from qp.monitoring.factor_health_pipeline import (
    FactorHealthPipeline,
    FactorHealthReport,
)
from qp.monitoring.model_decay import DecayStage, ModelDecayDetector
from qp.monitoring.regime import MarketRegimeEngine, RegimeResult
from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth
from qp.platform.pipeline.result import PipelineResult
from qp.shared.paths import ONLINE_SIGNAL_HISTORY
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.time import fmt_ts
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
    psi_available: bool = False
    rolling_ic: float = 0.0
    rolling_ic_available: bool = False
    strategy_name: str = ""
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
        knowledge_archive: Any | None = None,
    ) -> None:
        super().__init__()
        self._alerts = alert_manager or AlertManager()
        self._model_decay = model_decay_detector
        self._regime_engine = regime_engine or MarketRegimeEngine()
        self._last_monitored_strategy: str = ""
        # 注入知识库归档器（上层组合根传入），避免 monitoring→knowledge 向上依赖。
        # None 时回退 lazy import（保持调度器/CLI 兼容）。
        self._knowledge_archive = knowledge_archive

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

        run_id = getattr(context, "run_id", "ks-" + fmt_ts(datetime.now(UTC), sep="-"))
        logger = getattr(context, "logger", None)

        report = MonitorReport(
            run_id=run_id,
            timestamp=datetime.now(UTC).isoformat(),
        )

        try:
            # Step 1: Market Regime
            report.regime = self._check_regime(context)

            # Step 2: Drift detection — real PSI from signal-score
            # distributions (or caller-supplied value).
            psi, psi_available, drift_alerts = self._check_drift(context)
            report.psi_value = psi
            report.psi_available = psi_available

            # Step 2.5: Online signal health — realized rolling IC from
            # accumulated daily signal history (real value, not a 0.0 stub).
            # Computed BEFORE model decay so decay uses the real IC.
            report.rolling_ic, report.rolling_ic_available = self._check_online_signal_health(
                context
            )
            report.strategy_name = self._last_monitored_strategy or ""

            # Step 3: Model decay (uses realized IC when available;
            # when IC is unavailable the stage stays HEALTHY = "not
            # measured", never a fabricated DECAYING/STALE verdict).
            report.model_decay_stage = self._check_model_decay(
                context, report.rolling_ic if report.rolling_ic_available else None
            )

            # Step 3.5: Factor health (per-factor IC + decay)
            report.factor_health = self._check_factor_health(context)

            # Step 4: Strategy health
            report.strategy_health = self._check_strategy_health(context)

            # Step 5: Kill Switch
            ks_result = self._check_kill_switch(
                context,
                psi=report.psi_value,
                rolling_ic=report.rolling_ic,
            )
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
        """Detect current market regime from price data.

        Accepts either a single-series DataFrame (index/baseline) or a
        ``{symbol: DataFrame}`` dict. For dicts, the same equal-weighted
        synthetic index that DailyPipeline uses (``_build_index_df``) is
        built — so KillSwitch and the decision package read the same
        market signal instead of one seeing BEAR and the other UNKNOWN.
        """
        prices = self._get_price_data(context)
        if prices is None:
            return None
        n_limit_down = 0
        if isinstance(prices, dict):
            try:
                # Deferred import: daily_pipeline imports monitoring
                # modules at module level, so importing it here (runtime)
                # avoids an import cycle.
                from qp.pipeline.daily_pipeline import _build_index_df

                # Count whole-market limit-downs on the latest day from the
                # cross-section BEFORE flattening to a synthetic index.
                n_limit_down = MarketRegimeEngine.compute_limit_down_count(
                    MarketRegimeEngine._cross_section_latest_returns(prices)
                )
                index_df = _build_index_df(prices)
            except Exception:
                index_df = None
            if index_df is None or index_df.is_empty():
                return None
            prices = index_df
        return self._regime_engine.classify(prices, n_limit_down=n_limit_down or None)

    @staticmethod
    def _get_price_data(context: Any) -> Any:
        """Read price data from context — attribute or parameters.

        Callers historically attached ``price_data`` as a context attribute
        (``PipelineContext(pipeline_name=..., price_data=...)``), while
        scheduler/CLI build contexts via ``parameters={...}``.  Read both
        so regime detection and online-IC monitoring get real market data
        regardless of how the context was constructed.
        """
        prices = getattr(context, "price_data", None)
        if prices is None:
            params = getattr(context, "parameters", {}) or {}
            prices = params.get("price_data")
        return prices

    def _check_drift(self, context: Any) -> tuple[float, bool, list[str]]:
        """Check for feature/prediction distribution drift.

        PSI compares the recent window vs reference window. The caller
        may supply an explicit ``psi_value`` (computed upstream); otherwise
        PSI is computed from the persisted online signal-score history
        (recent 20 signal days vs preceding 20 days as reference).

        Returns:
            (psi, available, alerts). ``available=False`` means no PSI
            could be computed — the 0.0 is a data gap, not "no drift".
        """
        alerts: list[str] = []

        supplied = getattr(context, "psi_value", None)
        if isinstance(supplied, (int, float)):
            psi = float(supplied)
            available = True
            ref_window = getattr(context, "psi_reference_window", "training_period")
        else:
            psi, available = self._compute_signal_psi()
            ref_window = "signal_history"

        if available and psi >= 0.25:
            alerts.append(f"PSI {psi:.3f} ≥ 0.25 vs {ref_window} — significant feature drift")

        return psi, available, alerts

    def _compute_signal_psi(self) -> tuple[float, bool]:
        """Compute PSI between recent and reference signal-score distributions.

        Uses the persisted online signal history: the most recent 20 signal
        days are the "actual" (production) distribution, the preceding 20
        days are the "expected" (reference) distribution. Computed per
        strategy; the worst (largest) PSI wins. Returns (psi, available);
        ``available=False`` when no strategy has at least 4 signal days.
        """
        try:
            from pathlib import Path

            import polars as pl

            from qp.monitoring.drift import DriftMonitor

            signal_path = Path(ONLINE_SIGNAL_HISTORY)
            if not signal_path.exists():
                return 0.0, False

            df = pl.read_parquet(signal_path)
            if df is None or "raw_score" not in df.columns:
                return 0.0, False

            # Score-distribution drift is a property of the whole ranking,
            # not of the day's few candidate signals.  Prefer the sampled
            # cross-section rows (kind="universe") when present.
            if "kind" in df.columns:
                df = df.filter(pl.col("kind") == "universe")
                if df.is_empty():
                    return 0.0, False

            best = 0.0
            any_computed = False
            for sid in df["strategy_id"].unique().to_list():
                sdf = df.filter(pl.col("strategy_id") == sid)
                dates = sdf.select("date").unique().sort("date")["date"].to_list()
                if len(dates) < 4:
                    continue
                actual_dates = dates[-20:]
                ref_dates = dates[-40:-20] if len(dates) >= 40 else dates[: len(dates) - 20]
                if len(actual_dates) < 2 or len(ref_dates) < 2:
                    continue
                actual = sdf.filter(pl.col("date").is_in(actual_dates))["raw_score"].to_numpy()
                expected = sdf.filter(pl.col("date").is_in(ref_dates))["raw_score"].to_numpy()
                if len(actual) < 2 or len(expected) < 2:
                    continue
                any_computed = True
                psi = DriftMonitor.compute_psi(expected, actual)
                best = max(best, psi)
            return best, any_computed
        except Exception:
            return 0.0, False

    def _check_model_decay(
        self,
        context: Any,
        rolling_ic: float | None = None,
    ) -> DecayStage:
        """Check for model performance decay.

        Args:
            context: Pipeline context (kept for future use / compatibility).
            rolling_ic: Realized rolling IC from online signal health.
                ``None`` (or an unset context value) means IC is unavailable
                — the stage stays HEALTHY ("not measured"), never a
                fabricated DECAYING/STALE verdict.
        """
        if self._model_decay is None:
            return DecayStage.HEALTHY

        if rolling_ic is None:
            rolling_ic = getattr(context, "rolling_ic", None)
        if rolling_ic is None:
            return DecayStage.HEALTHY

        status = self._model_decay.check(rolling_ic)
        return status.stage

    def _check_strategy_health(self, context: Any) -> StrategyHealth | None:
        """Check strategy health metrics.

        Reads the monitor from context attribute or ``parameters`` (both
        construction styles are used by scheduler/CLI).
        """
        monitor = getattr(context, "strategy_monitor", None)
        if monitor is None:
            params = getattr(context, "parameters", {}) or {}
            monitor = params.get("strategy_monitor")
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

    def _check_online_signal_health(self, context: Any) -> tuple[float, bool]:
        """Compute realized rolling IC from online signal history.

        Reads the accumulated daily signal snapshots (written by the daily
        pipeline) and computes the 20-day mean rank IC against price data.

        Returns:
            (rolling_ic_20d, available). ``available=False`` means the IC
            was never computed — no price data in context, or fewer than 5
            signal days in history.  A 0.0 IC with available=False is a
            data gap, NOT model decay, and callers must not alarm on it.
        """
        self._last_monitored_strategy = ""
        try:
            prices = self._get_price_data(context)
            if not prices:
                return 0.0, False

            from qp.monitoring.online_monitor import OnlineSignalMonitor
            from qp.strategy.registry import StrategyRegistry

            registry = StrategyRegistry()
            candidates = registry.list_strategies()
            if not candidates:
                return 0.0, False

            monitor = OnlineSignalMonitor()
            # First candidate with signal history wins; prefer one whose
            # realized IC is actually non-zero (a 0.0 usually means the
            # signal/price join produced no IC values for that strategy).
            first_available: tuple[str, float] | None = None
            for sid in candidates:
                ic = monitor.rolling_ic(sid, prices, window=20)
                if ic is None:
                    continue
                if first_available is None:
                    first_available = (sid, float(ic))
                if ic != 0.0:
                    self._last_monitored_strategy = sid
                    return float(ic), True
            if first_available is not None:
                self._last_monitored_strategy = first_available[0]
                return first_available[1], True

            # No strategy produced a measurable IC.  Say so out loud: a
            # silent 0.0 would be read downstream as "healthy" (the decay
            # check treats unavailable IC as HEALTHY = not measured), and an
            # operator staring at "healthy" deserves to know that nothing
            # was actually measured.
            sample = getattr(monitor, "last_ic_sample", None)
            if sample:
                logger.warning(
                    "实时 IC 不可测（样本不足）→ 跳过模型衰减判定 / realized IC "
                    "not measurable (thin sample) → model-decay check skipped: {}",
                    sample,
                )
            return 0.0, False
        except Exception:
            return 0.0, False

    def _check_kill_switch(
        self,
        context: Any,
        psi: float = 0.0,
        rolling_ic: float = 0.0,
    ) -> dict[str, Any]:
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
            "psi": psi,
            "rolling_ic": rolling_ic,
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
        except Exception as exc:
            # Best-effort, never blocks the pipeline — but a silent failure
            # hides stale dashboard data (e.g. schema mismatch after code
            # deploy without restart). Log it so it's visible in scheduler.log.
            logger.warning("Health log write failed (dashboard will show stale data): {}", exc)

    def _archive_to_knowledge(self, report: MonitorReport) -> None:
        """Auto-archive significant events to KnowledgeArchive (#14 fix).

        Only archives on PAUSE_BUY, REDUCE, or STOP — WATCH is informational
        and should not generate noise. Creates failure_analysis entries when
        Kill Switch fires at actionable levels.
        """
        if report.action in (MonitorAction.OK, MonitorAction.WATCH):
            return  # Don't archive routine or watch-only events

        try:
            # 归档器由上层组合根注入（CLI/scheduler），监控层不直接依赖知识层。
            # 未注入时跳过归档（best-effort，不阻塞管道）。
            archive = self._knowledge_archive
            if archive is None:
                return

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

        Fail-safe guard (P1-4): an ``OK`` verdict only means "no risk event"
        when the run actually measured something.  If the key inputs never
        reached the pipeline (no price data → no regime, no drift, no
        realized IC), the honest verdict is "unknown" — leave the stored
        state untouched instead of downgrading it.  Before this guard a
        data-less run (a unit test, a mis-invoked CLI) cleared PAUSED /
        WARNING to NORMAL, i.e. missing data was silently read as "all
        clear".  See docs/tracking/rolling_ic_false_stale.md §4.1.

        The ``reason`` shown on the WebUI is a human-readable sentence;
        machine-readable fields (action/regime/psi/triggers) go into
        ``details`` so logs stay complete without confusing the display.
        """
        try:
            from qp.monitoring.system_state import SystemStateManager

            if report.action == MonitorAction.OK and not self._measurements_present(report):
                logger.warning(
                    "监控输入不可用（regime={} psi_available={} ic_available={}）→ "
                    "保持系统状态不变 / monitor inputs unavailable → system state "
                    "left unchanged (fail-safe, no OK downgrade)",
                    report.regime is not None,
                    report.psi_available,
                    report.rolling_ic_available,
                )
                return

            mgr = SystemStateManager()
            regime_str = report.regime.regime.value if report.regime else "UNKNOWN"
            reason = self._human_reason(report, regime_str)
            details = f"action={report.action.value} regime={regime_str} psi={report.psi_value:.3f}"
            if report.kill_switch_triggers:
                details += " | triggers: " + ", ".join(report.kill_switch_triggers[:3])

            mgr.auto_transition(
                monitor_action=report.action.value,
                reason=reason,
                source="KillSwitchPipeline",
                details=details,
            )
        except Exception:
            pass  # Best-effort — state machine failure should not block pipeline

    @staticmethod
    def _measurements_present(report: MonitorReport) -> bool:
        """True when the run actually measured the risk posture.

        Requires market data (a missing regime means no price data reached
        the pipeline at all) plus at least one real risk measurement —
        drift (PSI) or realized IC.  A missing IC on its own is tolerated:
        it is routinely unavailable while signal history accumulates, and
        the decay check reports "not measured" rather than "clear".
        """
        if report.regime is None:
            return False
        return bool(report.psi_available or report.rolling_ic_available)

    @staticmethod
    def _human_reason(report: MonitorReport, regime_str: str) -> str:
        """Build a human-readable transition reason.

        Reads like a sentence for the WebUI instead of a machine log line.
        """
        action = report.action

        if action == MonitorAction.OK:
            return "监控正常，未发现风险事件"

        if action == MonitorAction.WATCH:
            parts = ["监控警告"]
            if report.psi_available and report.psi_value >= 0.25:
                parts.append(f"信号分布漂移 PSI={report.psi_value:.2f}（阈值 0.25）")
            if regime_str == "UNKNOWN":
                parts.append("市场环境未知")
            else:
                _regime_labels = {
                    "TREND_UP": "上涨趋势",
                    "TREND_DOWN": "下跌趋势",
                    "RANGING": "震荡市",
                    "LIQUIDITY_CRUNCH": "流动性危机",
                    "STYLE_REVERSAL": "风格切换",
                }
                parts.append(f"市场环境: {_regime_labels.get(regime_str, regime_str)}")
            parts.append("维持现有持仓，新开仓不受限")
            return "；".join(parts)

        if action == MonitorAction.PAUSE_BUY:
            return "风险事件触发：暂停新开仓"
        if action == MonitorAction.REDUCE:
            return "风险事件触发：建议降低仓位"
        if action == MonitorAction.STOP:
            return "紧急熔断：停止交易"
        return f"监控状态: {action.value}"

    def _emit_retrain_signal(self, report: MonitorReport) -> None:
        """Emit retrain/weight-adjustment signal based on monitoring state.

        Evaluates PSI drift, IC decay, and model decay stage to determine
        if retraining or weight reduction is needed (L11-1.5, L11-1.7).
        """
        try:
            from qp.monitoring.retrain_signal import (
                RetrainSignalLogger,
                RetrainTrigger,
                evaluate_retrain_need,
            )

            regime_str = report.regime.regime.value if report.regime else "UNKNOWN"

            signal = evaluate_retrain_need(
                strategy_name=report.strategy_name or "unknown",
                psi_value=report.psi_value,
                rolling_ic=report.rolling_ic,
                training_ic=0.035,
                current_regime=regime_str,
                model_decay_stage=str(report.model_decay_stage),
            )

            # rolling_ic_available=False means IC was never computed (no
            # signal history yet / no price data in context).  A zero IC
            # under that flag is a data gap, not real decay — suppress
            # IC_DECAY false alarms so operators aren't spammed daily.
            if not report.rolling_ic_available and signal.trigger == RetrainTrigger.IC_DECAY:
                return

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
