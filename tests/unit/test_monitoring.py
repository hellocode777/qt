"""Tests for Monitoring Layer — drift, decay, regime, kill switch."""

import numpy as np


class TestDriftMonitor:
    """Test PSI and distribution drift detection."""

    def test_psi_identical(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        data = np.random.randn(1000)
        psi = DriftMonitor.compute_psi(data, data)
        assert psi < 0.01  # Near zero for identical distributions

    def test_psi_different(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        expected = np.random.normal(0, 1, 5000)
        actual = np.random.normal(2, 1, 5000)  # Shifted mean
        psi = DriftMonitor.compute_psi(expected, actual)
        assert psi > 0.1  # Significant difference

    def test_psi_empty(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        psi = DriftMonitor.compute_psi(np.array([]), np.array([]))
        assert psi == 0.0

    def test_psi_single_element(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        psi = DriftMonitor.compute_psi(np.array([1.0]), np.array([1.0]))
        assert psi == 0.0

    def test_check_feature(self) -> None:
        from qp.monitoring.drift import DriftMonitor, DriftSeverity

        monitor = DriftMonitor()
        ref = np.random.normal(0, 1, 10000)
        cur = np.random.normal(0, 1.05, 10000)  # Slightly different
        result = monitor.check_feature(ref, cur, "test_feature")
        assert result.feature_name == "test_feature"
        assert result.severity in (
            DriftSeverity.NONE,
            DriftSeverity.MILD,
            DriftSeverity.SIGNIFICANT,
        )

    def test_ks_identical(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        data = np.random.normal(0, 1, 1000)
        ks_stat, ks_pval = DriftMonitor.compute_ks(data, data)
        assert ks_stat < 0.1  # Small KS for identical
        assert ks_pval > 0.05  # Not significantly different

    def test_ks_different(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        a = np.random.normal(0, 1, 1000)
        b = np.random.normal(3, 1, 1000)
        ks_stat, ks_pval = DriftMonitor.compute_ks(a, b)
        assert ks_stat > 0.5  # Large difference

    def test_wasserstein(self) -> None:
        from qp.monitoring.drift import DriftMonitor

        a = np.random.normal(0, 1, 500)
        b = np.random.normal(0, 1, 500)
        dist = DriftMonitor.compute_wasserstein(a, b)
        assert dist >= 0  # Non-negative


class TestModelDecayDetector:
    """Test model decay detection."""

    def test_healthy(self) -> None:
        from qp.monitoring.model_decay import DecayStage, ModelDecayDetector

        detector = ModelDecayDetector(training_ic_mean=0.035)
        status = detector.check(rolling_ic=0.030)
        assert status.stage == DecayStage.HEALTHY
        assert status.ic_ratio > 0.5

    def test_decaying(self) -> None:
        from qp.monitoring.model_decay import DecayStage, ModelDecayDetector

        detector = ModelDecayDetector(training_ic_mean=0.035)
        status = detector.check(rolling_ic=0.005)  # 0.005 / 0.035 = 14%
        assert status.stage in (DecayStage.DECAYING, DecayStage.STALE)
        assert status.needs_attention is True

    def test_warning(self) -> None:
        from qp.monitoring.model_decay import DecayStage, ModelDecayDetector

        detector = ModelDecayDetector(training_ic_mean=0.035)
        status = detector.check(rolling_ic=0.015)  # 0.015 / 0.035 = 43%
        assert status.stage == DecayStage.WARNING

    def test_stale(self) -> None:
        from qp.monitoring.model_decay import DecayStage, ModelDecayDetector

        detector = ModelDecayDetector(training_ic_mean=0.035, absolute_min_ic=0.010)
        status = detector.check(rolling_ic=0.002)
        assert status.stage == DecayStage.STALE

    def test_rolling_ic_computation(self) -> None:
        from qp.monitoring.model_decay import ModelDecayDetector

        daily_ic = [0.03, 0.04, 0.02, 0.035, 0.025]
        result = ModelDecayDetector.compute_rolling_ic(daily_ic, window=3)
        assert len(result) == len(daily_ic)

    def test_ic_decay_rate(self) -> None:
        from qp.monitoring.model_decay import ModelDecayDetector

        # Declining IC
        daily_ic = [0.04, 0.035, 0.03, 0.025, 0.02, 0.015, 0.01, 0.005] * 10
        rate = ModelDecayDetector.ic_decay_rate(daily_ic, window=60)
        assert rate < 0  # Negative slope = declining


class TestKillSwitch:
    """Test Kill Switch triggers."""

    def test_drawdown_trigger_not_fired(self) -> None:
        from qp.monitoring.kill_switch import DrawdownTrigger

        trigger = DrawdownTrigger(historical_max_dd=0.15, ratio=1.5)
        result = trigger.evaluate({"current_drawdown": 0.10})
        assert result["fired"] is False

    def test_drawdown_trigger_fired(self) -> None:
        from qp.monitoring.kill_switch import DrawdownTrigger

        trigger = DrawdownTrigger(historical_max_dd=0.15, ratio=1.5)
        result = trigger.evaluate({"current_drawdown": 0.30})
        assert result["fired"] is True

    def test_portfolio_dd_not_fired(self) -> None:
        from qp.monitoring.kill_switch import PortfolioDrawdownTrigger

        trigger = PortfolioDrawdownTrigger()
        result = trigger.evaluate(
            {
                "monthly_return": -0.05,
                "rolling_60d_drawdown": 0.10,
            }
        )
        assert result["fired"] is False

    def test_portfolio_dd_fired_monthly(self) -> None:
        from qp.monitoring.kill_switch import PortfolioDrawdownTrigger

        trigger = PortfolioDrawdownTrigger(monthly_limit=0.15)
        result = trigger.evaluate(
            {
                "monthly_return": -0.18,
                "rolling_60d_drawdown": 0.05,
            }
        )
        assert result["fired"] is True

    def test_psi_trigger_not_fired(self) -> None:
        from qp.monitoring.kill_switch import PSITrigger

        trigger = PSITrigger(threshold=0.25)
        result = trigger.evaluate({"psi": 0.10})
        assert result["fired"] is False

    def test_psi_trigger_fired(self) -> None:
        from qp.monitoring.kill_switch import PSITrigger

        trigger = PSITrigger(threshold=0.25)
        result = trigger.evaluate({"psi": 0.30})
        assert result["fired"] is True

    def test_kill_switch_aggregate(self) -> None:
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            KillSwitch,
            PortfolioDrawdownTrigger,
        )

        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger(historical_max_dd=0.15))
        ks.add_trigger(PortfolioDrawdownTrigger())

        result = ks.check(
            current_drawdown=0.10,
            monthly_return=-0.03,
        )
        assert result.triggered is False
        assert result.recommendation == "OK"

    def test_kill_switch_triggered(self) -> None:
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            KillSwitch,
        )

        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger(historical_max_dd=0.15, ratio=1.5))

        result = ks.check(current_drawdown=0.30)
        assert result.triggered is True
        assert result.recommendation == "PAUSE"


class TestMarketRegime:
    """Test market regime classification."""

    def test_construct(self) -> None:
        from qp.monitoring.regime import MarketRegimeEngine

        engine = MarketRegimeEngine()
        assert engine is not None

    def test_classify_insufficient_data(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine, Regime

        engine = MarketRegimeEngine(min_days=60)
        prices = pl.DataFrame({"close": [100.0, 101.0, 102.0]})
        result = engine.classify(prices)
        assert result.regime == Regime.UNKNOWN

    def test_classify_normal(self) -> None:
        # Generate 200 days of random walk
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0, 1, 200))
        closes = np.maximum(closes, 1.0)

        prices = pl.DataFrame(
            {
                "close": closes,
                "high": closes + np.abs(np.random.normal(0, 0.5, 200)),
                "low": closes - np.abs(np.random.normal(0, 0.5, 200)),
            }
        )

        engine = MarketRegimeEngine()
        result = engine.classify(prices)
        assert result.regime.value != ""  # Some regime assigned
        assert result.confidence > 0

    def test_regime_result_properties(self) -> None:
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0.05, 1, 200))
        closes = np.maximum(closes, 1.0)

        prices = pl.DataFrame(
            {
                "close": closes,
                "high": closes + np.abs(np.random.normal(0, 0.5, 200)),
                "low": closes - np.abs(np.random.normal(0, 0.5, 200)),
            }
        )

        engine = MarketRegimeEngine()
        result = engine.classify(prices)
        assert isinstance(result.is_trending, bool)
        assert isinstance(result.is_high_vol, bool)
