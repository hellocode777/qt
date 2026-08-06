"""Data Validation — quality gate before dataset publication (ADR-016).

Implements data_layer.md §1.3: circuit breaker + data quality checks.

Modules:
  - result.py: CheckResult, ValidationReport, Severity
  - checks.py: Pure-function validation checks (gaps, monotonicity, OHLC, etc.)
  - drift.py: PSI (Population Stability Index) + summary-statistic jump detection
  - circuit_breaker.py: CircuitBreaker — halts pipeline on quality breaches
  - gate.py: ValidationGate — orchestrates all checks with breaker integration
  - pandera_schemas.py: Declarative Pandera schemas for Data Products
  - pandera_validator.py: Bridge between Pandera and CheckResult types

Quick start::

    from qp.data.validation import ValidationGate, GateConfig

    gate = ValidationGate(GateConfig())
    report = gate.validate(cleaned_df)
    if report.passed:
        publish_to_silver(cleaned_df)

    # With Pandera schema validation:
    from qp.data.validation.pandera_schemas import DailyPriceSchema

    config = GateConfig(enable_pandera=True, pandera_schema=DailyPriceSchema)
    gate = ValidationGate(config)
"""

from qp.data.validation.checks import (
    check_financial_balance,
    check_gaps,
    check_monotonicity,
    check_non_negative,
    check_null_rate,
    check_ohlc_physics,
    check_pit_delay,
    check_price_limits,
    run_physical_checks,
)
from qp.data.validation.circuit_breaker import (
    BreakerConfig,
    BreakerResult,
    CircuitBreaker,
)
from qp.data.validation.drift import (
    check_all_drift,
    check_psi_drift,
    check_summary_stat_drift,
    compute_psi,
)
from qp.data.validation.gate import GateConfig, ValidationGate
from qp.data.validation.pandera_schemas import (
    BalanceSheetSchema,
    DailyPriceExtendedSchema,
    DailyPriceSchema,
    FundamentalIndicatorSchema,
)
from qp.data.validation.pandera_validator import PanderaValidator
from qp.data.validation.result import CheckResult, Severity, ValidationReport

__all__ = [
    "BalanceSheetSchema",
    "BreakerConfig",
    "BreakerResult",
    # Results
    "CheckResult",
    # Circuit breaker
    "CircuitBreaker",
    "DailyPriceExtendedSchema",
    "DailyPriceSchema",
    "FundamentalIndicatorSchema",
    "GateConfig",
    # Pandera
    "PanderaValidator",
    "Severity",
    # Gate
    "ValidationGate",
    "ValidationReport",
    "check_all_drift",
    # Checks
    "check_financial_balance",
    "check_gaps",
    "check_monotonicity",
    "check_non_negative",
    "check_null_rate",
    "check_ohlc_physics",
    "check_pit_delay",
    "check_price_limits",
    "check_psi_drift",
    "check_summary_stat_drift",
    # Drift
    "compute_psi",
    "run_physical_checks",
]
