"""ValidationGate — orchestrates all validation checks before data publication.

Implements data_layer.md §1.3: the Data Quality Gate that sits between
Cleaning Engine and Feature Store / Strategy layer.

Architecture:
  Cleaning Engine → ValidationGate → [Silver Tier] → Feature Store
                        │
                   CircuitBreaker
                   (halts on critical failures)

Usage::

    gate = ValidationGate()
    report = gate.validate(cleaned_df, calendar=trading_dates)
    if report.passed:
        save_to_silver(cleaned_df)
    else:
        log_and_alert(report)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl
from loguru import logger

from qp.data.validation.checks import (
    check_gaps,
    check_monotonicity,
    check_non_negative,
    check_null_rate,
    check_ohlc_physics,
    check_price_limits,
)
from qp.data.validation.circuit_breaker import (
    BreakerConfig,
    BreakerResult,
    CircuitBreaker,
)
from qp.data.validation.drift import check_all_drift
from qp.data.validation.result import CheckResult, ValidationReport

if TYPE_CHECKING:
    from pandera.api.polars.model import DataFrameModel

# ------------------------------------------------------------------
# Gate configuration
# ------------------------------------------------------------------


@dataclass
class GateConfig:
    """Configuration for the ValidationGate.

    Attributes:
        enable_gaps: Run gap detection check.
        enable_monotonicity: Run monotonicity check.
        enable_ohlc_physics: Run OHLC physical logic check.
        enable_price_limits: Run price limit check.
        enable_non_negative: Run non-negative constraints check.
        enable_null_rate: Run null rate check.
        enable_drift: Run PSI + summary-stat drift checks.
        enable_pandera: Run Pandera schema validation (if schema provided).
        pandera_schema: Pandera DataFrameModel class to validate against.
        max_gap_days: Maximum days between consecutive rows before a gap is flagged.
        max_null_rate: Maximum allowed null rate for key columns.
        null_rate_columns: Columns to check for nulls.
        breaker_config: Circuit breaker configuration.
    """

    enable_gaps: bool = True
    enable_monotonicity: bool = True
    enable_ohlc_physics: bool = True
    enable_price_limits: bool = True
    enable_non_negative: bool = True
    enable_null_rate: bool = True
    enable_drift: bool = False  # Requires baseline data — off by default
    enable_pandera: bool = False  # Requires pandera_schema to be set

    max_gap_days: int = 5
    max_null_rate: float = 0.001

    null_rate_columns: list[str] = field(
        default_factory=lambda: ["open", "high", "low", "close", "volume"]
    )

    pandera_schema: type[DataFrameModel] | None = None
    breaker_config: BreakerConfig | None = None


# ------------------------------------------------------------------
# Validation Gate
# ------------------------------------------------------------------


class ValidationGate:
    """Central data quality gate — runs all configured checks.

    Design principles:
      - Checks are pure functions (no side effects).
      - Circuit breaker is fail-closed (when in doubt, block data).
      - All errors are logged with full context for audit.
      - Per-check enable/disable via GateConfig.

    Usage::

        gate = ValidationGate(GateConfig())
        report = gate.validate(df, calendar=calendar)
        # report.passed → True if no ERROR-severity failures
        # report.circuit_triggered → True if breaker tripped
    """

    def __init__(self, config: GateConfig | None = None) -> None:
        self.config = config or GateConfig()
        self.breaker = CircuitBreaker(self.config.breaker_config)
        self._run_history: list[ValidationReport] = []

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def validate(
        self,
        df: pl.DataFrame,
        calendar: list[str] | None = None,
        baseline: pl.DataFrame | None = None,
    ) -> ValidationReport:
        """Run all enabled validation checks against a DataFrame.

        Args:
            df: Cleaned DataFrame to validate (Polars).
            calendar: Optional trading calendar for gap detection.
            baseline: Optional baseline DataFrame for drift checks.

        Returns:
            ValidationReport with per-check results and circuit breaker outcome.
        """
        logger.info("ValidationGate: 开始校验 ({} 行, {} 列)", df.height, len(df.columns))

        all_checks: list[CheckResult] = []

        # ── Pandera schema check (first — catches type/schema issues early) ──
        if self.config.enable_pandera and self.config.pandera_schema is not None:
            from qp.data.validation.pandera_validator import PanderaValidator

            all_checks.append(PanderaValidator.validate(df, self.config.pandera_schema))

        # ── Physical checks ──
        if self.config.enable_gaps:
            all_checks.append(
                check_gaps(df, max_allowed_gap_days=self.config.max_gap_days, calendar=calendar)
            )

        if self.config.enable_monotonicity:
            all_checks.append(check_monotonicity(df))

        if self.config.enable_ohlc_physics:
            all_checks.append(check_ohlc_physics(df))

        if self.config.enable_price_limits:
            all_checks.append(check_price_limits(df))

        if self.config.enable_non_negative:
            all_checks.append(check_non_negative(df))

        if self.config.enable_null_rate:
            all_checks.append(
                check_null_rate(
                    df,
                    required_columns=self.config.null_rate_columns,
                    max_null_rate=self.config.max_null_rate,
                )
            )

        # ── Drift checks (only if baseline provided) ──
        if self.config.enable_drift and baseline is not None:
            all_checks.extend(check_all_drift(df, baseline))

        # ── Build report ──
        report = ValidationReport(checks=all_checks)

        # ── Circuit breaker evaluation ──
        breaker_result = self.breaker.evaluate(all_checks)
        report.circuit_triggered = breaker_result.tripped

        # ── Log results ──
        self._log_report(report, breaker_result)

        self._run_history.append(report)
        return report

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def quick_check(self, df: pl.DataFrame) -> ValidationReport:
        """Fast validation with defaults — no calendar, no baseline.

        Use this inside DataPipeline.run() for the Silver-tier gate.
        """
        return self.validate(df)

    def check_schema_only(self, df: pl.DataFrame) -> list[CheckResult]:
        """Run only schema-level checks (null rate, non-negative).

        Useful after CleaningEngine for a lightweight gate.
        """
        results: list[CheckResult] = []
        if self.config.enable_null_rate:
            results.append(
                check_null_rate(
                    df,
                    required_columns=self.config.null_rate_columns,
                    max_null_rate=self.config.max_null_rate,
                )
            )
        if self.config.enable_non_negative:
            results.append(check_non_negative(df))
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _log_report(report: ValidationReport, breaker: BreakerResult) -> None:
        """Log a human-readable validation summary."""
        passed = report.passed_checks
        total = report.total_checks

        if report.passed:
            logger.info("✓ ValidationGate: {}/{} 校验通过", passed, total)
        else:
            logger.warning(
                "✗ ValidationGate: {}/{} 校验通过, {} 失败", passed, total, report.failed_checks
            )

        for check in report.checks:
            icon = "✓" if check.passed else "✗"
            sev = f"[{check.severity.value.upper()}]"
            logger.info("  {} {} {} — {}", icon, sev, check.check_name, check.detail)

        if report.circuit_triggered:
            logger.error("!!! 断路器已触发 — 数据被阻止进入下一层 !!!")
            logger.error("  原因: {}", breaker.reason)
