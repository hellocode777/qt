"""Tests for qp.data.validation.gate and circuit_breaker — gate orchestration."""

from __future__ import annotations

import polars as pl

from qp.data.validation.circuit_breaker import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
)
from qp.data.validation.gate import GateConfig, ValidationGate
from qp.data.validation.result import CheckResult, Severity, ValidationReport

# ==================================================================
# Helper
# ==================================================================


def _clean_df() -> pl.DataFrame:
    """3 symbols × 5 days of clean OHLCV data."""
    rows = []
    for sym in ["000001", "000002", "000003"]:
        for day in range(15, 20):
            rows.append(
                {
                    "trade_date": f"2024-01-{day:02d}",
                    "symbol": sym,
                    "open": 10.0 + (day - 15) * 0.1,
                    "high": 10.8 + (day - 15) * 0.1,
                    "low": 9.8 + (day - 15) * 0.1,
                    "close": 10.5 + (day - 15) * 0.1,
                    "volume": 1000000.0,
                }
            )
    return pl.DataFrame(rows).with_columns(pl.col("trade_date").str.to_date())


# ==================================================================
# ValidationReport
# ==================================================================


class TestValidationReport:
    def test_all_pass(self):
        report = ValidationReport(
            checks=[
                CheckResult("a", True, Severity.ERROR, "ok"),
                CheckResult("b", True, Severity.WARNING, "ok"),
            ]
        )
        assert report.passed is True
        assert report.passed_checks == 2
        assert report.failed_checks == 0

    def test_one_error_fails_report(self):
        report = ValidationReport(
            checks=[
                CheckResult("a", True, Severity.ERROR, "ok"),
                CheckResult("b", False, Severity.ERROR, "bad"),
            ]
        )
        assert report.passed is False
        assert report.passed_checks == 1
        assert report.failed_checks == 1

    def test_warning_only_does_not_fail_report(self):
        """WARNING severity alone doesn't cause report.passed=False."""
        report = ValidationReport(
            checks=[
                CheckResult("a", True, Severity.ERROR, "ok"),
                CheckResult("b", False, Severity.WARNING, "heads up"),
            ]
        )
        assert report.passed is True  # No ERROR failures
        assert report.passed_checks == 1

    def test_summary_format(self):
        report = ValidationReport(
            checks=[
                CheckResult("a", True, Severity.ERROR, "ok"),
                CheckResult("b", False, Severity.ERROR, "bad"),
            ]
        )
        assert "1/2" in report.summary
        assert "1 errors" in report.summary

    def test_circuit_triggered_in_summary(self):
        report = ValidationReport(checks=[], circuit_triggered=True)
        assert "CIRCUIT BREAKER" in report.summary


# ==================================================================
# CircuitBreaker
# ==================================================================


