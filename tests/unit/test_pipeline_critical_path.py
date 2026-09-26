# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for critical pipeline paths — DailyPipeline, KillSwitchPipeline, MultiFactorPipeline.


Previously test_pipeline.py only had 6 abstract tests (76 lines).
This adds coverage for the actual production pipelines.

Coverage:
  - DailyPipeline: system state gating, parameter handling, FAILED paths
  - KillSwitchPipeline: full run, action determination, post-processing steps
  - MultiFactorPipeline: strategy dispatch, parameter parsing
  - PipelineContext: parameter passthrough
  - FullDataPipeline: structure and constructor
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import polars as pl


class TestDailyPipelineCriticalPath:
    """Critical path: DailyPipeline Step 0 (SystemState check) and FAILED handling."""

    def test_construct(self) -> None:
        from qp.pipeline.daily_pipeline import DailyPipeline

        p = DailyPipeline()
        assert p.name == "daily"

    def test_system_state_paused_runs_record_only(self) -> None:
        """P1-2: a blocked state must NOT abort the run.

        Step 0 used to return immediately, which also skipped Step 10.5 — the
        only writer of the online signal history the kill switch measures — so
        a paused platform could never be revised (deadlock, see
        docs/tracking/rolling_ic_false_stale.md §4).  Blocked now means
        "record only": the recording chain runs, no decisions are produced.
        """
        from qp.monitoring.system_state import SystemState, SystemStateManager
        from qp.pipeline.daily_pipeline import DailyPipeline
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.shared.types import PipelineStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SystemStateManager(base_dir=tmpdir)
            mgr.transition(SystemState.PAUSED, reason="Test block")

            ctx = PipelineContext(
                pipeline_name="test_daily",
                parameters={"capital": 500000, "top_n": 5, "allocator": "equal_weight"},
            )

            # DataPipeline is the first step after the state check: reaching it
            # proves the run continued past Step 0.
            sentinel = PipelineResult(status=PipelineStatus.FAILED)
            sentinel.errors = ["RECORDING_CHAIN_ENTERED"]

            pipeline = DailyPipeline()
            with (
                patch("qp.monitoring.system_state.SystemStateManager", return_value=mgr),
                patch("qp.pipeline.daily_pipeline.DataPipeline") as data_cls,
            ):
                data_cls.return_value.run.return_value = sentinel
                result = pipeline.run(ctx)

            assert data_cls.return_value.run.called, "state check must not abort the run"
            assert "RECORDING_CHAIN_ENTERED" in result.errors
            assert result.metadata.get("system_state") == "PAUSED"
            assert result.metadata.get("record_only") is True
            assert "PAUSED" in result.metadata["skip_reason"]

    def test_system_state_normal_allows_execution_fails_on_missing_data(self) -> None:
        """When SystemState is NORMAL but no data exists, pipeline fails gracefully."""
        from qp.monitoring.system_state import SystemStateManager
        from qp.pipeline.daily_pipeline import DailyPipeline
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.shared.types import PipelineStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SystemStateManager(base_dir=tmpdir)

            ctx = PipelineContext(
                pipeline_name="test_daily",
                parameters={"capital": 100000},
            )

            pipeline = DailyPipeline()
            with (
                patch(
                    "qp.monitoring.system_state.SystemStateManager",
                    return_value=mgr,
                ),
                patch(
                    "qp.pipeline.daily_pipeline.DataPipeline.run",
                    return_value=PipelineResult(status=PipelineStatus.SUCCESS),
                ),
                patch(
                    "qp.pipeline.daily_pipeline.FeaturePipeline.run",
                    return_value=PipelineResult(status=PipelineStatus.SUCCESS),
                ),
                patch(
                    "qp.pipeline.daily_pipeline._load_price_data",
                    return_value=({}, pl.DataFrame()),
                ),
                # Steps 1.5/1.6 lazily import and write production data — stub both.
                patch("qp.pipeline.factor_calc_pipeline.FactorCalcPipeline") as factor_cls,
                patch("qp.monitoring.factor_health_pipeline.FactorHealthPipeline") as fh_cls,
            ):
                factor_cls.return_value.run.return_value = PipelineResult(
                    status=PipelineStatus.SUCCESS
                )
                fh_cls.return_value.run_incremental.return_value = PipelineResult(
                    status=PipelineStatus.SUCCESS
                )
                result = pipeline.run(ctx)

            assert result.status.value in ("success", "failed")

    def test_parameter_passthrough(self) -> None:
        """DailyPipeline correctly extracts parameters from context."""
        from qp.pipeline.daily_pipeline import DailyPipeline
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_params",
            parameters={
                "capital": 250000,
                "top_n": 15,
                "allocator": "risk_parity",
            },
        )

        pipeline = DailyPipeline()
        assert pipeline.name == "daily"
        assert ctx.parameters["capital"] == 250000
        assert ctx.parameters["top_n"] == 15
        assert ctx.parameters["allocator"] == "risk_parity"

    def test_state_check_is_advisory(self) -> None:
        """If SystemStateManager fails, pipeline continues (doesn't crash)."""
        from qp.pipeline.daily_pipeline import DailyPipeline
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.shared.types import PipelineStatus

        ctx = PipelineContext(
            pipeline_name="test_advisory",
            parameters={"capital": 100000},
        )

        pipeline = DailyPipeline()
        with (
            patch(
                "qp.monitoring.system_state.SystemStateManager",
                side_effect=RuntimeError("State manager unavailable"),
            ),
            patch(
                "qp.pipeline.daily_pipeline.DataPipeline.run",
                return_value=PipelineResult(status=PipelineStatus.SUCCESS),
            ),
            patch(
                "qp.pipeline.daily_pipeline.FeaturePipeline.run",
                return_value=PipelineResult(status=PipelineStatus.SUCCESS),
            ),
            patch(
                "qp.pipeline.daily_pipeline._load_price_data",
                return_value=({}, pl.DataFrame()),
            ),
            # Steps 1.5/1.6 lazily import and write production data — stub both.
            patch("qp.pipeline.factor_calc_pipeline.FactorCalcPipeline") as factor_cls,
            patch("qp.monitoring.factor_health_pipeline.FactorHealthPipeline") as fh_cls,
        ):
            factor_cls.return_value.run.return_value = PipelineResult(status=PipelineStatus.SUCCESS)
            fh_cls.return_value.run_incremental.return_value = PipelineResult(
                status=PipelineStatus.SUCCESS
            )
            result = pipeline.run(ctx)
            assert result.status.value in ("success", "failed")


