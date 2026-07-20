"""ValidationResult — output of a Validation Gate run.

See rule.md §7.9 and ADR-016 for the complete specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qp.shared.types import ValidationStatus


@dataclass
class RuleResult:
    """Result of a single validation rule check.

    Attributes:
        rule_name: Unique rule identifier (e.g. 'rank_ic', 'sharpe_ratio').
        status: PASS or FAIL.
        score: Numeric score (higher = better).
        threshold: The threshold value that was checked against.
        actual_value: The observed value.
        detail: Human-readable explanation.
    """

    rule_name: str
    status: ValidationStatus
    score: float
    threshold: float | None = None
    actual_value: float | None = None
    detail: str = ""


@dataclass
class ValidationResult:
    """Aggregate result from the Validation Gate.

    A strategy must receive status=PASS on all rules before it can proceed
    to Paper Trading or Production (see StrategyLifecycle enum).

    Attributes:
        status: Overall PASS/FAIL — FAIL if any single rule failed.
        score: Weighted composite score (0–100).
        confidence: Confidence level (0–1) based on data quantity.
        rules: Per-rule results for audit trail.
        failed_rules: Convenience list of rule names that failed.
        recommendation: Human-readable next-step recommendation.
        metrics: Optional additional metrics (e.g. IC mean, Sharpe).
    """

    status: ValidationStatus = ValidationStatus.PASS
    score: float = 0.0
    confidence: float = 0.0
    rules: list[RuleResult] = field(default_factory=list)
    failed_rules: list[str] = field(default_factory=list)
    recommendation: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "failed_rules": self.failed_rules,
            "recommendation": self.recommendation,
            "rules": [
                {
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "score": r.score,
                    "threshold": r.threshold,
                    "actual_value": r.actual_value,
                    "detail": r.detail,
                }
                for r in self.rules
            ],
            "metrics": self.metrics,
        }
