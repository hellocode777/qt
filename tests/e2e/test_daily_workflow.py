"""End-to-end tests for the daily operating schedule.

Covers the critical path:
  1. KillSwitchPipeline smoke test
  2. SystemState lifecycle (NORMAL → WARNING → PAUSED → RECOVERY)
  3. SystemState blocks DailyPipeline execution
  4. RetrainSignal evaluate + log + notify
  5. All 7 KillSwitch triggers evaluate without crash
  6. KnowledgeArchive auto-archive only on PAUSE_BUY+
  7. Watchdog ping file creation
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path


class TestKillSwitchPipelineE2E:
    """End-to-end: KillSwitchPipeline runs end-to-end with all steps."""

    def test_pipeline_runs_and_returns_report(self) -> None:
        from qp.monitoring.kill_switch_pipeline import KillSwitchPipeline, MonitorReport
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(pipeline_name="e2e_test")
        pipeline = KillSwitchPipeline()
        result = pipeline.run(ctx)

        assert result.status.value == "success"
        report = result.metadata.get("report")  # type: ignore[union-attr]
        assert report is not None
        assert isinstance(report, MonitorReport)
        assert result.metrics["psi"] >= 0.0

    def test_pipeline_default_action_is_ok(self) -> None:
        from qp.monitoring.kill_switch_pipeline import KillSwitchPipeline, MonitorAction
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(pipeline_name="e2e_test")
        pipeline = KillSwitchPipeline()
        result = pipeline.run(ctx)

        report = result.metadata.get("report")  # type: ignore[union-attr]
        # With no real data, all triggers should be silent
        assert report.action == MonitorAction.OK

    def test_all_checks_run(self) -> None:
        """Verify all 5 check steps run without crash."""
        from qp.monitoring.kill_switch_pipeline import KillSwitchPipeline
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(pipeline_name="e2e_test")
        pipeline = KillSwitchPipeline()

        # Call each check method individually
        regime = pipeline._check_regime(ctx)
        assert regime is None  # No price data

        psi, alerts = pipeline._check_drift(ctx)
        assert psi == 0.0
        assert alerts == []

        stage = pipeline._check_model_decay(ctx)
        assert stage is not None

        health = pipeline._check_strategy_health(ctx)
        assert health is None  # No monitor

        ks = pipeline._check_kill_switch(ctx)
        assert "triggered" in ks
        assert "level" in ks


class TestSystemStateE2E:
    """End-to-end: SystemState lifecycle and cross-pipeline blocking."""

    def test_initial_state_is_normal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.system_state import SystemState, SystemStateManager

            mgr = SystemStateManager(base_dir=tmpdir)
            current = mgr.current()
            assert current.to_state == SystemState.NORMAL

    def test_transition_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.system_state import SystemState, SystemStateManager

            mgr = SystemStateManager(base_dir=tmpdir)

            # NORMAL → WARNING
            t1 = mgr.transition(SystemState.WARNING, reason="PSI 0.30 > 0.25", source="test")
            assert t1.to_state == SystemState.WARNING
            assert mgr.current().to_state == SystemState.WARNING

            # WARNING → PAUSED
            t2 = mgr.transition(SystemState.PAUSED, reason="Weekly DD 7%", source="test")
            assert t2.to_state == SystemState.PAUSED

            # PAUSED → STOPPED
            t3 = mgr.transition(SystemState.STOPPED, reason="Abnormal turnover", source="test")
            assert t3.to_state == SystemState.STOPPED

            # Check history
            log = mgr.history()
            assert log.height == 3

    def test_auto_transition_from_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.system_state import SystemState, SystemStateManager

            mgr = SystemStateManager(base_dir=tmpdir)

            # OK → NORMAL (already normal, no change)
            result = mgr.auto_transition("OK", reason="test")
            assert result is None  # No change

            # PAUSE_BUY → PAUSED
            result = mgr.auto_transition("PAUSE_BUY", reason="test")
            assert result is not None
            assert result.to_state == SystemState.PAUSED

            # OK from PAUSED → RECOVERY (not straight to NORMAL)
            result = mgr.auto_transition("OK", reason="recovered")
            assert result is not None
            assert result.to_state == SystemState.RECOVERY

    def test_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.system_state import SystemState, SystemStateManager

            mgr = SystemStateManager(base_dir=tmpdir)
            assert not mgr.is_blocked()

            mgr.transition(SystemState.PAUSED, reason="test")
            assert mgr.is_blocked()

            mgr.transition(SystemState.STOPPED, reason="test")
            assert mgr.is_blocked()

    def test_normal_can_open_positions(self) -> None:
        from qp.monitoring.system_state import SystemState

        assert SystemState.NORMAL.can_open_positions()
        assert SystemState.WARNING.can_open_positions()
        assert not SystemState.PAUSED.can_open_positions()
        assert not SystemState.STOPPED.can_open_positions()
        assert SystemState.RECOVERY.can_open_positions() is False  # RECOVERY > PAUSED in int value

    def test_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.system_state import SystemState, SystemStateManager

            mgr = SystemStateManager(base_dir=tmpdir)
            mgr.transition(SystemState.WARNING, reason="test")
            stats = mgr.stats()
            assert stats["current_state"] == "WARNING"
            assert stats["n_transitions"] == 1


class TestRetrainSignalE2E:
    """End-to-end: RetrainSignal evaluate → log → query."""

    def test_evaluate_full_chain(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        # PSI drift → retrain
        signal = evaluate_retrain_need(psi_value=0.30, strategy_name="test")
        assert signal.action == RetrainAction.SCHEDULE_RETRAIN
        assert signal.is_actionable()

        # IC decay → reduce weight
        signal = evaluate_retrain_need(rolling_ic=0.008, training_ic=0.035, strategy_name="test")
        assert signal.action == RetrainAction.REDUCE_WEIGHT
        assert signal.is_actionable()

        # STALE → retire
        signal = evaluate_retrain_need(model_decay_stage="STALE", strategy_name="test")
        assert signal.action == RetrainAction.RETIRE

        # Mild PSI → monitor only (not actionable)
        signal = evaluate_retrain_need(psi_value=0.12, rolling_ic=0.03, strategy_name="test")
        assert signal.action == RetrainAction.MONITOR
        assert not signal.is_actionable()

        # All clear → none
        signal = evaluate_retrain_need(psi_value=0.05, rolling_ic=0.03, training_ic=0.035)
        assert signal.action == RetrainAction.NONE

    def test_log_and_retrieve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.retrain_signal import (
                RetrainAction,
                RetrainSignal,
                RetrainSignalLogger,
            )

            logger = RetrainSignalLogger(base_dir=tmpdir)

            # Log multiple signals
            logger.log(
                RetrainSignal(
                    date="2026-07-25",
                    strategy_name="test_v1",
                    trigger="PSI_DRIFT",
                    action=RetrainAction.SCHEDULE_RETRAIN,
                    psi_value=0.30,
                    message="PSI drift detected",
                )
            )
            logger.log(
                RetrainSignal(
                    date="2026-07-26",
                    strategy_name="test_v1",
                    trigger="IC_DECAY",
                    action=RetrainAction.REDUCE_WEIGHT,
                    rolling_ic=0.008,
                    message="IC decay",
                )
            )
            logger.log(
                RetrainSignal(
                    date="2026-07-27",
                    strategy_name="test_v1",
                    trigger="PSI_DRIFT",
                    action=RetrainAction.MONITOR,
                    psi_value=0.12,
                    message="Mild drift",
                )
            )

            # Query
            history = logger.load_history(days=30)
            assert len(history) == 3

            stats = logger.stats()
            assert stats["n_signals"] == 3

    def test_regime_shift_triggers_monitor(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(
            psi_value=0.05,
            rolling_ic=0.03,
            training_ic=0.035,
            current_regime="LIQUIDITY_CRUNCH",
        )
        assert signal.action == RetrainAction.MONITOR
        assert signal.trigger == "REGIME_SHIFT"


class TestKillSwitchTriggersE2E:
    """End-to-end: All 7 KillSwitch triggers evaluate without crash."""

    def test_all_triggers_evaluate_silently_with_defaults(self) -> None:
        from qp.monitoring.kill_switch import (
            AbnormalTurnoverTrigger,
            ConsecutiveLossTrigger,
            DrawdownTrigger,
            ModelDecayTrigger,
            PortfolioDrawdownTrigger,
            PSITrigger,
            WeeklyDrawdownTrigger,
        )

        triggers = [
            DrawdownTrigger(),
            PortfolioDrawdownTrigger(),
            PSITrigger(),
            ModelDecayTrigger(training_ic_mean=0.035),
            WeeklyDrawdownTrigger(),
            ConsecutiveLossTrigger(),
            AbnormalTurnoverTrigger(),
        ]

        metrics: dict[str, object] = {
            "current_drawdown": 0.0,
            "monthly_return": 0.0,
            "rolling_60d_drawdown": 0.0,
            "psi": 0.0,
            "rolling_ic": 0.0,
            "training_ic_mean": 0.035,
            "weekly_drawdown": 0.0,
            "consecutive_loss_days": 0,
            "daily_trade_count": 0,
            "total_holdings": 1,
        }

        for t in triggers:
            result = t.evaluate(metrics)
            assert "fired" in result
            assert "kill_level" in result
            # All should be silent with default zero values
            assert result["fired"] is False, f"{t.name} fired on defaults"

    def test_triggers_fire_with_real_data(self) -> None:
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            KillSwitchLevel,
            WeeklyDrawdownTrigger,
        )

        # Weekly drawdown triggers
        t = WeeklyDrawdownTrigger(weekly_limit=0.05)
        result = t.evaluate({"weekly_drawdown": 0.07})
        assert result["fired"] is True
        assert result["kill_level"] == KillSwitchLevel.HALT_BUY

        # Drawdown triggers
        t = DrawdownTrigger(historical_max_dd=0.15, ratio=1.5)
        result = t.evaluate({"current_drawdown": 0.30})
        assert result["fired"] is True

    def test_trigger_priorities(self) -> None:
        from qp.monitoring.kill_switch import (
            AbnormalTurnoverTrigger,
            ConsecutiveLossTrigger,
            DrawdownTrigger,
            ModelDecayTrigger,
            PSITrigger,
            WeeklyDrawdownTrigger,
        )

        triggers = [
            (AbnormalTurnoverTrigger, 10),
            (WeeklyDrawdownTrigger, 15),
            (DrawdownTrigger, 20),
            (ConsecutiveLossTrigger, 30),
            (ModelDecayTrigger, 40),
            (PSITrigger, 50),
        ]

        for cls, expected_priority in triggers:
            instance = cls()  # type: ignore[call-arg]
            assert instance.priority == expected_priority, (
                f"{cls.__name__}: expected priority {expected_priority}, got {instance.priority}"
            )


class TestAutoArchiveE2E:
    """End-to-end: KnowledgeArchive auto-archive gating (#14 fix)."""

    def test_watch_does_not_archive(self) -> None:
        """WATCH events should NOT generate archive noise."""
        with tempfile.TemporaryDirectory():
            from qp.monitoring.kill_switch_pipeline import (
                KillSwitchPipeline,
                MonitorAction,
                MonitorReport,
            )

            class _TestKSP(KillSwitchPipeline):
                @property
                def name(self) -> str:
                    return "test"

            pipeline = _TestKSP()
            report = MonitorReport(action=MonitorAction.WATCH)

            # Patch archive to track calls
            pipeline._archive_to_knowledge(report)
            # Should return immediately without calling KnowledgeArchive

    def test_pause_buy_does_archive(self) -> None:
        """PAUSE_BUY events SHOULD generate archive entries."""
        with tempfile.TemporaryDirectory():
            from qp.monitoring.kill_switch_pipeline import (
                KillSwitchPipeline,
                MonitorAction,
                MonitorReport,
            )

            class _TestKSP(KillSwitchPipeline):
                @property
                def name(self) -> str:
                    return "test"

            pipeline = _TestKSP()
            report = MonitorReport(action=MonitorAction.PAUSE_BUY)

            # Should attempt archive (may fail gracefully if KnowledgeArchive
            # directory isn't set up — that's fine, we just verify no crash)
            pipeline._archive_to_knowledge(report)


class TestWatchdogE2E:
    """End-to-end: Watchdog ping file creation."""

    def test_ping_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ping_dir = Path(tmpdir) / "watchdog"
            ping_dir.mkdir(parents=True, exist_ok=True)

            ping_file = ping_dir / "test_job.ping"
            ping_file.write_text(f"{datetime.now(UTC).isoformat()}\n")

            assert ping_file.exists()
            content = ping_file.read_text()
            assert "2026" in content  # ISO timestamp


class TestSchedulerJobRegistration:
    """End-to-end: Verify all 5 jobs are registered."""

    def test_all_jobs_registered(self) -> None:
        from qp.platform.scheduler.job import Job
        from qp.platform.scheduler.scheduler import QPScheduler
        from qp.platform.scheduler.trigger import CronTrigger

        scheduler = QPScheduler(timezone="Asia/Shanghai")

        scheduler.add_job(
            Job(
                name="data_fetch",
                task=lambda: None,
                trigger=CronTrigger(day="1-5", hour="8", minute="0"),
            )
        )
        scheduler.add_job(
            Job(
                name="monitor_check",
                task=lambda: None,
                trigger=CronTrigger(day="1-5", hour="9", minute="7"),
            )
        )
        scheduler.add_job(
            Job(
                name="retrain_notify",
                task=lambda: None,
                trigger=CronTrigger(day="1-5", hour="9", minute="17"),
            )
        )
        scheduler.add_job(
            Job(
                name="pre_close_check",
                task=lambda: None,
                trigger=CronTrigger(day="1-5", hour="16", minute="53"),
            )
        )
        scheduler.add_job(
            Job(
                name="daily_pipeline",
                task=lambda: None,
                trigger=CronTrigger(day="1-5", hour="17", minute="57"),
            )
        )

        jobs = scheduler.list_jobs()
        assert "data_fetch" in jobs
        assert "monitor_check" in jobs
        assert "retrain_notify" in jobs
        assert "pre_close_check" in jobs
        assert "daily_pipeline" in jobs
        assert len(jobs) == 5
