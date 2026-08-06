"""Tests for Monitoring Layer — drift, decay, regime, kill switch."""

from pathlib import Path

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
        ks_stat, _ks_pval = DriftMonitor.compute_ks(a, b)
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
            KillSwitchLevel,
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
        assert result.level == KillSwitchLevel.NORMAL
        assert result.recommendation == "NORMAL"

    def test_kill_switch_triggered(self) -> None:
        from qp.monitoring.kill_switch import (
            DrawdownTrigger,
            KillSwitch,
            KillSwitchLevel,
        )

        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger(historical_max_dd=0.15, ratio=1.5))

        result = ks.check(current_drawdown=0.30)
        assert result.triggered is True
        assert result.level == KillSwitchLevel.HALT_BUY
        assert result.recommendation == "HALT_BUY"


class TestP0SafetyTriggers:
    """Test P0 safety triggers added per docs/11_12.md."""

    # ------------------------------------------------------------------
    # KillSwitchLevel enum
    # ------------------------------------------------------------------

    def test_kill_switch_level_values(self) -> None:
        from qp.monitoring.kill_switch import KillSwitchLevel

        assert KillSwitchLevel.NORMAL == "NORMAL"
        assert KillSwitchLevel.WARNING == "WARNING"
        assert KillSwitchLevel.HALT_BUY == "HALT_BUY"
        assert KillSwitchLevel.FULL_STOP == "FULL_STOP"
        assert len(list(KillSwitchLevel)) == 4

    def test_kill_switch_level_ranking(self) -> None:
        from qp.monitoring.kill_switch import KillSwitch, KillSwitchLevel

        ks = KillSwitch()
        assert ks._level_rank(KillSwitchLevel.NORMAL) == 0
        assert ks._level_rank(KillSwitchLevel.WARNING) == 1
        assert ks._level_rank(KillSwitchLevel.HALT_BUY) == 2
        assert ks._level_rank(KillSwitchLevel.FULL_STOP) == 3
        # Escalation: higher rank = more severe
        assert ks._level_rank(KillSwitchLevel.FULL_STOP) > ks._level_rank(KillSwitchLevel.HALT_BUY)
        assert ks._level_rank(KillSwitchLevel.HALT_BUY) > ks._level_rank(KillSwitchLevel.WARNING)

    # ------------------------------------------------------------------
    # WeeklyDrawdownTrigger
    # ------------------------------------------------------------------

    def test_weekly_drawdown_not_fired(self) -> None:
        from qp.monitoring.kill_switch import KillSwitchLevel, WeeklyDrawdownTrigger

        trigger = WeeklyDrawdownTrigger(weekly_limit=0.05)
        result = trigger.evaluate({"weekly_drawdown": 0.03})
        assert result["fired"] is False
        assert result["kill_level"] == KillSwitchLevel.NORMAL
        assert result["weekly_drawdown"] == 0.03

    def test_weekly_drawdown_fired(self) -> None:
        from qp.monitoring.kill_switch import KillSwitchLevel, WeeklyDrawdownTrigger

        trigger = WeeklyDrawdownTrigger(weekly_limit=0.05)
        result = trigger.evaluate({"weekly_drawdown": 0.06})
        assert result["fired"] is True
        assert result["kill_level"] == KillSwitchLevel.HALT_BUY
        assert "Weekly drawdown" in result["message"]

    def test_weekly_drawdown_exact_threshold(self) -> None:
        from qp.monitoring.kill_switch import WeeklyDrawdownTrigger

        trigger = WeeklyDrawdownTrigger(weekly_limit=0.05)
        result = trigger.evaluate({"weekly_drawdown": 0.05})
        # > threshold (strict), not >= → 0.05 is NOT fired
        assert result["fired"] is False

    # ------------------------------------------------------------------
    # ConsecutiveLossTrigger
    # ------------------------------------------------------------------

    def test_consecutive_loss_not_fired(self) -> None:
        from qp.monitoring.kill_switch import ConsecutiveLossTrigger, KillSwitchLevel

        trigger = ConsecutiveLossTrigger(consecutive_days=5)
        result = trigger.evaluate({"consecutive_loss_days": 3})
        assert result["fired"] is False
        assert result["kill_level"] == KillSwitchLevel.NORMAL

    def test_consecutive_loss_fired(self) -> None:
        from qp.monitoring.kill_switch import ConsecutiveLossTrigger, KillSwitchLevel

        trigger = ConsecutiveLossTrigger(consecutive_days=5)
        result = trigger.evaluate({"consecutive_loss_days": 5})
        assert result["fired"] is True
        assert result["kill_level"] == KillSwitchLevel.WARNING
        assert "manual review" in result["message"].lower()

    def test_consecutive_loss_exceeds_threshold(self) -> None:
        from qp.monitoring.kill_switch import ConsecutiveLossTrigger, KillSwitchLevel

        trigger = ConsecutiveLossTrigger(consecutive_days=5)
        result = trigger.evaluate({"consecutive_loss_days": 7})
        assert result["fired"] is True
        assert result["kill_level"] == KillSwitchLevel.WARNING

    def test_consecutive_loss_zero(self) -> None:
        from qp.monitoring.kill_switch import ConsecutiveLossTrigger

        trigger = ConsecutiveLossTrigger(consecutive_days=5)
        result = trigger.evaluate({"consecutive_loss_days": 0})
        assert result["fired"] is False

    # ------------------------------------------------------------------
    # AbnormalTurnoverTrigger
    # ------------------------------------------------------------------

    def test_abnormal_turnover_not_fired(self) -> None:
        from qp.monitoring.kill_switch import AbnormalTurnoverTrigger, KillSwitchLevel

        trigger = AbnormalTurnoverTrigger(turnover_ratio=0.80)
        result = trigger.evaluate({"daily_trade_count": 5, "total_holdings": 20})
        assert result["fired"] is False
        assert result["kill_level"] == KillSwitchLevel.NORMAL

    def test_abnormal_turnover_fired(self) -> None:
        from qp.monitoring.kill_switch import AbnormalTurnoverTrigger, KillSwitchLevel

        trigger = AbnormalTurnoverTrigger(turnover_ratio=0.80)
        result = trigger.evaluate({"daily_trade_count": 17, "total_holdings": 20})
        assert result["fired"] is True
        assert result["kill_level"] == KillSwitchLevel.FULL_STOP
        assert "FULL_STOP" in result["message"]

    def test_abnormal_turnover_exact_threshold(self) -> None:
        from qp.monitoring.kill_switch import AbnormalTurnoverTrigger

        trigger = AbnormalTurnoverTrigger(turnover_ratio=0.80)
        # 16/20 = 0.80, strict > → NOT fired
        result = trigger.evaluate({"daily_trade_count": 16, "total_holdings": 20})
        assert result["fired"] is False

    def test_abnormal_turnover_zero_holdings(self) -> None:
        from qp.monitoring.kill_switch import AbnormalTurnoverTrigger, KillSwitchLevel

        trigger = AbnormalTurnoverTrigger(turnover_ratio=0.80)
        # 0 holdings → ratio guarded to 0.0, should not fire or crash
        result = trigger.evaluate({"daily_trade_count": 5, "total_holdings": 0})
        assert result["fired"] is False
        assert result["kill_level"] == KillSwitchLevel.NORMAL

    # ------------------------------------------------------------------
    # KillSwitchLevel escalation in aggregated KillSwitch
    # ------------------------------------------------------------------

    def test_kill_switch_full_stop_overrides_halt_buy(self) -> None:
        from qp.monitoring.kill_switch import (
            AbnormalTurnoverTrigger,
            KillSwitch,
            KillSwitchLevel,
            WeeklyDrawdownTrigger,
        )

        ks = KillSwitch()
        ks.add_trigger(WeeklyDrawdownTrigger(weekly_limit=0.05))
        ks.add_trigger(AbnormalTurnoverTrigger(turnover_ratio=0.80))

        result = ks.check(
            weekly_drawdown=0.06,  # HALT_BUY
            daily_trade_count=17,  # FULL_STOP
            total_holdings=20,
        )
        assert result.triggered is True
        assert result.level == KillSwitchLevel.FULL_STOP  # FULL_STOP wins
        assert len(result.triggers) == 2

    def test_kill_switch_warning_with_consecutive_loss(self) -> None:
        from qp.monitoring.kill_switch import (
            ConsecutiveLossTrigger,
            KillSwitch,
            KillSwitchLevel,
        )

        ks = KillSwitch()
        ks.add_trigger(ConsecutiveLossTrigger(consecutive_days=5))

        result = ks.check(consecutive_loss_days=5)
        assert result.triggered is True
        assert result.level == KillSwitchLevel.WARNING
        assert result.recommendation == "WARNING"

    def test_kill_switch_all_p0_triggers_integration(self) -> None:
        from qp.monitoring.kill_switch import (
            AbnormalTurnoverTrigger,
            ConsecutiveLossTrigger,
            KillSwitch,
            KillSwitchLevel,
            WeeklyDrawdownTrigger,
        )

        ks = KillSwitch()
        ks.add_trigger(WeeklyDrawdownTrigger(weekly_limit=0.05))
        ks.add_trigger(ConsecutiveLossTrigger(consecutive_days=5))
        ks.add_trigger(AbnormalTurnoverTrigger(turnover_ratio=0.80))

        # All clear
        result = ks.check(
            weekly_drawdown=0.02,
            consecutive_loss_days=2,
            daily_trade_count=3,
            total_holdings=20,
        )
        assert result.triggered is False
        assert result.level == KillSwitchLevel.NORMAL


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
        assert isinstance(result.is_crisis, bool)

    def test_regime_liquidity_crunch(self) -> None:
        """LIQUIDITY_CRUNCH should trigger when limit-up/down ratio is extreme."""
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine, Regime

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
        # Mass limit-down: ratio near 0
        result = engine.classify(prices, limit_up_down_ratio=0.05)
        assert result.regime == Regime.LIQUIDITY_CRUNCH
        assert result.is_crisis is True

    def test_regime_liquidity_crunch_mass_limit_up(self) -> None:
        """Mass limit-up is also a liquidity event."""
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine, Regime

        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0, 1, 200))
        closes = np.maximum(closes, 1.0)
        prices = pl.DataFrame({"close": closes})

        engine = MarketRegimeEngine()
        result = engine.classify(prices, limit_up_down_ratio=0.92)
        assert result.regime == Regime.LIQUIDITY_CRUNCH

    def test_regime_style_reversal(self) -> None:
        """STYLE_REVERSAL should trigger when sector rotation is rapid."""
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine, Regime

        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0, 1, 200))
        closes = np.maximum(closes, 1.0)
        prices = pl.DataFrame({"close": closes})

        engine = MarketRegimeEngine()
        result = engine.classify(prices, sector_rotation_speed=0.65)
        assert result.regime == Regime.STYLE_REVERSAL
        assert result.is_crisis is True

    def test_regime_classify_with_new_params_defaults(self) -> None:
        """classify() should work without the new optional params."""
        import numpy as np
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0, 1, 200))
        closes = np.maximum(closes, 1.0)
        prices = pl.DataFrame({"close": closes})

        engine = MarketRegimeEngine()
        result = engine.classify(prices)
        assert result.limit_up_down_ratio == 0.5
        assert result.sector_rotation_speed == 0.0


