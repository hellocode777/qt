"""Rule Engine — configurable validation gate framework.

All rules are configuration-driven (no hardcoded thresholds in rule logic).
See rule.md §7.9 and ADR-016.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from qp.shared.types import ValidationStatus
from qp.validation.result import RuleResult, ValidationResult


@dataclass
class ValidationContext:
    """Context passed to every validation rule.

    Carries all the data a rule might need: feature DataFrame, signal
    DataFrame, backtest metrics, strategy metadata, and any extra kwargs.
    """

    feature_df: Any = None  # Polars DataFrame: [trade_date, symbol, feature_value]
    price_df: Any = None  # Polars DataFrame: [trade_date, symbol, close]
    signal_df: Any = None  # Polars DataFrame: [symbol, rank, action]
    backtest_metrics: dict[str, float] = field(default_factory=dict)
    strategy_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseRule(ABC):
    """Abstract validation rule.

    Each concrete rule implements `check(context) -> RuleResult`.
    Thresholds are passed via constructor so they can be configured
    from config files or CLI without code changes.

    Usage:
        rule = RankICCheck(min_ic_mean=0.02)
        result = rule.check(context)
    """

    @property
    @abstractmethod
    def rule_name(self) -> str:
        """Unique rule identifier (e.g. 'rank_ic', 'sharpe_ratio')."""
        ...

    @abstractmethod
    def check(self, context: ValidationContext) -> RuleResult:
        """Execute the rule against the given context.

        Returns a RuleResult with PASS/FAIL status and supporting detail.
        """
        ...


class RuleEngine:
    """Registry-based rule engine.

    Runs all registered rules against a ValidationContext and produces
    an aggregate ValidationResult.

    Usage:
        engine = RuleEngine()
        engine.register(RankICCheck(min_ic_mean=0.02))
        engine.register(ICIRCheck(min_ic_ir=0.3))
        result = engine.validate(context)
        if result.passed:
            print("Strategy passed all checks")
    """

    def __init__(self) -> None:
        self._rules: list[BaseRule] = []

    def register(self, rule: BaseRule) -> None:
        """Register a validation rule."""
        self._rules.append(rule)

    def validate(self, context: ValidationContext) -> ValidationResult:
        """Run all registered rules and produce an aggregate result.

        Returns:
            ValidationResult with overall PASS/FAIL status.
            FAIL if any single rule fails.
        """
        rule_results: list[RuleResult] = []
        failed_names: list[str] = []

        for rule in self._rules:
            result = rule.check(context)
            rule_results.append(result)
            if result.status == ValidationStatus.FAIL:
                failed_names.append(result.rule_name)

        if not rule_results:
            return ValidationResult(
                status=ValidationStatus.PASS,
                score=100.0,
                confidence=0.0,
                recommendation="No rules configured — gate is open.",
            )

        # Composite score: average of all rule scores
        composite_score = sum(r.score for r in rule_results) / len(rule_results)
        # Confidence: fraction of rules that passed
        confidence = 1.0 - len(failed_names) / len(rule_results)

        overall_status = ValidationStatus.FAIL if failed_names else ValidationStatus.PASS

        if failed_names:
            recommendation = (
                f"Strategy failed {len(failed_names)}/{len(rule_results)} rules: "
                + ", ".join(failed_names)
                + ". Fix the issues above before promoting to Paper Trading."
            )
        else:
            recommendation = "All validation checks passed. Strategy may proceed to Paper Trading."

        return ValidationResult(
            status=overall_status,
            score=round(composite_score, 2),
            confidence=round(confidence, 2),
            rules=rule_results,
            failed_rules=failed_names,
            recommendation=recommendation,
        )
