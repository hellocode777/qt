"""Validation Layer — Gate between Research and Strategy.

Exports the Rule Engine, all 14 built-in checks across 4 stages, and the
ValidationResult model.  See rule.md §7.9, §10.1–§10.2.

Check inventory (16 total):
  Factor (6): RankIC, IC_IR, t-stat, Stratification, Neutralization, MinSample
  Backtest (4): Sharpe, MaxDrawdown, Turnover, CostAdjusted
  Overfit (2): Overfit (OOS/IS), FeatureImportance
  Paper Trading (3): SignalCorrelation, Slippage, SignalInterruption
  Shadow→Prod (2): KillSwitchHistory, HighVolSurvival
  Process (2): CodeReview, ExperimentRecord
"""

from qp.validation.checks.backtest_checks import (
    CostAdjustedCheck,
    MaxDrawdownCheck,
    SharpeCheck,
    TurnoverCheck,
)
from qp.validation.checks.factor_checks import (
    ICIRCheck,
    MinSamplePeriodCheck,
    NeutralizationCheck,
    RankICCheck,
    StratificationCheck,
    TStatCheck,
)
from qp.validation.checks.overfit_checks import (
    FeatureImportanceCheck,
    OverfitCheck,
)
from qp.validation.checks.paper_trading_checks import (
    SignalCorrelationCheck,
    SignalInterruptionCheck,
    SlippageDeviationCheck,
)
from qp.validation.checks.process_checks import (
    CodeReviewCheck,
    ExperimentRecordCheck,
)
from qp.validation.checks.production_checks import (
    HighVolSurvivalCheck,
    KillSwitchHistoryCheck,
)
from qp.validation.engine import BaseRule, RuleEngine, ValidationContext
from qp.validation.pipeline import ValidationPipeline, ValidationPipelineConfig
from qp.validation.result import RuleResult, ValidationResult

__all__ = [
    # Framework
    "BaseRule",
    "RuleEngine",
    "RuleResult",
    "ValidationContext",
    "ValidationResult",
    "ValidationPipeline",
    "ValidationPipelineConfig",
    # Factor (6)
    "RankICCheck",
    "ICIRCheck",
    "TStatCheck",
    "StratificationCheck",
    "NeutralizationCheck",
    "MinSamplePeriodCheck",
    # Backtest (4)
    "SharpeCheck",
    "MaxDrawdownCheck",
    "TurnoverCheck",
    "CostAdjustedCheck",
    # Overfit (2)
    "OverfitCheck",
    "FeatureImportanceCheck",
    # Paper Trading (3)
    "SignalCorrelationCheck",
    "SlippageDeviationCheck",
    "SignalInterruptionCheck",
    # Shadow → Production (2)
    "KillSwitchHistoryCheck",
    "HighVolSurvivalCheck",
    # Process (2)
    "CodeReviewCheck",
    "ExperimentRecordCheck",
]
