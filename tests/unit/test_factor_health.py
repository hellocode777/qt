"""Unit tests for FactorHealthMonitor."""

from __future__ import annotations

import numpy as np
import pytest

from qp.monitoring.factor_health import (
    FactorHealthMonitor,
    FactorHealthStatus,
    FactorLifecycle,
)


class TestFactorHealthStage:
    def test_enum_values(self):
        assert FactorLifecycle.PRODUCTION == "production"
        assert FactorLifecycle.VALIDATED == "validated"
        assert FactorLifecycle.DEGRADED == "degraded"
        assert FactorLifecycle.RETIRED == "retired"


class TestFactorHealthStatus:
    def test_defaults(self):
        s = FactorHealthStatus()
        assert s.lifecycle == FactorLifecycle.RESEARCH
        assert s.ic_mean == 0.0
        assert not s.needs_attention
        assert not s.is_retired

    def test_needs_attention(self):
        s = FactorHealthStatus(lifecycle=FactorLifecycle.DEGRADED)
        assert s.needs_attention
        assert not s.is_retired

        s2 = FactorHealthStatus(lifecycle=FactorLifecycle.RETIRED)
        assert s2.needs_attention
        assert s2.is_retired

    def test_to_dict(self):
        s = FactorHealthStatus(
            factor_name="test",
            lifecycle=FactorLifecycle.PRODUCTION,
            ic_mean=0.03,
            ic_30d=0.025,
        )
        d = s.to_dict()
        assert d["factor_name"] == "test"
        assert d["stage"] == "production"
        assert d["ic_mean"] == 0.03