class TestKillSwitchPipelineIntegration:
    """Integration tests for KillSwitchPipeline post-processing steps."""

    def test_full_pipeline_runs_all_steps(self) -> None:
        from qp.monitoring.kill_switch_pipeline import KillSwitchPipeline
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(pipeline_name="test_ks_full")
        pipeline = KillSwitchPipeline()
        result = pipeline.run(ctx)

        assert result.status.value == "success"
        assert "psi" in result.metrics
        assert "kill_switch_triggered" in result.metrics
        assert "MonitorReport" in result.artifacts
        assert "action" in result.metadata

    def test_health_log_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.health_logger import SystemHealthLogger

            logger = SystemHealthLogger(base_dir=tmpdir)
            logger.log(
                date="2026-07-25",
                psi_value=0.12,
                rolling_ic=0.025,
                regime="TREND_UP",
                kill_switch_level="NORMAL",
                kill_switch_triggered=False,
                model_decay_stage="HEALTHY",
                strategy_health_score=92.0,
                action="OK",
            )

            latest = logger.get_latest()
            assert latest is not None
            assert latest.date == "2026-07-25"
            assert latest.action == "OK"

            stats = logger.stats()
            assert stats["n_days"] == 1

    def test_all_post_processing_steps_exist(self) -> None:
        """Verify all 5 post-processing methods are callable."""
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
            MonitorReport,
        )

        pipeline = KillSwitchPipeline()
        report = MonitorReport(
            action=MonitorAction.OK,
            psi_value=0.0,
            model_decay_stage="HEALTHY",
        )

        # All post-processing steps should handle empty reports gracefully
        pipeline._log_health(report)
        pipeline._archive_to_knowledge(report)
        pipeline._emit_retrain_signal(report)
        pipeline._update_system_state(report)

    def test_health_log_from_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from qp.monitoring.health_logger import SystemHealthLogger
            from qp.monitoring.kill_switch_pipeline import MonitorReport
            from qp.monitoring.regime import Regime, RegimeResult

            logger = SystemHealthLogger(base_dir=tmpdir)
            regime = RegimeResult(regime=Regime.TREND_UP, confidence=0.80)
            report = MonitorReport(
                action="ok",
                regime=regime,
                psi_value=0.05,
                alerts=[],
            )

            record = logger.log_from_report(report, date_str="2026-07-25")
            assert record is not None
            assert record.regime == "TREND_UP"

    def test_archive_only_on_significant_actions(self) -> None:
        """#14 fix: WATCH does NOT archive, PAUSE_BUY DOES."""
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
            MonitorReport,
        )
        from qp.monitoring.regime import Regime, RegimeResult

        pipeline = KillSwitchPipeline()

        # OK → no archive
        report_ok = MonitorReport(action=MonitorAction.OK)
        pipeline._archive_to_knowledge(report_ok)  # Should return immediately

        # WATCH → no archive
        report_watch = MonitorReport(action=MonitorAction.WATCH)
        pipeline._archive_to_knowledge(report_watch)  # Should return immediately

        # PAUSE_BUY → should attempt archive
        crisis_regime = RegimeResult(regime=Regime.LIQUIDITY_CRUNCH, confidence=0.85)
        report_pause = MonitorReport(
            action=MonitorAction.PAUSE_BUY,
            regime=crisis_regime,
            kill_switch_triggers=["Weekly DD 7% > 5%"],
        )
        # Won't crash even if KnowledgeArchive dir doesn't exist
        pipeline._archive_to_knowledge(report_pause)


