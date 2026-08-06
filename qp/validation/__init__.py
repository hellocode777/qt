"""Validation Layer — Gate between Research and Strategy.

Exports the Rule Engine, all 18 built-in checks across 4 stages, and the
ValidationResult model.  See rule.md §7.9, §10.1–§10.2.

Check inventory (20 total):
  Factor (10): RankIC, IC_IR, t-stat, Stratification, Neutralization, MinSample,
               Coverage, MissingRate, MaxCorrelation, TurnoverLimit
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
    CoverageCheck,
    ICIRCheck,
    MaxCorrelationCheck,
    MinSamplePeriodCheck,
    MissingRateCheck,
    NeutralizationCheck,
    RankICCheck,
    StratificationCheck,
    TStatCheck,
    TurnoverLimitCheck,
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
from qp.validation.gate_registry_bridge import (
    GateRegistryBridge,
    gate_and_promote,
)
from qp.validation.pipeline import ValidationPipeline, ValidationPipelineConfig
from qp.validation.result import GateDecision, GateResult, RuleResult, ValidationResult

__all__ = [
    # Framework
    "BaseRule",
    # Process (2)
    "CodeReviewCheck",
    "CostAdjustedCheck",
    "CoverageCheck",
    "ExperimentRecordCheck",
    "FeatureImportanceCheck",
    "GateDecision",
    "GateRegistryBridge",
    "GateResult",
    "HighVolSurvivalCheck",
    "ICIRCheck",
    # Shadow → Production (2)
    "KillSwitchHistoryCheck",
    "MaxCorrelationCheck",
    "MaxDrawdownCheck",
    "MinSamplePeriodCheck",
    "MissingRateCheck",
    "NeutralizationCheck",
    # Overfit (2)
    "OverfitCheck",
    # Factor (10)
    "RankICCheck",
    "RuleEngine",
    "RuleResult",
    # Backtest (4)
    "SharpeCheck",
    # Paper Trading (3)
    "SignalCorrelationCheck",
    "SignalInterruptionCheck",
    "SlippageDeviationCheck",
    "StratificationCheck",
    "TStatCheck",
    "TurnoverCheck",
    "TurnoverLimitCheck",
    "ValidationContext",
    "ValidationPipeline",
    "ValidationPipelineConfig",
    "ValidationResult",
    "gate_and_promote",
]