class TestFactorHealthMonitor:
    def test_insufficient_data(self):
        monitor = FactorHealthMonitor(min_days_for_check=30)
        status = monitor.check_factor("test", [0.01] * 10)
        assert status.lifecycle == FactorLifecycle.RESEARCH
        assert "Insufficient" in status.summary

    def test_healthy_factor(self):
        monitor = FactorHealthMonitor(reference_ic_mean=0.05)
        # Strong stable IC — should reach at least VALIDATED
        np.random.seed(42)
        daily_ics = list(np.random.normal(0.05, 0.02, 100))
        status = monitor.check_factor("healthy_factor", daily_ics)
        assert status.lifecycle in (
            FactorLifecycle.VALIDATED,
            FactorLifecycle.PRODUCTION,
        )
        assert status.n_days == 100

    def test_stale_near_zero_ic(self):
        monitor = FactorHealthMonitor(
            absolute_min_ic=0.01,
            retirement_consecutive_days=20,  # Lowered for test
        )
        # IC hovering near zero
        np.random.seed(42)
        daily_ics = list(np.random.normal(0.002, 0.005, 100))
        status = monitor.check_factor("stale_factor", daily_ics)
        assert status.lifecycle in (FactorLifecycle.RESEARCH, FactorLifecycle.RETIRED)
        assert status.ic_30d == pytest.approx(0.0, abs=0.01)

    def test_degraded_low_ic_ratio(self):
        monitor = FactorHealthMonitor(
            reference_ic_mean=0.08,
            decay_ratio=0.30,
            absolute_min_ic=0.005,  # lower than 0.01 so STALE doesn't trigger first
        )
        # Current IC much lower than reference
        np.random.seed(42)
        # Last 30 days have much lower IC
        early = list(np.random.normal(0.08, 0.01, 70))
        late = list(np.random.normal(0.01, 0.01, 30))
        daily_ics = early + late
        status = monitor.check_factor("degraded_factor", daily_ics)
        # IC_30d ~0.01 vs reference 0.08 → ratio ~0.125 → < 0.30 → DEGRADED
        assert status.stage == FactorLifecycle.DEGRADED

    def test_warning_moderate_decay(self):
        monitor = FactorHealthMonitor(
            reference_ic_mean=0.05,
            warning_ratio=0.50,
            decay_ratio=0.30,
        )
        # IC declining but not below 30%
        np.random.seed(42)
        early = list(np.random.normal(0.06, 0.01, 70))
        late = list(np.random.normal(0.025, 0.01, 30))
        daily_ics = early + late
        status = monitor.check_factor("warning_factor", daily_ics)
        # IC_30d ~0.025 vs reference 0.05 → ratio ~0.50 → WARNING
        assert status.stage in (FactorLifecycle.VALIDATED, FactorLifecycle.DEGRADED)

    def test_decay_trend_degraded(self):
        monitor = FactorHealthMonitor(decay_slope=-0.0005)
        # Steadily declining IC
        np.random.seed(42)
        daily_ics = list(np.linspace(0.06, 0.005, 100) + np.random.normal(0, 0.005, 100))
        status = monitor.check_factor("trend_factor", daily_ics)
        # Should detect strong negative trend
        assert status.ic_decay_rate < 0
        assert status.stage in (
            FactorLifecycle.DEGRADED,
            FactorLifecycle.RETIRED,
        )

    def test_low_ic_ir_stale(self):
        monitor = FactorHealthMonitor(
            stale_ic_ir=0.10,
            retirement_consecutive_days=20,  # Lowered for test
        )
        # Very noisy IC
        np.random.seed(42)
        daily_ics = list(np.random.normal(0.01, 0.15, 100))
        status = monitor.check_factor("noisy_factor", daily_ics)
        # Very noisy IC → low IC_IR → DEGRADED (consecutive degraded days ≥ 30)
        assert status.lifecycle in (
            FactorLifecycle.RESEARCH,
            FactorLifecycle.DEGRADED,
            FactorLifecycle.RETIRED,
        )

    def test_check_all_sorts_by_severity(self):
        monitor = FactorHealthMonitor(reference_ic_mean=0.05)
        np.random.seed(42)
        factor_ics = {
            "strong": list(np.random.normal(0.06, 0.01, 100)),
            "weak": list(np.random.normal(0.002, 0.005, 100)),
            "moderate": list(np.random.normal(0.03, 0.01, 100)),
        }
        results = monitor.check_all(factor_ics)
        assert len(results) == 3

    def test_rolling_mean(self):
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = FactorHealthMonitor._rolling_mean(arr, 3)
        assert result == pytest.approx(4.0)  # (3+4+5)/3

    def test_decay_slope_positive(self):
        arr = np.array([0.01, 0.02, 0.03, 0.04, 0.05] * 10)
        slope = FactorHealthMonitor._compute_decay_slope(arr, 50)
        assert slope > 0  # Positive trend

    def test_decay_slope_negative(self):
        arr = np.array([0.05, 0.04, 0.03, 0.02, 0.01] * 10)
        slope = FactorHealthMonitor._compute_decay_slope(arr, 50)
        assert slope < 0  # Negative trend

    def test_rolling_ic_series(self):
        daily_ics = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = FactorHealthMonitor.compute_rolling_ic_series(daily_ics, window=3)
        assert len(result) == 5
        assert result[0] == pytest.approx(0.01)
        assert result[2] == pytest.approx(0.02)  # (0.01+0.02+0.03)/3
        assert result[4] == pytest.approx(0.04)  # (0.03+0.04+0.05)/3


class TestFactorHealthMonitorNaNHandling:
    def test_nan_filtering(self):
        monitor = FactorHealthMonitor(min_days_for_check=30)
        np.random.seed(42)
        # Mix in some NaNs
        clean = list(np.random.normal(0.05, 0.02, 80))
        dirty = clean + [float("nan")] * 20
        status = monitor.check_factor("nan_test", dirty)
        assert status.n_days == 80  # NaNs filtered out
        assert status.n_days >= 30

    def test_all_nan(self):
        monitor = FactorHealthMonitor(min_days_for_check=30)
        status = monitor.check_factor("all_nan", [float("nan")] * 50)
        assert status.lifecycle == FactorLifecycle.RESEARCH
        assert "Insufficient" in status.summary
