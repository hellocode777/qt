"""ValidationPipeline — wraps RuleEngine as a BasePipeline.

Makes the Validation Gate schedulable and CLI-invocable. Supports
lifecycle-aware check registration: different checks run at different
stages (Factor → Backtest → Paper Trading → Shadow→Production).

Per rule.md §11 Phase 1:
  "Validation Gate（第 5 层，最小版）—— 把第 10.2 节的判定条件写成
   自动化检查脚本"

Usage:
    pipeline = ValidationPipeline(stage="backtest_passed")
    result = pipeline.run(context)  # → PipelineResult with ValidationResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus, StrategyLifecycle
from qp.validation.engine import RuleEngine, ValidationContext


@dataclass
class ValidationPipelineConfig:
    """Configuration for a ValidationPipeline run.

    Attributes:
        stage: Which lifecycle stage to validate against.
        strategy_id: Strategy being validated.
        overrides: Threshold overrides keyed by rule_name → threshold_value.
        require_all_passed: If True, all stage checks must pass.
    """

    stage: str = "backtest_passed"
    strategy_id: str = ""
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    require_all_passed: bool = True


class ValidationPipeline(BasePipeline):
    """Runs the Validation Gate as a formal Pipeline.

    Automatically registers the appropriate checks for the target
    lifecycle stage. Results are returned as a PipelineResult with
    the ValidationResult as an artifact.

    Check registration by stage:
      RESEARCH / BACKTEST_PASSED → Factor checks + Backtest checks
      PAPER_TRADING               → + Overfit + Paper Trading checks
      SHADOW_PRODUCTION           → + Production checks
      PRODUCTION                  → + Process checks (code review, experiment)
    """

    def __init__(self, config: ValidationPipelineConfig | None = None) -> None:
        super().__init__()
        self._config = config or ValidationPipelineConfig()

    @property
    def name(self) -> str:
        return f"validation_gate_{self._config.stage}"

    # ------------------------------------------------------------------
    # Pipeline interface
    # ------------------------------------------------------------------

    def run(self, context: Any) -> Any:
        """Execute the Validation Gate pipeline.

        Args:
            context: PipelineContext with runtime info. Expected to carry
                     a ValidationContext via context.validation_context,
                     or raw data to build one.

        Returns:
            PipelineResult with ValidationResult as artifact.
        """
        from qp.platform.pipeline.result import PipelineResult

        logger = getattr(context, "logger", None)

        try:
            # Resolve validation context
            val_ctx = self._resolve_context(context)

            # Build engine with stage-appropriate checks
            engine = self._build_engine()

            # Run validation
            validation_result = engine.validate(val_ctx)

            # Determine pipeline status
            if validation_result.passed:
                status = PipelineStatus.SUCCESS
            elif not self._config.require_all_passed:
                status = PipelineStatus.PARTIAL
            else:
                status = PipelineStatus.FAILED

            result = PipelineResult(status=status)
            result.metrics = {
                "validation_score": validation_result.score,
                "validation_confidence": validation_result.confidence,
                "rules_total": len(validation_result.rules),
                "rules_failed": len(validation_result.failed_rules),
            }
            result.artifacts = ["ValidationResult"]
            result.metadata = {
                "stage": self._config.stage,
                "strategy_id": self._config.strategy_id,
                "validation": validation_result.to_dict(),
                "recommendation": validation_result.recommendation,
            }

            if logger:
                logger.info(
                    "ValidationPipeline complete: {} (score={}, confidence={:.0%})",
                    validation_result.status.value,
                    validation_result.score,
                    validation_result.confidence,
                )

            return result

        except Exception as exc:
            if logger:
                logger.error(f"ValidationPipeline failed: {exc}")

            from qp.platform.pipeline.result import PipelineResult

            result = PipelineResult(status=PipelineStatus.FAILED)
            result.errors = [str(exc)]
            return result

    # ------------------------------------------------------------------
    # Context resolution
    # ------------------------------------------------------------------

    def _resolve_context(self, context: Any) -> ValidationContext:
        """Extract or build a ValidationContext from pipeline context."""
        # If the pipeline context already carries a ValidationContext
        val_ctx = getattr(context, "validation_context", None)
        if isinstance(val_ctx, ValidationContext):
            return val_ctx

        # Otherwise build from available data
        return ValidationContext(
            feature_df=getattr(context, "feature_df", None),
            price_df=getattr(context, "price_df", None),
            signal_df=getattr(context, "signal_df", None),
            backtest_metrics=getattr(context, "backtest_metrics", {}),
            strategy_id=self._config.strategy_id,
            metadata=getattr(context, "metadata", {}),
        )

    # ------------------------------------------------------------------
    # Engine construction — lifecycle-aware
    # ------------------------------------------------------------------

    def _build_engine(self) -> RuleEngine:
        """Build a RuleEngine with appropriate checks for the target stage."""
        engine = RuleEngine()
        stage = self._config.stage

        # ---- Stage 1: Factor checks (always) ----
        self._register_factor_checks(engine, stage)

        # ---- Stage 2: Backtest checks ----
        if stage in _STAGES_REQUIRING_BACKTEST:
            self._register_backtest_checks(engine, stage)

        # ---- Stage 3: Overfit checks ----
        if stage in _STAGES_REQUIRING_OVERFIT:
            self._register_overfit_checks(engine, stage)

        # ---- Stage 4: Paper Trading checks ----
        if stage in _STAGES_REQUIRING_PAPER:
            self._register_paper_trading_checks(engine, stage)

        # ---- Stage 5: Production readiness ----
        if stage in _STAGES_REQUIRING_PRODUCTION:
            self._register_production_checks(engine, stage)

        # ---- Stage 6: Process/governance checks ----
        if stage in _STAGES_REQUIRING_PROCESS:
            self._register_process_checks(engine, stage)

        return engine

    # ------------------------------------------------------------------
    # Check registration per category
    # ------------------------------------------------------------------

    def _register_factor_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.factor_checks import (
            ICIRCheck,
            MinSamplePeriodCheck,
            NeutralizationCheck,
            RankICCheck,
            StratificationCheck,
            TStatCheck,
        )

        overrides = self._config.overrides

        engine.register(RankICCheck(
            min_ic_mean=overrides.get("rank_ic", {}).get("min_ic_mean", 0.02)
        ))
        engine.register(ICIRCheck(
            min_ic_ir=overrides.get("ic_ir", {}).get("min_ic_ir", 0.3)
        ))
        engine.register(TStatCheck(
            min_t_stat=overrides.get("ic_t_stat", {}).get("min_t_stat", 2.0)
        ))
        engine.register(StratificationCheck(
            min_t_stat=overrides.get("stratification", {}).get("min_t_stat", 2.0)
        ))
        engine.register(NeutralizationCheck(
            min_ratio=overrides.get("neutralization", {}).get("min_ratio", 0.5)
        ))
        engine.register(MinSamplePeriodCheck(
            min_years=overrides.get("min_sample_period", {}).get("min_years", 3.0)
        ))

    def _register_backtest_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.backtest_checks import (
            CostAdjustedCheck,
            MaxDrawdownCheck,
            SharpeCheck,
            TurnoverCheck,
        )

        overrides = self._config.overrides

        engine.register(SharpeCheck(
            min_sharpe=overrides.get("sharpe_ratio", {}).get("min_sharpe", 1.0)
        ))
        engine.register(MaxDrawdownCheck(
            max_drawdown_pct=overrides.get("max_drawdown", {}).get("max_drawdown_pct", 25.0)
        ))
        engine.register(TurnoverCheck(
            min_turnover_pct=overrides.get("turnover", {}).get("min_turnover_pct", 5.0),
            max_turnover_pct=overrides.get("turnover", {}).get("max_turnover_pct", 200.0),
        ))
        engine.register(CostAdjustedCheck(
            min_sharpe=overrides.get("cost_adjusted", {}).get("min_sharpe", 1.0),
            max_drawdown_pct=overrides.get("cost_adjusted", {}).get("max_drawdown_pct", 25.0),
        ))

    def _register_overfit_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.overfit_checks import (
            FeatureImportanceCheck,
            OverfitCheck,
        )

        overrides = self._config.overrides

        engine.register(OverfitCheck(
            min_oos_ratio=overrides.get("overfit_ic_ratio", {}).get("min_oos_ratio", 0.5)
        ))
        engine.register(FeatureImportanceCheck(
            max_top1_pct=overrides.get("feature_importance", {}).get("max_top1_pct", 0.80),
            max_top3_pct=overrides.get("feature_importance", {}).get("max_top3_pct", 0.95),
        ))

    def _register_paper_trading_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.paper_trading_checks import (
            SignalCorrelationCheck,
            SignalInterruptionCheck,
            SlippageDeviationCheck,
        )

        overrides = self._config.overrides

        engine.register(SignalCorrelationCheck(
            min_correlation=overrides.get("signal_correlation", {}).get("min_correlation", 0.8)
        ))
        engine.register(SlippageDeviationCheck(
            max_deviation_pct=overrides.get("slippage_deviation", {}).get("max_deviation_pct", 0.50)
        ))
        engine.register(SignalInterruptionCheck(
            max_consecutive_missing=overrides.get("signal_interruption", {}).get("max_consecutive_missing", 2),
            max_missing_ratio=overrides.get("signal_interruption", {}).get("max_missing_ratio", 0.05),
        ))

    def _register_production_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.production_checks import (
            HighVolSurvivalCheck,
            KillSwitchHistoryCheck,
        )

        overrides = self._config.overrides

        engine.register(KillSwitchHistoryCheck())
        engine.register(HighVolSurvivalCheck(
            max_dd_during_high_vol=overrides.get("high_vol_survival", {}).get("max_dd_during_high_vol", 25.0)
        ))

    def _register_process_checks(self, engine: RuleEngine, stage: str) -> None:
        from qp.validation.checks.process_checks import (
            CodeReviewCheck,
            ExperimentRecordCheck,
        )

        engine.register(CodeReviewCheck())
        engine.register(ExperimentRecordCheck())


# ------------------------------------------------------------------
# Stage → check category mapping
# ------------------------------------------------------------------

_STAGES_REQUIRING_BACKTEST: frozenset[str] = frozenset({
    "backtest_passed",
    "paper_trading",
    "shadow_production",
    "production",
})

_STAGES_REQUIRING_OVERFIT: frozenset[str] = frozenset({
    "backtest_passed",
    "paper_trading",
    "shadow_production",
    "production",
})

_STAGES_REQUIRING_PAPER: frozenset[str] = frozenset({
    "paper_trading",
    "shadow_production",
    "production",
})

_STAGES_REQUIRING_PRODUCTION: frozenset[str] = frozenset({
    "shadow_production",
    "production",
})

_STAGES_REQUIRING_PROCESS: frozenset[str] = frozenset({
    "production",
})