class TestCircuitBreaker:
    def test_default_closed(self):
        breaker = CircuitBreaker()
        assert breaker.state == BreakerState.CLOSED
        assert not breaker.is_open

    def test_no_failures_does_not_trip(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        results = [
            CheckResult("a", True, Severity.ERROR, "ok"),
            CheckResult("b", True, Severity.WARNING, "ok"),
        ]
        outcome = breaker.evaluate(results)
        assert not outcome.tripped
        assert breaker.state == BreakerState.CLOSED

    def test_single_error_trips_with_default_config(self):
        """Default max_critical_failures=0 means ANY error trips breaker."""
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        results = [
            CheckResult("a", False, Severity.ERROR, "bad"),
        ]
        outcome = breaker.evaluate(results)
        assert outcome.tripped
        assert breaker.state == BreakerState.OPEN

    def test_max_critical_failures_allows_one(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=1))
        results = [
            CheckResult("a", False, Severity.ERROR, "bad"),
        ]
        outcome = breaker.evaluate(results)
        assert not outcome.tripped

    def test_two_errors_trip_when_max_is_one(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=1))
        results = [
            CheckResult("a", False, Severity.ERROR, "bad"),
            CheckResult("b", False, Severity.ERROR, "also bad"),
        ]
        outcome = breaker.evaluate(results)
        assert outcome.tripped

    def test_warnings_trip_when_above_threshold(self):
        breaker = CircuitBreaker(BreakerConfig(max_warnings=2))
        results = [
            CheckResult("a", False, Severity.WARNING, "warn"),
            CheckResult("b", False, Severity.WARNING, "warn"),
            CheckResult("c", False, Severity.WARNING, "warn"),
        ]
        outcome = breaker.evaluate(results)
        assert outcome.tripped

    def test_warnings_below_threshold_pass(self):
        breaker = CircuitBreaker(BreakerConfig(max_warnings=5))
        results = [
            CheckResult("a", False, Severity.WARNING, "warn"),
            CheckResult("b", False, Severity.WARNING, "warn"),
        ]
        outcome = breaker.evaluate(results)
        assert not outcome.tripped

    def test_manual_reset(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        breaker.evaluate([CheckResult("a", False, Severity.ERROR, "bad")])
        assert breaker.state == BreakerState.OPEN
        breaker.reset()
        assert breaker.state == BreakerState.CLOSED

    def test_half_open(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        breaker.evaluate([CheckResult("a", False, Severity.ERROR, "bad")])
        assert breaker.state == BreakerState.OPEN
        breaker.test_half_open()
        assert breaker.state == BreakerState.HALF_OPEN

    def test_half_open_closes_on_clean_batch(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        breaker.evaluate([CheckResult("a", False, Severity.ERROR, "bad")])
        breaker.test_half_open()
        outcome = breaker.evaluate([CheckResult("b", True, Severity.ERROR, "all good")])
        assert not outcome.tripped
        assert breaker.state == BreakerState.CLOSED

    def test_require_all_checks(self):
        breaker = CircuitBreaker(BreakerConfig(require_all_checks=True))
        results = [
            CheckResult("a", True, Severity.ERROR, "ok"),
            CheckResult("b", False, Severity.INFO, "info fail"),
        ]
        outcome = breaker.evaluate(results)
        assert outcome.tripped

    def test_breaker_result_includes_reason(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        outcome = breaker.evaluate([CheckResult("x", False, Severity.ERROR, "broken")])
        assert "1 critical failures" in outcome.reason
        assert "x" in outcome.blocked_checks

    def test_trip_count_increments(self):
        breaker = CircuitBreaker(BreakerConfig(max_critical_failures=0))
        assert breaker._trip_count == 0
        breaker.evaluate([CheckResult("a", False, Severity.ERROR, "bad")])
        assert breaker._trip_count == 1
        breaker.reset()
        breaker.evaluate([CheckResult("b", False, Severity.ERROR, "bad")])
        assert breaker._trip_count == 1  # Reset clears count

    def test_auto_reset(self):
        breaker = CircuitBreaker(
            BreakerConfig(
                max_critical_failures=0,
                auto_reset_after_seconds=0.001,  # ~1ms, immediate
            )
        )
        breaker.evaluate([CheckResult("a", False, Severity.ERROR, "bad")])
        assert breaker.state == BreakerState.OPEN
        # Auto-reset should trigger after the configured time
        import time

        time.sleep(0.01)
        assert breaker.state == BreakerState.CLOSED


# ==================================================================
# ValidationGate
# ==================================================================


class TestValidationGate:
    def test_all_checks_pass_on_clean_data(self):
        gate = ValidationGate(GateConfig())
        df = _clean_df()
        report = gate.validate(df)
        assert report.passed is True
        assert report.circuit_triggered is False

    def test_reports_all_check_names(self):
        gate = ValidationGate(GateConfig())
        df = _clean_df()
        report = gate.validate(df)
        names = {c.check_name for c in report.checks}
        assert "gaps_check" in names
        assert "monotonicity_check" in names
        assert "ohlc_physics_check" in names
        assert "price_limit_check" in names
        assert "non_negative_check" in names
        assert "null_rate_check" in names

    def test_disable_all_checks(self):
        config = GateConfig(
            enable_gaps=False,
            enable_monotonicity=False,
            enable_ohlc_physics=False,
            enable_price_limits=False,
            enable_non_negative=False,
            enable_null_rate=False,
        )
        gate = ValidationGate(config)
        report = gate.validate(_clean_df())
        assert report.total_checks == 0
        assert report.passed is True

    def test_selective_checks(self):
        config = GateConfig(
            enable_gaps=False,
            enable_monotonicity=False,
            enable_ohlc_physics=True,
            enable_price_limits=False,
            enable_non_negative=False,
            enable_null_rate=False,
        )
        gate = ValidationGate(config)
        report = gate.validate(_clean_df())
        assert report.total_checks == 1
        assert report.checks[0].check_name == "ohlc_physics_check"

    def test_bad_data_fails_gate(self):
        """Insert a High<Low violation to trigger gate failure."""
        gate = ValidationGate(GateConfig())
        bad_df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "symbol": ["000001"],
                "open": [10.0],
                "high": [9.0],  # high < low
                "low": [11.0],
                "close": [10.2],
                "volume": [1000000.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        report = gate.validate(bad_df)
        assert report.passed is False
        assert any(
            c.check_name == "ohlc_physics_check" and not c.passed for c in report.checks
        )

    def test_circuit_breaker_integration(self):
        """Gate with zero-tolerance breaker trips on any error."""
        config = GateConfig(breaker_config=BreakerConfig(max_critical_failures=0))
        gate = ValidationGate(config)
        bad_df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "symbol": ["000001"],
                "open": [10.0],
                "high": [9.0],
                "low": [11.0],
                "close": [10.2],
                "volume": [1000000.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        report = gate.validate(bad_df)
        assert report.circuit_triggered is True

    def test_quick_check(self):
        gate = ValidationGate(GateConfig())
        report = gate.quick_check(_clean_df())
        assert report.total_checks >= 1
        assert report.passed is True

    def test_check_schema_only(self):
        gate = ValidationGate(GateConfig())
        results = gate.check_schema_only(_clean_df())
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_drift_enabled_with_baseline(self):
        config = GateConfig(enable_drift=True)
        gate = ValidationGate(config)
        df = _clean_df()
        report = gate.validate(df, baseline=df.clone())
        drift_checks = [c for c in report.checks if "drift" in c.check_name]
        assert len(drift_checks) == 2

    def test_drift_disabled_by_default(self):
        gate = ValidationGate(GateConfig())
        report = gate.validate(_clean_df(), baseline=_clean_df())
        drift_checks = [c for c in report.checks if "drift" in c.check_name]
        assert len(drift_checks) == 0

    def test_run_history_recorded(self):
        gate = ValidationGate(GateConfig())
        gate.validate(_clean_df())
        gate.validate(_clean_df())
        assert len(gate._run_history) == 2

    def test_with_calendar(self):
        gate = ValidationGate(GateConfig())
        # Include dates NOT in the data to trigger calendar gap detection
        calendar = [
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
            "2024-01-18",
            "2024-01-19",
            "2024-01-20",
        ]
        report = gate.validate(_clean_df(), calendar=calendar)
        gaps_check = next(c for c in report.checks if c.check_name == "gaps_check")
        # 2024-01-20 is not in the data
        assert "missing_calendar_dates" in gaps_check.metadata
        assert "2024-01-20" in gaps_check.metadata["missing_calendar_dates"]
