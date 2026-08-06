"""Validation result types — structured outputs from all validation checks.

Data Layer §3: every check produces a CheckResult; ValidationGate aggregates
them into a ValidationReport that the circuit breaker can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """Check failure severity — drives circuit breaker logic."""

    ERROR = "error"  # Blocks pipeline (data is corrupt)
    WARNING = "warning"  # Does not block but triggers alert
    INFO = "info"  # Purely informational


@dataclass
class CheckResult:
    """Output of a single validation check.

    Attributes:
        check_name: Unique check identifier (e.g. 'gaps_check').
        passed: True if the check passed.
        severity: ERROR blocks pipeline, WARNING alerts only.
        detail: Human-readable summary of what was checked.
        affected_rows: Number of rows that failed the check.
        metadata: Arbitrary extra data (e.g. PSI score, gap dates).
    """

    check_name: str
    passed: bool
    severity: Severity = Severity.ERROR
    detail: str = ""
    affected_rows: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Aggregate result from running all validation checks.

    Attributes:
        passed: True if no ERROR-severity checks failed.
        checks: Per-check results.
        total_checks: Number of checks executed.
        passed_checks: Number that passed.
        failed_checks: Number that failed.
        circuit_triggered: True if the circuit breaker halted the pipeline.
        summary: One-line summary for logging.
    """

    checks: list[CheckResult] = field(default_factory=list)
    circuit_triggered: bool = False

    @property
    def passed(self) -> bool:
        errors = [
            c for c in self.checks if c.severity == Severity.ERROR and not c.passed
        ]
        return len(errors) == 0

    @property
    def total_checks(self) -> int:
        return len(self.checks)

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def summary(self) -> str:
        errors = [
            c for c in self.checks if c.severity == Severity.ERROR and not c.passed
        ]
        warnings = [
            c for c in self.checks if c.severity == Severity.WARNING and not c.passed
        ]
        parts = [f"{self.passed_checks}/{self.total_checks} checks passed"]
        if errors:
            parts.append(f"{len(errors)} errors")
        if warnings:
            parts.append(f"{len(warnings)} warnings")
        if self.circuit_triggered:
            parts.append("CIRCUIT BREAKER TRIGGERED")
        return " | ".join(parts)