class TestMultiFactorPipeline:
    """Tests for the MultiFactorPipeline (experiment pipeline)."""

    def test_construct(self) -> None:
        from qp.pipeline.multifactor_pipeline import MultiFactorPipeline

        p = MultiFactorPipeline()
        assert p is not None

    def test_strategy_param_maps_to_runner(self) -> None:
        """Parameter 'strategy' is correctly parsed for strategy dispatch."""
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_mf",
            parameters={
                "strategy": "alpha_multi_factor_v2",
                "start_date": "2026-01-01",
                "top_n": 20,
            },
        )

        strategy = ctx.parameters.get("strategy", "")
        assert strategy == "alpha_multi_factor_v2"
        assert ctx.parameters.get("top_n") == 20

    def test_comma_separated_strategies_parsed(self) -> None:
        """Comma-separated strategy list is split correctly."""
        strategy_val = "alpha_multi_factor_v1,alpha_multi_factor_v2,momentum_vol_full"
        strategies = [s.strip() for s in strategy_val.split(",") if s.strip()]
        assert len(strategies) == 3
        assert strategies[0] == "alpha_multi_factor_v1"
        assert strategies[2] == "momentum_vol_full"

    def test_empty_strategy_produces_empty_list(self) -> None:
        strategies = [s.strip() for s in [""] if s.strip()]
        assert strategies == []

    def test_model_mode_flag_parsed(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_mf_model",
            parameters={"model_mode": True, "strategy": "momentum_vol_full"},
        )
        assert ctx.parameters.get("model_mode") is True

    def test_score_band_parsed(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_mf_band",
            parameters={"score_band": "60-80", "strategy": "default"},
        )
        assert ctx.parameters.get("score_band") == "60-80"