class TestRegimeStaticHelpers:
    """Test compute_limit_up_down_ratio and compute_sector_rotation_speed."""

    def test_limit_up_down_ratio_balanced(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        # Mixed returns, no extremes
        df = pl.DataFrame({"return": [0.01, -0.01, 0.02, -0.02, 0.03, 0.0]})
        ratio = MarketRegimeEngine.compute_limit_up_down_ratio(df)
        assert 0.0 <= ratio <= 1.0
        assert ratio == 0.5  # No limit-up or limit-down hits

    def test_limit_up_down_ratio_all_limit_down(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        df = pl.DataFrame({"return": [-0.10, -0.099, -0.10, -0.098, -0.10]})
        ratio = MarketRegimeEngine.compute_limit_up_down_ratio(df)
        assert ratio == 0.0  # All limit-down, no limit-up

    def test_limit_up_down_ratio_all_limit_up(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        df = pl.DataFrame({"return": [0.10, 0.099, 0.10, 0.098, 0.10]})
        ratio = MarketRegimeEngine.compute_limit_up_down_ratio(df)
        assert ratio == 1.0  # All limit-up, no limit-down

    def test_limit_up_down_ratio_empty(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        df = pl.DataFrame({"return": pl.Series([], dtype=pl.Float64)})
        ratio = MarketRegimeEngine.compute_limit_up_down_ratio(df)
        assert ratio == 0.5  # Default for insufficient data

    def test_limit_up_down_ratio_pct_change_col(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        # Falls back to "pct_change" column
        # 0.10 >= 0.098 (up x3), -0.098 <= -0.098 (down x2), 0.05 neither
        df = pl.DataFrame({"pct_change": [0.10, -0.098, 0.05, 0.10, -0.098, 0.10]})
        ratio = MarketRegimeEngine.compute_limit_up_down_ratio(df)
        assert ratio == 0.6  # 3 up, 2 down = 3/5

    def test_sector_rotation_speed_basic(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        # Create 30 days of sector returns with 3 sectors
        dates = [f"2026-07-{d:02d}" for d in range(1, 31)] * 3
        sectors = (["银行"] * 30) + (["科技"] * 30) + (["消费"] * 30)
        import numpy as np

        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.02, 90))

        df = pl.DataFrame(
            {
                "trade_date": dates,
                "sector": sectors,
                "return": returns,
            }
        )
        speed = MarketRegimeEngine.compute_sector_rotation_speed(df)
        assert speed > 0.0

    def test_sector_rotation_speed_empty(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        df = pl.DataFrame({"trade_date": [], "return": []})
        speed = MarketRegimeEngine.compute_sector_rotation_speed(df)
        assert speed == 0.0

    def test_sector_rotation_speed_insufficient_data(self) -> None:
        import polars as pl

        from qp.monitoring.regime import MarketRegimeEngine

        # Only 3 days of data (below min)
        df = pl.DataFrame(
            {
                "trade_date": ["2026-07-01", "2026-07-02", "2026-07-03"],
                "return": [0.01, -0.01, 0.02],
            }
        )
        speed = MarketRegimeEngine.compute_sector_rotation_speed(df)
        assert speed == 0.0

    def test_kill_switch_pipeline_handles_crisis_regime(self) -> None:
        """KillSwitchPipeline should stay OK on LIQUIDITY_CRUNCH alone (#4 fix).

        Regime is context, not a trigger — only KillSwitch triggers cause action.
        """
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
            MonitorReport,
        )
        from qp.monitoring.regime import Regime, RegimeResult

        class _TestKSP(KillSwitchPipeline):
            @property
            def name(self) -> str:
                return "test"

        pipeline = _TestKSP()

        # Crisis regime alone should NOT pause trading
        crisis_regime = RegimeResult(regime=Regime.LIQUIDITY_CRUNCH, confidence=0.85)
        report = MonitorReport(regime=crisis_regime)
        action = pipeline._determine_action(report)
        assert action == MonitorAction.OK  # Regime alone does not trigger action

    def test_kill_switch_pipeline_handles_style_reversal(self) -> None:
        """KillSwitchPipeline should stay OK on STYLE_REVERSAL alone (#4 fix).

        Regime is context, not a trigger.
        """
        from qp.monitoring.kill_switch_pipeline import (
            KillSwitchPipeline,
            MonitorAction,
            MonitorReport,
        )
        from qp.monitoring.regime import Regime, RegimeResult

        class _TestKSP(KillSwitchPipeline):
            @property
            def name(self) -> str:
                return "test"

        pipeline = _TestKSP()

        reversal_regime = RegimeResult(regime=Regime.STYLE_REVERSAL, confidence=0.70)
        report = MonitorReport(regime=reversal_regime)
        action = pipeline._determine_action(report)
        assert action == MonitorAction.OK  # Regime alone does not trigger action


class TestSystemHealthLogger:
    """Test the system_health_log Parquet-based health logger."""

    def test_construct(self) -> None:
        from qp.monitoring.health_logger import SystemHealthLogger

        logger = SystemHealthLogger()
        assert logger is not None

    def test_log_and_retrieve(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            logger.log(
                date="2026-07-25",
                psi_value=0.12,
                rolling_ic=0.025,
                regime="TREND_UP",
                kill_switch_level="NORMAL",
                kill_switch_triggered=False,
                model_decay_stage="HEALTHY",
                strategy_health_score=92.0,
                action="OK",
                n_alerts=0,
                alerts_summary="",
            )

            latest = logger.get_latest()
            assert latest is not None
            assert latest.date == "2026-07-25"
            assert latest.psi_value == 0.12
            assert latest.regime == "TREND_UP"

    def test_log_multiple_days_and_query(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            for day in range(1, 6):
                logger.log(
                    date=f"2026-07-0{day}",
                    psi_value=0.10 + day * 0.01,
                    regime="TREND_UP",
                    action="OK",
                )

            history = logger.load_history(days=10)
            assert len(history) == 5
            assert history["date"].to_list() == [
                "2026-07-05",
                "2026-07-04",
                "2026-07-03",
                "2026-07-02",
                "2026-07-01",
            ]

    def test_dedup_same_date(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            logger.log(date="2026-07-25", psi_value=0.10, action="OK")
            logger.log(date="2026-07-25", psi_value=0.30, action="WATCH")  # Overwrite

            history = logger.load_history(days=10)
            assert len(history) == 1
            assert history["psi_value"].item() == 0.30
            assert history["action"].item() == "WATCH"

    def test_load_history_empty(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            history = logger.load_history(days=90)
            assert history.is_empty()

    def test_get_latest_empty(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            assert logger.get_latest() is None

    def test_query_regime_changes(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            logger.log(date="2026-07-01", regime="TREND_UP", action="OK")
            logger.log(date="2026-07-02", regime="TREND_UP", action="OK")
            logger.log(date="2026-07-03", regime="LIQUIDITY_CRUNCH", action="PAUSE_BUY")

            changes = logger.query_regime_changes()
            # Regime changed from TREND_UP to LIQUIDITY_CRUNCH on 07-03
            assert changes.height >= 1

    def test_stats(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            logger.log(
                date="2026-07-25",
                regime="TREND_UP",
                kill_switch_triggered=False,
                action="OK",
            )

            stats = logger.stats()
            assert stats["n_days"] == 1
            assert "date_range" in stats

    def test_log_from_report(self) -> None:
        import tempfile

        from qp.monitoring.health_logger import SystemHealthLogger
        from qp.monitoring.kill_switch_pipeline import MonitorReport
        from qp.monitoring.regime import Regime, RegimeResult

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SystemHealthLogger(base_dir=tmpdir)
            regime = RegimeResult(regime=Regime.TREND_UP, confidence=0.80)
            report = MonitorReport(
                run_id="test-001",
                regime=regime,
                action="OK",
                psi_value=0.05,
                alerts=["All clear"],
            )

            record = logger.log_from_report(report, date_str="2026-07-25")
            assert record is not None
            assert record.regime == "TREND_UP"
            assert record.action == "OK"

    def test_health_record_to_dict(self) -> None:
        from qp.monitoring.health_logger import HealthRecord

        record = HealthRecord(
            date="2026-07-25",
            psi_value=0.10,
            regime="TREND_UP",
            kill_switch_triggered=True,
            kill_switch_level="WARNING",
        )
        d = record.to_dict()
        assert d["date"] == "2026-07-25"
        assert d["psi_value"] == 0.10
        assert d["kill_switch_triggered"] is True
        assert d["kill_switch_level"] == "WARNING"


class TestDecisionAuditLogger:
    """Test the trade decision audit logger (T2 per docs/11_12.md)."""

    def test_construct(self) -> None:
        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        logger = DecisionAuditLogger()
        assert logger is not None

    def test_record_signal(self) -> None:
        import tempfile

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            record = logger.record_signal(
                date="2026-07-25",
                symbol="000001.SZ",
                action="BUY",
                score=0.85,
                rank=5,
                reason_tags=["RANK_TOP20"],
                strategy_name="alpha_multi_factor_v2",
            )
            assert record.symbol == "000001.SZ"
            assert record.action == "BUY"
            assert record.score == 0.85
            assert "RANK_TOP20" in record.reason_tags

    def test_record_human_override(self) -> None:
        import tempfile

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            record = logger.record_human_override(
                date="2026-07-25",
                symbol="000002.SZ",
                original_action="BUY",
                override_action="HOLD",
                reason="盘后发布减持公告",
                strategy_name="alpha_multi_factor_v2",
            )
            assert record.human_override is True
            assert "MANUAL_OVERRIDE" in record.reason_tags
            assert "BUY → HOLD" in record.override_reason

    def test_record_portfolio_snapshot(self) -> None:
        import tempfile

        import polars as pl

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            signals = pl.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "action": ["BUY", "SELL", "HOLD"],
                    "score": [0.85, -0.20, 0.10],
                }
            )
            n = logger.record_portfolio_snapshot(
                signals, date_str="2026-07-25", strategy_name="test"
            )
            assert n == 3

    def test_query_by_date(self) -> None:
        import tempfile

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            logger.record_signal(date="2026-07-25", symbol="A", action="BUY", score=0.9)
            logger.record_signal(date="2026-07-26", symbol="B", action="SELL", score=0.3)

            df = logger.query_by_date("2026-07-25")
            assert len(df) == 1
            assert df["symbol"].item() == "A"

    def test_query_human_overrides(self) -> None:
        import tempfile

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            logger.record_signal(date="2026-07-25", symbol="A", action="BUY", score=0.9)
            logger.record_human_override(
                date="2026-07-25",
                symbol="B",
                original_action="BUY",
                override_action="HOLD",
                reason="test",
            )
            df = logger.query_human_overrides()
            assert len(df) == 1

    def test_reason_tag_enum(self) -> None:
        from qp.knowledge.decision_audit_logger import ReasonTag

        assert ReasonTag.STOP_LOSS == "STOP_LOSS"
        assert ReasonTag.RANK_DROP == "RANK_DROP"
        assert ReasonTag.RISK_EVENT == "RISK_EVENT"
        assert ReasonTag.MANUAL_OVERRIDE == "MANUAL_OVERRIDE"
        assert len(list(ReasonTag)) == 10

    def test_stats(self) -> None:
        import tempfile

        from qp.knowledge.decision_audit_logger import DecisionAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = DecisionAuditLogger(base_dir=tmpdir)
            logger.record_signal(date="2026-07-25", symbol="A", action="BUY", score=0.9)
            logger.record_signal(date="2026-07-25", symbol="B", action="SELL", score=0.3)
            stats = logger.stats()
            assert stats["n_decisions"] == 2


class TestFailureArchiveLogger:
    """Test the failure archive logger (T3 per docs/11_12.md)."""

    def test_construct(self) -> None:
        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        logger = FailureArchiveLogger()
        assert logger is not None

    def test_record_stop_loss(self) -> None:
        import tempfile

        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = FailureArchiveLogger(base_dir=tmpdir)
            record = logger.record_stop_loss(
                date="2026-07-25",
                symbol="000001.SZ",
                buy_date="2026-06-15",
                buy_price=15.80,
                sell_price=14.22,
                loss_pct=-0.10,
                feature_snapshot={"Momentum_1M": -0.03, "PE_TTM": 25.0},
                strategy_name="alpha_multi_factor_v2",
            )
            assert record.failure_type == "STOP_LOSS"
            assert record.symbol == "000001.SZ"
            assert record.loss_pct == -0.10
            assert record.feature_snapshot["Momentum_1M"] == -0.03

    def test_record_kill_switch(self) -> None:
        import tempfile

        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = FailureArchiveLogger(base_dir=tmpdir)
            record = logger.record_kill_switch(
                date="2026-07-25",
                kill_switch_level="FULL_STOP",
                market_regime="LIQUIDITY_CRUNCH",
                trigger_reason="Weekly DD 7% > 5% threshold",
            )
            assert record.failure_type == "KILL_SWITCH"
            assert record.kill_switch_level == "FULL_STOP"
            assert record.market_regime == "LIQUIDITY_CRUNCH"

    def test_record_black_swan(self) -> None:
        import tempfile

        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = FailureArchiveLogger(base_dir=tmpdir)
            record = logger.record_black_swan(
                date="2026-07-25",
                symbol="",
                strategy_name="alpha_multi_factor_v2",
                loss_pct=-0.25,
                feature_snapshot={"Volatility_60D": 0.08, "PE_TTM": 15.0},
                market_regime="LIQUIDITY_CRUNCH",
                trigger_reason="Mass limit-down cascade",
            )
            assert record.failure_type == "BLACK_SWAN"
            assert "BLACK_SWAN" in record.tags

    def test_query_by_type(self) -> None:
        import tempfile

        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = FailureArchiveLogger(base_dir=tmpdir)
            logger.record_stop_loss(
                date="2026-07-25",
                symbol="A",
                buy_date="2026-06-01",
                buy_price=10.0,
                sell_price=9.0,
                loss_pct=-0.10,
            )
            logger.record_kill_switch(
                date="2026-07-26",
                kill_switch_level="HALT_BUY",
                trigger_reason="test",
            )
            stop_losses = logger.query_by_type("STOP_LOSS")
            ks_events = logger.query_by_type("KILL_SWITCH")
            assert len(stop_losses) == 1
            assert len(ks_events) == 1

    def test_failure_type_enum(self) -> None:
        from qp.knowledge.failure_archive_logger import FailureType

        assert FailureType.STOP_LOSS == "STOP_LOSS"
        assert FailureType.KILL_SWITCH == "KILL_SWITCH"
        assert FailureType.BLACK_SWAN == "BLACK_SWAN"
        assert len(list(FailureType)) == 5

    def test_stats(self) -> None:
        import tempfile

        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = FailureArchiveLogger(base_dir=tmpdir)
            logger.record_stop_loss(
                date="2026-07-25",
                symbol="A",
                buy_date="2026-06-01",
                buy_price=10.0,
                sell_price=9.0,
                loss_pct=-0.10,
            )
            stats = logger.stats()
            assert stats["n_failures"] == 1


class TestRegimeNoteLogger:
    """Test the market regime notes logger (L12-3 per docs/11_12.md)."""

    def test_construct(self) -> None:
        from qp.knowledge.regime_notes import RegimeNoteLogger

        logger = RegimeNoteLogger()
        assert logger is not None

    def test_record_event(self) -> None:
        import tempfile

        from qp.knowledge.regime_notes import RegimeNoteLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RegimeNoteLogger(base_dir=tmpdir)
            entry = logger.record_event(
                title="2024.02 Micro-cap Crash",
                event_date="2024-02-05",
                regime="LIQUIDITY_CRUNCH",
                severity=5,
                strategy_name="alpha_multi_factor_v2",
                ic_during_event=-0.03,
                max_drawdown_pct=12.5,
                observations="Small caps collapsed, quality held.",
                tags=["liquidity-crisis"],
            )
            assert entry is not None
            assert "LIQUIDITY_CRUNCH" in entry.metadata.get("regime", "")

    def test_record_from_regime_result(self) -> None:
        import tempfile

        from qp.knowledge.regime_notes import RegimeNoteLogger
        from qp.monitoring.regime import Regime, RegimeResult

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RegimeNoteLogger(base_dir=tmpdir)
            regime_result = RegimeResult(
                regime=Regime.LIQUIDITY_CRUNCH,
                confidence=0.85,
                limit_up_down_ratio=0.05,
                annualized_vol=0.45,
            )
            entry = logger.record_from_regime_result(
                regime_result,
                title="Auto-recorded Crisis",
                strategy_name="test",
                ic_during_event=-0.05,
                max_drawdown_pct=15.0,
            )
            assert entry is not None

    def test_query_by_regime(self) -> None:
        import tempfile

        from qp.knowledge.regime_notes import RegimeNoteLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RegimeNoteLogger(base_dir=tmpdir)
            logger.record_event(
                title="Event A",
                event_date="2026-01-15",
                regime="LIQUIDITY_CRUNCH",
            )
            logger.record_event(
                title="Event B",
                event_date="2026-03-20",
                regime="STYLE_REVERSAL",
            )
            results = logger.query_by_regime("LIQUIDITY_CRUNCH")
            assert len(results) >= 1

    def test_get_ground_truth_labels(self) -> None:
        import tempfile

        from qp.knowledge.regime_notes import RegimeNoteLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RegimeNoteLogger(base_dir=tmpdir)
            logger.record_event(
                title="GT Event",
                event_date="2026-06-01",
                regime="LIQUIDITY_CRUNCH",
                regime_label="LIQUIDITY_CRUNCH",
                labeled_by="expert",
            )
            labels = logger.get_ground_truth_labels()
            assert len(labels) >= 1
            assert labels[0]["regime"] == "LIQUIDITY_CRUNCH"


class TestRetrainSignal:
    """Test retrain signal generation and logging (P3 L11-1.5, L11-1.7)."""

    def test_retrain_action_enum(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction

        assert RetrainAction.NONE == "NONE"
        assert RetrainAction.SCHEDULE_RETRAIN == "SCHEDULE_RETRAIN"
        assert RetrainAction.REDUCE_WEIGHT == "REDUCE_WEIGHT"
        assert len(list(RetrainAction)) == 6

    def test_retrain_trigger_enum(self) -> None:
        from qp.monitoring.retrain_signal import RetrainTrigger

        assert RetrainTrigger.PSI_DRIFT == "PSI_DRIFT"
        assert RetrainTrigger.IC_DECAY == "IC_DECAY"
        assert len(list(RetrainTrigger)) == 5

    def test_evaluate_psi_drift_trigger(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(psi_value=0.30, rolling_ic=0.03)
        assert signal.action == RetrainAction.SCHEDULE_RETRAIN
        assert signal.trigger == "PSI_DRIFT"
        assert signal.is_actionable() is True

    def test_evaluate_ic_decay_reduce_weight(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(
            rolling_ic=0.008,
            training_ic=0.035,
            psi_value=0.05,
        )
        assert signal.action == RetrainAction.REDUCE_WEIGHT
        assert signal.trigger == "IC_DECAY"

    def test_evaluate_model_stale(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(model_decay_stage="STALE")
        assert signal.action == RetrainAction.RETIRE

    def test_evaluate_none(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(psi_value=0.05, rolling_ic=0.03, training_ic=0.035)
        assert signal.action == RetrainAction.NONE
        assert signal.is_actionable() is False

    def test_evaluate_regime_shift(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, evaluate_retrain_need

        signal = evaluate_retrain_need(
            psi_value=0.05,
            rolling_ic=0.03,
            training_ic=0.035,
            current_regime="LIQUIDITY_CRUNCH",
        )
        assert signal.action == RetrainAction.MONITOR
        assert signal.trigger == "REGIME_SHIFT"

    def test_signal_logger(self) -> None:
        import tempfile

        from qp.monitoring.retrain_signal import (
            RetrainAction,
            RetrainSignal,
            RetrainSignalLogger,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RetrainSignalLogger(base_dir=tmpdir)
            signal = RetrainSignal(
                date="2026-07-25",
                strategy_name="test",
                trigger="PSI_DRIFT",
                action=RetrainAction.SCHEDULE_RETRAIN,
                psi_value=0.30,
                message="Test retrain signal",
            )
            logger.log(signal)

            history = logger.load_history(days=30)
            assert len(history) == 1
            assert history["action"].item() == "SCHEDULE_RETRAIN"

    def test_signal_to_dict(self) -> None:
        from qp.monitoring.retrain_signal import RetrainAction, RetrainSignal

        signal = RetrainSignal(
            strategy_name="test",
            trigger="PSI_DRIFT",
            action=RetrainAction.SCHEDULE_RETRAIN,
            psi_value=0.32,
        )
        d = signal.to_dict()
        assert d["strategy_name"] == "test"
        assert d["psi_value"] == 0.32


class TestVersionTree:
    """Test strategy version tree (P3 L12-2.3)."""

    def test_construct(self) -> None:
        from qp.knowledge.version_tree import StrategyVersionTree

        tree = StrategyVersionTree()
        assert tree is not None

    def test_register_and_get(self) -> None:
        import tempfile

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            node = tree.register_version(
                strategy_name="test_strategy",
                version="v1.0",
                changelog="Initial version",
                ic_mean=0.025,
            )
            assert node.version == "v1.0"
            retrieved = tree.get("test_strategy", "v1.0")
            assert retrieved is not None
            assert retrieved.ic_mean == 0.025

    def test_lineage(self) -> None:
        import tempfile

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            tree.register_version("test_strategy", "v1.0", changelog="Root")
            tree.register_version(
                "test_strategy",
                "v2.0",
                parent_version="v1.0",
                changelog="Added reversal factors",
            )
            tree.register_version(
                "test_strategy",
                "v2.1",
                parent_version="v2.0",
                changelog="Fixed sign bug",
            )
            lineage = tree.get_lineage("test_strategy")
            assert len(lineage) == 3
            assert lineage[0].version == "v1.0"
            assert lineage[2].version == "v2.1"

    def test_auto_retire_parent(self) -> None:
        import tempfile

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            tree.register_version("s", "v1.0")
            tree.register_version("s", "v2.0", parent_version="v1.0")
            v1 = tree.get("s", "v1.0")
            assert v1 is not None
            assert v1.status == "retired"

    def test_diff(self) -> None:
        import tempfile

        import pytest

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            tree.register_version("s", "v1.0", ic_mean=0.020, sharpe=0.30)
            tree.register_version(
                "s",
                "v2.0",
                parent_version="v1.0",
                ic_mean=0.028,
                sharpe=0.45,
            )
            diff = tree.diff("s", "v1.0", "v2.0")
            assert diff["ic_delta"] == pytest.approx(0.008)
            assert diff["sharpe_delta"] == pytest.approx(0.15)

    def test_list_strategies(self) -> None:
        import tempfile

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            tree.register_version("alpha", "v1.0")
            tree.register_version("momentum", "v1.0")
            strategies = tree.list_strategies()
            assert "alpha" in strategies
            assert "momentum" in strategies

    def test_duplicate_version_raises(self) -> None:
        import tempfile

        import pytest

        from qp.knowledge.version_tree import StrategyVersionTree

        with tempfile.TemporaryDirectory() as tmpdir:
            tree = StrategyVersionTree(filepath=f"{tmpdir}/version_tree.json")
            tree.register_version("s", "v1.0")
            with pytest.raises(ValueError, match="already exists"):
                tree.register_version("s", "v1.0")

    def test_empty_lineage(self) -> None:
        from qp.knowledge.version_tree import StrategyVersionTree

        tree = StrategyVersionTree()
        lineage = tree.get_lineage("nonexistent")
        assert lineage == []


class TestClusterAnalyzer:
    """Test failure cluster analyzer and feedback loop (P3 L12-1.6, C2-C4)."""

    def test_construct(self) -> None:
        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer

        analyzer = FailureClusterAnalyzer()
        assert analyzer is not None

    def test_generate_rules_empty(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer

        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            rules = analyzer.generate_blacklist_rules(min_records=5)
            assert rules == []

    def test_suggest_features_empty(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer

        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            suggestions = analyzer.suggest_features(min_records=5)
            assert suggestions == []

    def test_suggest_strategy_empty(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer

        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            adjustments = analyzer.suggest_strategy_adjustments(days=30)
            assert adjustments == []

    def test_blacklist_rule_dataclass(self) -> None:
        from qp.knowledge.cluster_analyzer import BlacklistRule

        rule = BlacklistRule(
            condition="PE_TTM > 100",
            reason="Test reason",
            source_failures=15,
            confidence=0.85,
        )
        d = rule.to_dict()
        assert d["condition"] == "PE_TTM > 100"
        assert d["confidence"] == 0.85

    def test_feature_suggestion_dataclass(self) -> None:
        from qp.knowledge.cluster_analyzer import FeatureSuggestion

        s = FeatureSuggestion(
            feature_name="Test_Factor",
            derivation="A * B",
            rationale="Test",
            priority=4,
        )
        assert s.feature_name == "Test_Factor"

    def test_strategy_adjustment_dataclass(self) -> None:
        from qp.knowledge.cluster_analyzer import StrategyAdjustment

        a = StrategyAdjustment(
            parameter="max_positions",
            suggestion="20 → 15",
            reason="Test",
        )
        assert a.parameter == "max_positions"

    def test_generate_rules_from_real_data(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer
        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            # Seed some failure data
            archive = FailureArchiveLogger(base_dir=tmpdir)
            for i in range(15):
                archive.record_stop_loss(
                    date="2026-07-25",
                    symbol=f"00000{i}.SZ",
                    buy_date="2026-06-01",
                    buy_price=10.0,
                    sell_price=9.0,
                    loss_pct=-0.10,
                    feature_snapshot={
                        "PE_TTM": 120.0 + i,
                        "Volatility_60D": 0.05,
                        "ROE": 0.01,
                    },
                )

            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            rules = analyzer.generate_blacklist_rules(min_records=5)
            assert len(rules) > 0  # Should find PE and Vol rules

    def test_analyze_full_feedback(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import FailureClusterAnalyzer
        from qp.knowledge.failure_archive_logger import FailureArchiveLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            archive = FailureArchiveLogger(base_dir=tmpdir)
            for i in range(12):
                archive.record_stop_loss(
                    date="2026-07-25",
                    symbol=f"00000{i}.SZ",
                    buy_date="2026-06-01",
                    buy_price=10.0,
                    sell_price=9.0,
                    loss_pct=-0.10,
                    feature_snapshot={"PE_TTM": 150.0, "Volatility_60D": 0.06},
                    market_regime="LIQUIDITY_CRUNCH" if i < 5 else "TREND_UP",
                )

            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            result = analyzer.analyze(days=30)
            assert "rules" in result
            assert "feature_suggestions" in result
            assert "strategy_adjustments" in result
            assert "feed_consumers" in result

    def test_save_and_load_rules(self) -> None:
        import tempfile

        from qp.knowledge.cluster_analyzer import BlacklistRule, FailureClusterAnalyzer

        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FailureClusterAnalyzer(base_dir=tmpdir)
            rules = [
                BlacklistRule(
                    condition="PE_TTM > 100",
                    reason="Test",
                    source_failures=10,
                    confidence=0.9,
                ),
            ]
            analyzer.save_rules(rules)
            loaded = analyzer.load_rules()
            assert len(loaded) == 1
            assert loaded[0].condition == "PE_TTM > 100"


# ==================================================================
# StrategyHealthLogger tests (P1.1)
# ==================================================================


class TestStrategyHealthLogger:
    """Test StrategyHealthLogger persistence and health computation."""

    def test_record_and_check_basic(self, tmp_path) -> None:

        from qp.monitoring.strategy_health_logger import (
            MONITORING_DIR,
            StrategyHealthLogger,
        )

        original_dir = str(MONITORING_DIR)
        try:
            # Redirect to temp dir
            import qp.monitoring.strategy_health_logger as mod

            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            logger = StrategyHealthLogger(window_days=60)
            health = logger.record_and_check(
                strategy_id="test_strategy_v1.0",
                date="2026-07-30",
                n_signals=8,
                n_buys=8,
                n_sells=0,
            )

            assert health.strategy_id == "test_strategy_v1.0"
            assert 0 <= health.health_score <= 100
            assert health.avg_daily_signals == 8.0
            assert health.days_since_last_signal == 0
        finally:
            # Restore
            import qp.monitoring.strategy_health_logger as mod

            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_persistence_across_runs(self, tmp_path) -> None:
        from pathlib import Path

        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            # First run
            logger1 = mod.StrategyHealthLogger()
            logger1.record_and_check(
                strategy_id="persist_test",
                date="2026-07-29",
                n_signals=10,
                n_buys=10,
            )

            # Second run — should load history
            logger2 = mod.StrategyHealthLogger()
            health2 = logger2.record_and_check(
                strategy_id="persist_test",
                date="2026-07-30",
                n_signals=5,
                n_buys=5,
            )

            assert health2.avg_daily_signals == 7.5  # (10+5)/2
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_load_all_latest(self, tmp_path) -> None:
        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            logger = mod.StrategyHealthLogger()
            for sid in ["strat_a", "strat_b", "strat_c"]:
                logger.record_and_check(
                    strategy_id=sid,
                    date="2026-07-30",
                    n_signals=5,
                    n_buys=5,
                )

            latest = logger.load_all_latest()
            assert len(latest) == 3
            assert "strat_a" in latest
            assert "strat_b" in latest
            assert latest["strat_a"].health_score >= 0
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_health_to_dict(self) -> None:
        from qp.monitoring.strategy_health_logger import StrategyHealthLogger
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="test",
            health_level=HealthLevel.HEALTHY,
            health_score=95.0,
            alerts=["low signal count"],
            summary="test summary",
        )
        d = StrategyHealthLogger.health_to_dict(health)
        assert d["health_level"] == "healthy"
        assert d["health_score"] == 95.0
        assert len(d["alerts"]) == 1
        assert d["summary"] == "test summary"

    def test_empty_history_returns_healthy(self, tmp_path) -> None:
        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            logger = mod.StrategyHealthLogger()
            health = logger.record_and_check(
                strategy_id="new_strategy",
                date="2026-07-30",
                n_signals=5,
                n_buys=5,
            )
            # First recording — should be healthy (no history to compare)
            assert health.health_level.value == "healthy"
            assert health.health_score == 100.0
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_load_latest_health_nonexistent(self) -> None:
        from qp.monitoring.strategy_health_logger import StrategyHealthLogger

        logger = StrategyHealthLogger()
        result = logger.load_latest_health("nonexistent_strategy")
        assert result is None


class TestStrategyHealthPipelineIntegration:
    """Integration tests simulating daily pipeline health recording (P1.1)."""

    def test_multi_day_accumulation(self, tmp_path) -> None:
        """Simulate 5 days of pipeline runs — health should evolve."""
        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            # Day 1-3: stable signals
            for day in range(1, 4):
                logger = mod.StrategyHealthLogger()
                h = logger.record_and_check(
                    strategy_id="test_integration",
                    date=f"2026-07-0{day}",
                    n_signals=10,
                    n_buys=10,
                )
                assert h.health_score >= 90, f"Day {day}: expected healthy"

            # Day 4: signal drop
            logger = mod.StrategyHealthLogger()
            h = logger.record_and_check(
                strategy_id="test_integration",
                date="2026-07-04",
                n_signals=2,
                n_buys=2,
            )
            # Should detect lower avg signals vs expected range (5-30)
            assert h.avg_daily_signals < 10

            # Day 5: zero signals — should trigger alert
            logger = mod.StrategyHealthLogger()
            h = logger.record_and_check(
                strategy_id="test_integration",
                date="2026-07-05",
                n_signals=0,
                n_buys=0,
            )
            assert h.health_score < 90  # Should drop from 100
            assert h.days_since_last_signal >= 1
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_health_saved_to_parquet(self, tmp_path) -> None:
        """Verify health records are persisted to parquet."""
        import polars as pl

        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            logger = mod.StrategyHealthLogger()
            logger.record_and_check(
                strategy_id="persist_check",
                date="2026-07-30",
                n_signals=8,
                n_buys=8,
            )

            # Verify file exists and has data
            assert mod.HEALTH_PARQUET.exists()
            df = pl.read_parquet(str(mod.HEALTH_PARQUET))
            assert df.height >= 1
            assert "strategy_id" in df.columns
            assert "health_score" in df.columns
            assert df.filter(pl.col("strategy_id") == "persist_check").height == 1
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_signals_saved_to_parquet(self, tmp_path) -> None:
        """Verify signal records are persisted for history loading."""
        import polars as pl

        import qp.monitoring.strategy_health_logger as mod

        original_dir = str(mod.MONITORING_DIR)
        try:
            mod.MONITORING_DIR = tmp_path
            mod.HEALTH_PARQUET = tmp_path / "strategy_health.parquet"

            logger = mod.StrategyHealthLogger()
            logger.record_and_check(
                strategy_id="sig_check",
                date="2026-07-30",
                n_signals=7,
                n_buys=5,
                n_sells=2,
            )

            sig_path = tmp_path / "strategy_signals.parquet"
            assert sig_path.exists()
            df = pl.read_parquet(str(sig_path))
            row = df.filter(pl.col("strategy_id") == "sig_check")
            assert row.height == 1
            assert row["n_signals"][0] == 7
            assert row["n_buys"][0] == 5
            assert row["n_sells"][0] == 2
        finally:
            mod.MONITORING_DIR = Path(original_dir)
            mod.HEALTH_PARQUET = Path(original_dir) / "strategy_health.parquet"

    def test_health_to_dict_includes_all_fields(self) -> None:
        """health_to_dict must include all required fields for DecisionPackage."""
        from qp.monitoring.strategy_health_logger import StrategyHealthLogger
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="full_test",
            health_level=HealthLevel.WARNING,
            health_score=55.5,
            avg_daily_signals=3.2,
            signal_consistency=0.8,
            weekly_turnover_pct=0.15,
            current_drawdown_pct=0.05,
            days_since_last_signal=2,
            alerts=["low signal count", "high turnover"],
            summary="test summary",
        )
        d = StrategyHealthLogger.health_to_dict(health)

        required = [
            "health_level",
            "health_score",
            "avg_daily_signals",
            "signal_consistency",
            "weekly_turnover_pct",
            "current_drawdown_pct",
            "days_since_last_signal",
            "alerts",
            "summary",
        ]
        for field in required:
            assert field in d, f"Missing field: {field}"
        assert len(d["alerts"]) == 2


class TestStrategyHealthReport:
    """Test StrategyHealthReport generation (P1.2)."""

    def test_from_healthy_strategy(self) -> None:
        from qp.monitoring.strategy_health_report import (
            HealthRecommendation,
            StrategyHealthReport,
        )
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="momentum_v1.0",
            health_level=HealthLevel.HEALTHY,
            health_score=92.0,
            avg_daily_signals=12.0,
            signal_consistency=0.9,
            alerts=[],
        )
        report = StrategyHealthReport.from_health(health)

        assert report.recommendation == HealthRecommendation.HEALTHY
        assert report.can_use_in_decision is True
        assert report.needs_human_review is False
        assert report.trend == "unknown"  # No history

    def test_from_critical_strategy(self) -> None:
        from qp.monitoring.strategy_health_report import (
            HealthRecommendation,
            StrategyHealthReport,
        )
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="broken_v1.0",
            health_level=HealthLevel.CRITICAL,
            health_score=15.0,
            avg_daily_signals=1.0,
            alerts=["no signals for 10 days", "drawdown breach"],
        )
        report = StrategyHealthReport.from_health(health)

        assert report.recommendation == HealthRecommendation.NOT_APPROVED
        assert report.can_use_in_decision is False
        assert report.needs_human_review is True

    def test_warning_needs_retrain(self) -> None:
        from qp.monitoring.strategy_health_report import (
            HealthRecommendation,
            StrategyHealthReport,
        )
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="decaying_v1.0",
            health_level=HealthLevel.WARNING,
            health_score=55.0,
            avg_daily_signals=4.0,
            alerts=["low signal count"],
        )
        report = StrategyHealthReport.from_health(health)

        assert report.recommendation == HealthRecommendation.NEEDS_RETRAIN

    def test_trend_computation_improving(self) -> None:
        from qp.monitoring.strategy_health_report import (
            _compute_trend,
        )
        from qp.monitoring.strategy_monitor import StrategyHealth

        # Scores: 40, 55, 70, 85, 92 — clearly improving
        history = [
            StrategyHealth(strategy_id="t", health_score=s) for s in [40.0, 55.0, 70.0, 85.0, 92.0]
        ]
        trend = _compute_trend(history)
        assert trend == "improving"

    def test_trend_computation_declining(self) -> None:
        from qp.monitoring.strategy_health_report import _compute_trend
        from qp.monitoring.strategy_monitor import StrategyHealth

        # Scores: 95, 88, 75, 60, 45 — clearly declining
        history = [
            StrategyHealth(strategy_id="t", health_score=s) for s in [95.0, 88.0, 75.0, 60.0, 45.0]
        ]
        trend = _compute_trend(history)
        assert trend == "declining"

    def test_trend_computation_stable(self) -> None:
        from qp.monitoring.strategy_health_report import _compute_trend
        from qp.monitoring.strategy_monitor import StrategyHealth

        history = [
            StrategyHealth(strategy_id="t", health_score=s) for s in [80.0, 81.0, 79.0, 80.5, 80.0]
        ]
        trend = _compute_trend(history)
        assert trend == "stable"

    def test_to_dict_includes_required_fields(self) -> None:
        from qp.monitoring.strategy_health_report import StrategyHealthReport
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="test",
            health_level=HealthLevel.HEALTHY,
            health_score=88.0,
        )
        report = StrategyHealthReport.from_health(health)
        d = report.to_dict()

        required = [
            "strategy_id",
            "recommendation",
            "recommendation_label",
            "health_score",
            "health_level",
            "trend",
            "trend_icon",
            "signal_summary",
            "alerts",
            "details",
        ]
        for field in required:
            assert field in d, f"Missing: {field}"

    def test_to_markdown(self) -> None:
        from qp.monitoring.strategy_health_report import StrategyHealthReport
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="momentum_v1.0",
            health_level=HealthLevel.HEALTHY,
            health_score=92.0,
            alerts=["low turnover"],
        )
        report = StrategyHealthReport.from_health(health)
        md = report.to_markdown()

        assert "momentum_v1.0" in md
        assert "92" in md
        assert "healthy" in md
        assert "low turnover" in md

    def test_warning_declining_is_not_approved(self) -> None:
        from qp.monitoring.strategy_health_report import (
            HealthRecommendation,
            StrategyHealthReport,
        )
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        # Declining history
        history = [
            StrategyHealth(strategy_id="t", health_score=s) for s in [90.0, 80.0, 70.0, 60.0, 50.0]
        ]
        health = StrategyHealth(
            strategy_id="t",
            health_level=HealthLevel.WARNING,
            health_score=50.0,
        )
        report = StrategyHealthReport.from_health(health, history=history)
        assert report.recommendation == HealthRecommendation.NOT_APPROVED

    def test_single_history_point_trend_unknown(self) -> None:
        from qp.monitoring.strategy_health_report import StrategyHealthReport
        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth

        health = StrategyHealth(
            strategy_id="new_strat",
            health_level=HealthLevel.HEALTHY,
            health_score=100.0,
        )
        history = [StrategyHealth(strategy_id="new_strat", health_score=100.0)]
        report = StrategyHealthReport.from_health(health, history=history)
        assert report.trend == "unknown"
        assert report.recommendation.value == "healthy"


class TestExitEnginePipelineIntegration:
    """Integration tests for Exit Engine → Daily Pipeline (P3.1)."""

    def test_exit_check_with_active_positions(self, tmp_path) -> None:
        """Active positions with stop-loss trigger should produce SELL signals."""
        import qp.decision.position_ledger as ledgermod
        from qp.portfolio.risk_exit import RiskExitManager

        orig_pos_dir = str(ledgermod.POSITIONS_DIR)
        try:
            ledgermod.POSITIONS_DIR = tmp_path / "positions"
            ledgermod.POSITIONS_PARQUET = ledgermod.POSITIONS_DIR / "positions.parquet"
            ledgermod.POSITIONS_INDEX = ledgermod.POSITIONS_DIR / "index.json"

            # Create active positions
            ledger = ledgermod.PositionLedger()
            ledger.open("600519", 1450.0, 100, decision_id="dp-001")  # Not in loss
            ledger.open("000001", 14.0, 1000, decision_id="dp-001")  # -14% → stop loss

            # Current prices: 600519 at 1500 (profit), 000001 at 12.0 (loss -14%)
            prices = {"600519": 1500.0, "000001": 12.0}
            holdings = {p.symbol: p.shares for p in ledger.get_active()}
            cost_basis = {p.symbol: p.entry_price for p in ledger.get_active()}

            mgr = RiskExitManager()
            exits = mgr.evaluate_daily(
                holdings=holdings,
                prices=prices,
                cost_basis=cost_basis,
                date_str="2026-07-30",
            )

            assert len(exits) == 1
            assert exits[0].symbol == "000001"
            assert "STOP_LOSS" in exits[0].reasons
        finally:
            ledgermod.POSITIONS_DIR = Path(orig_pos_dir)
            ledgermod.POSITIONS_PARQUET = Path(orig_pos_dir) / "positions.parquet"
            ledgermod.POSITIONS_INDEX = Path(orig_pos_dir) / "index.json"

    def test_exit_check_st_risk(self, tmp_path) -> None:
        """ST stock should trigger CRITICAL exit."""
        import qp.decision.position_ledger as ledgermod
        from qp.portfolio.risk_exit import RiskExitManager

        orig_pos_dir = str(ledgermod.POSITIONS_DIR)
        try:
            ledgermod.POSITIONS_DIR = tmp_path / "positions"
            ledgermod.POSITIONS_PARQUET = ledgermod.POSITIONS_DIR / "positions.parquet"
            ledgermod.POSITIONS_INDEX = ledgermod.POSITIONS_DIR / "index.json"

            ledger = ledgermod.PositionLedger()
            ledger.open("000888", 5.0, 1000, decision_id="dp-001")

            mgr = RiskExitManager()
            exits = mgr.evaluate_daily(
                holdings={"000888": 1000},
                prices={"000888": 4.5},
                cost_basis={"000888": 5.0},
                stock_names={"000888": "*ST风险"},
                date_str="2026-07-30",
            )

            assert len(exits) == 1
            assert "RISK_ST" in exits[0].reasons
        finally:
            ledgermod.POSITIONS_DIR = Path(orig_pos_dir)
            ledgermod.POSITIONS_PARQUET = Path(orig_pos_dir) / "positions.parquet"
            ledgermod.POSITIONS_INDEX = Path(orig_pos_dir) / "index.json"

    def test_exit_check_empty_positions(self) -> None:
        """No active positions → no exit signals."""
        from qp.portfolio.risk_exit import RiskExitManager

        mgr = RiskExitManager()
        exits = mgr.evaluate_daily(
            holdings={},
            prices={},
            cost_basis={},
        )
        assert exits == []

    def test_exit_priorities(self, tmp_path) -> None:
        """CRITICAL > HIGH priority ordering."""
        import qp.decision.position_ledger as ledgermod
        from qp.portfolio.risk_exit import Priority, RiskExitManager

        orig_pos_dir = str(ledgermod.POSITIONS_DIR)
        try:
            ledgermod.POSITIONS_DIR = tmp_path / "positions"
            ledgermod.POSITIONS_PARQUET = ledgermod.POSITIONS_DIR / "positions.parquet"
            ledgermod.POSITIONS_INDEX = ledgermod.POSITIONS_DIR / "index.json"

            mgr = RiskExitManager()
            exits = mgr.evaluate_daily(
                holdings={"000001": 1000, "000888": 500},
                prices={"000001": 12.0, "000888": 4.5},
                cost_basis={"000001": 14.0, "000888": 5.0},
                stock_names={"000001": "平安银行", "000888": "*ST风险"},
                date_str="2026-07-30",
            )

            # ST should be CRITICAL (priority 1), Stop Loss HIGH (priority 2)
            assert len(exits) == 2
            assert exits[0].symbol == "000888"  # CRITICAL first
            assert exits[0].priority == Priority.CRITICAL
            assert exits[1].priority == Priority.HIGH
        finally:
            ledgermod.POSITIONS_DIR = Path(orig_pos_dir)
            ledgermod.POSITIONS_PARQUET = Path(orig_pos_dir) / "positions.parquet"
            ledgermod.POSITIONS_INDEX = Path(orig_pos_dir) / "index.json"


class TestAlphaDecayDetector:
    """Test AlphaDecayDetector (P3.2)."""

    def test_position_in_top_n_no_signal(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector

        # Mock position
        class MockPos:
            symbol = "600519"
            is_active = True

        detector = AlphaDecayDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            today_signals={"600519", "000001", "000002"},
        )
        assert exits == []

    def test_position_fallen_out_generates_signal(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector
        from qp.portfolio.risk_exit import Priority, TradeReason

        class MockPos:
            symbol = "600519"
            is_active = True

        detector = AlphaDecayDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            today_signals={"000001", "000002"},  # 600519 not in top-N
        )
        assert len(exits) == 1
        assert exits[0].symbol == "600519"
        assert TradeReason.RANK_DROP in exits[0].reasons
        assert exits[0].priority == Priority.LOW

    def test_inactive_position_skipped(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector

        class MockPos:
            symbol = "600519"
            is_active = False  # Already closed

        detector = AlphaDecayDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            today_signals=set(),
        )
        assert exits == []

    def test_check_with_rank(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector

        class MockPos:
            symbol = "000001"
            is_active = True
            entry_price = 12.5

        detector = AlphaDecayDetector()
        exits = detector.check_with_rank(
            active_positions=[MockPos()],
            signal_ranks={"600519": 1, "000002": 2, "000001": 25},  # rank 25 > top_n
        )
        assert len(exits) == 1
        assert "排名 #25" in exits[0].detail
        assert "¥12.50" in exits[0].detail

    def test_check_with_rank_not_found(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector

        class MockPos:
            symbol = "000888"
            is_active = True
            entry_price = 5.0

        detector = AlphaDecayDetector()
        exits = detector.check_with_rank(
            active_positions=[MockPos()],
            signal_ranks={"600519": 1},  # 000888 not in ranks at all
        )
        assert len(exits) == 1
        assert "跌出 Top-20" in exits[0].detail

    def test_top_n_symbols_with_rank_column(self) -> None:
        import polars as pl

        from qp.portfolio.alpha_decay import top_n_symbols

        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E", "F"],
                "rank": [1, 2, 3, 4, 5, 6],
            }
        )
        result = top_n_symbols(df, top_n=3)
        assert result == {"A", "B", "C"}

    def test_top_n_symbols_with_score_column(self) -> None:
        import polars as pl

        from qp.portfolio.alpha_decay import top_n_symbols

        df = pl.DataFrame(
            {
                "symbol": ["X", "Y", "Z", "W"],
                "aggregated_score": [0.9, 0.7, 0.5, 0.3],
            }
        )
        result = top_n_symbols(df, top_n=2)
        assert result == {"X", "Y"}

    def test_top_n_symbols_empty(self) -> None:
        import polars as pl

        from qp.portfolio.alpha_decay import top_n_symbols

        assert top_n_symbols(None, top_n=10) == set()
        assert top_n_symbols(pl.DataFrame(), top_n=10) == set()

    def test_multiple_positions_mixed(self) -> None:
        from qp.portfolio.alpha_decay import AlphaDecayDetector

        class MockPos:
            pass

        p1 = MockPos()
        p1.symbol = "A"
        p1.is_active = True
        p2 = MockPos()
        p2.symbol = "B"
        p2.is_active = True
        p3 = MockPos()
        p3.symbol = "C"
        p3.is_active = False  # Inactive

        detector = AlphaDecayDetector()
        exits = detector.check(
            active_positions=[p1, p2, p3],
            today_signals={"A"},  # Only A still in top-N
        )
        assert len(exits) == 1  # Only B (C is inactive)
        assert exits[0].symbol == "B"


class TestFundamentalExitDetector:
    """Test FundamentalExitDetector (P3.3)."""

    def test_roe_decline_triggers_exit(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "600519"
            is_active = True

        # ROE declining from 25% to 15% → 40% decline
        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.15, 0.25],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"600519": fund},
        )
        assert len(exits) == 1
        assert "ROE" in exits[0].detail
        assert "40%" in exits[0].detail

    def test_stable_fundamentals_no_signal(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000001"
            is_active = True

        # Stable ROE
        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.18, 0.19],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000001": fund},
        )
        assert exits == []

    def test_revenue_growth_negative(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000002"
            is_active = True

        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.10, 0.10],
                "revenue_growth": [-0.15, 0.05],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000002": fund},
        )
        assert len(exits) == 1
        assert "营收增速" in exits[0].detail

    def test_net_profit_decline(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000003"
            is_active = True

        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.10, 0.10],
                "net_profit_growth": [-0.25, 0.08],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000003": fund},
        )
        assert len(exits) == 1
        assert "净利润增速" in exits[0].detail

    def test_debt_ratio_increase(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000004"
            is_active = True

        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "debt_ratio": [0.70, 0.50],  # 40% increase
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000004": fund},
        )
        assert len(exits) == 1
        assert "负债率" in exits[0].detail

    def test_insufficient_data_no_signal(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000005"
            is_active = True

        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30"],
                "ROE": [0.05],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000005": fund},
        )
        assert exits == []  # Need at least 2 periods

    def test_no_fundamental_data_skips(self) -> None:
        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000006"
            is_active = True

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={},
        )
        assert exits == []

    def test_inactive_position_skipped(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000007"
            is_active = False

        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.05, 0.20],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000007": fund},
        )
        assert exits == []

    def test_multiple_deterioration_reasons(self) -> None:
        import polars as pl

        from qp.portfolio.exit_signals import FundamentalExitDetector

        class MockPos:
            symbol = "000008"
            is_active = True

        # Both ROE decline AND negative revenue growth
        fund = pl.DataFrame(
            {
                "report_date": ["2026-06-30", "2026-03-31"],
                "ROE": [0.10, 0.20],
                "revenue_growth": [-0.12, 0.05],
            }
        )

        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[MockPos()],
            fundamental_data={"000008": fund},
        )
        assert len(exits) == 1
        detail = exits[0].detail
        assert "ROE" in detail
        assert "营收增速" in detail
        assert "FUNDAMENTAL_DETERIORATION" in exits[0].reasons
