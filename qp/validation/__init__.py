"""Validation Layer — Gate between Research and Strategy.

Exports the Rule Engine, all built-in checks, and the ValidationResult model.
See rule.md §7.9 for the complete specification.
"""

from qp.validation.checks.backtest_checks import (
    MaxDrawdownCheck,
    SharpeCheck,
    TurnoverCheck,
)
from qp.validation.checks.factor_checks import (
    ICIRCheck,
    RankICCheck,
    StratificationCheck,
    TStatCheck,
)
from qp.validation.checks.overfit_checks import (
    FeatureImportanceCheck,
    OverfitCheck,
)
from qp.validation.engine import BaseRule, RuleEngine, ValidationContext
from qp.validation.result import RuleResult, ValidationResult

__all__ = [
    "BaseRule",
    "RuleEngine",
    "RuleResult",
    "ValidationContext",
    "ValidationResult",
    "RankICCheck",
    "ICIRCheck",
    "TStatCheck",
    "StratificationCheck",
    "OverfitCheck",
    "FeatureImportanceCheck",
    "SharpeCheck",
    "MaxDrawdownCheck",
    "TurnoverCheck",
]