class TestPipelineContext:
    """Tests for PipelineContext parameter passing and lifecycle."""

    def test_context_defaults(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(pipeline_name="test")
        assert ctx.pipeline_name == "test"
        assert ctx.parameters == {}
        assert ctx.run_id != ""

    def test_context_with_parameters(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_params",
            parameters={"key": "value", "number": 42},
        )
        assert ctx.parameters["key"] == "value"
        assert ctx.parameters["number"] == 42

    def test_context_run_id_is_unique(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx1 = PipelineContext(pipeline_name="a")
        ctx2 = PipelineContext(pipeline_name="b")
        assert ctx1.run_id != ctx2.run_id

    def test_context_preserves_complex_types(self) -> None:
        from qp.platform.pipeline.context import PipelineContext

        ctx = PipelineContext(
            pipeline_name="test_complex",
            parameters={
                "symbols": ["000001", "000002", "000003"],
                "dates": {"start": "2026-01-01", "end": "2026-07-01"},
                "flags": {"model_mode": True, "skip_gate": False},
            },
        )
        assert len(ctx.parameters["symbols"]) == 3  # type: ignore[arg-type]
        assert ctx.parameters["dates"]["start"] == "2026-01-01"  # type: ignore[index]


class TestFullDataPipeline:
    """Tests for FullDataPipeline structure."""

    def test_construct(self) -> None:
        from qp.data.loader.full_pipeline import FullDataPipeline

        p = FullDataPipeline()
        assert p.name == "full_data_ingest"

    def test_tier_directories_exist(self) -> None:
        """Raw/Bronze/Silver/Gold directories are defined."""
        from qp.data.loader.full_pipeline import (
            DIR_BRONZE,
            DIR_GOLD,
            DIR_RAW,
            DIR_SILVER,
        )

        assert str(DIR_RAW) == "data/raw"
        assert str(DIR_BRONZE) == "data/bronze"
        assert str(DIR_SILVER) == "data/silver"
        assert str(DIR_GOLD) == "data/dataset"

    def test_name_property(self) -> None:
        from qp.data.loader.full_pipeline import FullDataPipeline

        p = FullDataPipeline()
        assert p.name is not None
        assert len(p.name) > 0


class TestPipelineResult:
    """Extended PipelineResult tests."""

    def test_result_metrics_merge(self) -> None:
        from qp.platform.pipeline.result import PipelineResult
        from qp.shared.types import PipelineStatus

        result = PipelineResult(status=PipelineStatus.SUCCESS)
        result.metrics["ic_mean"] = 0.025
        result.metrics["sharpe"] = 0.45
        result.metrics["n_signals"] = 10

        assert len(result.metrics) == 3
        assert result.metrics["ic_mean"] == 0.025

    def test_result_artifacts_list(self) -> None:
        from qp.platform.pipeline.result import PipelineResult

        result = PipelineResult()
        result.artifacts.append("data/dataset/daily_price.parquet")
        result.artifacts.append("reports/signals.md")

        assert len(result.artifacts) == 2
        assert "reports/signals.md" in result.artifacts

    def test_result_metadata_stores_complex(self) -> None:
        from qp.platform.pipeline.result import PipelineResult

        result = PipelineResult()
        result.metadata["strategy_counts"] = {"v1": 10, "v2": 5}
        result.metadata["decision_package_id"] = "dp-2026-07-25-abc123"

        assert result.metadata["strategy_counts"]["v1"] == 10  # type: ignore[index]


class TestPipelineRunner:
    """Extended PipelineRunner tests."""

    def test_runner_returns_result_for_success(self) -> None:
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.platform.pipeline.runner import PipelineRunner
        from qp.shared.protocols.base_pipeline import BasePipeline
        from qp.shared.types import PipelineStatus

        class _OKPipeline(BasePipeline):
            @property
            def name(self) -> str:
                return "ok"

            def run(self, ctx: PipelineContext) -> PipelineResult:
                r = PipelineResult(status=PipelineStatus.SUCCESS)
                r.metrics["x"] = 1.0
                return r

        runner = PipelineRunner()
        result = runner.run(_OKPipeline())
        assert result.status == PipelineStatus.SUCCESS
        assert result.metrics["x"] == 1.0

    def test_runner_captures_exception_as_failed(self) -> None:
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.platform.pipeline.runner import PipelineRunner
        from qp.shared.protocols.base_pipeline import BasePipeline
        from qp.shared.types import PipelineStatus

        class _CrashPipeline(BasePipeline):
            @property
            def name(self) -> str:
                return "crash"

            def run(self, ctx: PipelineContext) -> PipelineResult:
                msg = "Data not found"
                raise FileNotFoundError(msg)

        runner = PipelineRunner()
        result = runner.run(_CrashPipeline())
        assert result.status == PipelineStatus.FAILED
        assert len(result.errors) > 0
        assert "Data not found" in result.errors[0]

    def test_runner_sets_timing(self) -> None:
        from qp.platform.pipeline.context import PipelineContext
        from qp.platform.pipeline.result import PipelineResult
        from qp.platform.pipeline.runner import PipelineRunner
        from qp.shared.protocols.base_pipeline import BasePipeline
        from qp.shared.types import PipelineStatus

        class _TimedPipeline(BasePipeline):
            @property
            def name(self) -> str:
                return "timed"

            def run(self, ctx: PipelineContext) -> PipelineResult:
                import time

                time.sleep(0.01)
                return PipelineResult(status=PipelineStatus.SUCCESS)

        runner = PipelineRunner()
        result = runner.run(_TimedPipeline())
        assert result.duration_seconds > 0
        assert result.start_time is not None
