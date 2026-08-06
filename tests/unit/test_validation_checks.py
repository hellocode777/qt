"""Tests for qp.validation — Strategy Validation Gate checks.

Covers all 14 check classes + RuleEngine integration:
  Factor (6): RankIC, ICIR, TStat, Stratification, Neutralization, MinSample
  Backtest (4): Sharpe, MaxDrawdown, Turnover, CostAdjusted
  Overfit (2): Overfit, FeatureImportance
  Paper Trading (3): SignalCorrelation, Slippage, SignalInterruption
  Shadow→Prod (2): KillSwitchHistory, HighVolSurvival
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from qp.shared.types import ValidationStatus
from qp.validation import (
    CodeReviewCheck,
    CostAdjustedCheck,
    ExperimentRecordCheck,
    FeatureImportanceCheck,
    HighVolSurvivalCheck,
    ICIRCheck,
    KillSwitchHistoryCheck,
    MaxDrawdownCheck,
    MinSamplePeriodCheck,
    NeutralizationCheck,
    OverfitCheck,
    RankICCheck,
    RuleEngine,
    SharpeCheck,
    SignalCorrelationCheck,
    SignalInterruptionCheck,
    SlippageDeviationCheck,
    StratificationCheck,
    TStatCheck,
    TurnoverCheck,
    ValidationContext,
    ValidationPipeline,
    ValidationResult,
)

# ==================================================================
# Fixtures — test data
# ==================================================================


def _make_test_data(
    n_days: int = 60, n_stocks: int = 20, seed: int = 42
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Create synthetic feature + price DataFrames with known IC."""
    rng = np.random.default_rng(seed)
    dates = [
        f"2024-{m:02d}-{d:02d}"
        for m in range(1, 3)
        for d in range(1, min(n_days // 2 + 1, 29))
    ][:n_days]
    symbols = [f"STK{i:03d}" for i in range(n_stocks)]

    rows = []
    px_rows = []
    for di, d in enumerate(dates):
        base_price = 10.0 + di * 0.1
        for _si, s in enumerate(symbols):
            feat_val = rng.normal(0, 1)
            close = (
                base_price + rng.normal(0, 2) + feat_val * 0.5
            )  # feature has real signal
            rows.append({"trade_date": d, "symbol": s, "feature_value": feat_val})
            px_rows.append({"trade_date": d, "symbol": s, "close": close})

    return pl.DataFrame(rows), pl.DataFrame(px_rows)


@pytest.fixture
def test_data() -> tuple[pl.DataFrame, pl.DataFrame]:
    return _make_test_data()


@pytest.fixture
def good_context(test_data) -> ValidationContext:
    feat_df, px_df = test_data
    return ValidationContext(
        feature_df=feat_df,
        price_df=px_df,
        backtest_metrics={
            "sharpe_ratio": 1.5,
            "max_drawdown_pct": -15.0,
            "daily_turnover_pct": 30.0,
            "sharpe_ratio_net": 1.2,
            "max_drawdown_pct_net": -18.0,
        },
        metadata={
            "pre_neutralization_ic": 0.05,
            "post_neutralization_ic": 0.04,
            "train_start": "2020-01-01",
            "train_end": "2024-12-31",
            "in_sample_ic": 0.06,
            "out_of_sample_ic": 0.04,
            "feature_importance": {
                "f1": 0.3,
                "f2": 0.25,
                "f3": 0.2,
                "f4": 0.15,
                "f5": 0.1,
            },
        },
    )


# ==================================================================
# Factor checks
# ==================================================================


class TestRankICCheck:
    def test_passes_with_good_data(self, good_context):
        check = RankICCheck(min_ic_mean=0.0)  # low threshold for synthetic data
        result = check.check(good_context)
        assert result.status == ValidationStatus.PASS

    def test_fails_with_high_threshold(self, good_context):
        check = RankICCheck(min_ic_mean=0.50)  # impossibly high
        result = check.check(good_context)
        assert result.status == ValidationStatus.FAIL

    def test_missing_data(self):
        check = RankICCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL
        assert "Missing" in result.detail

    def test_empty_data(self):
        check = RankICCheck()
        ctx = ValidationContext(
            feature_df=pl.DataFrame(
                {"trade_date": [], "symbol": [], "feature_value": []}
            ),
            price_df=pl.DataFrame({"trade_date": [], "symbol": [], "close": []}),
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL


class TestICIRCheck:
    def test_passes_with_good_data(self, good_context):
        check = ICIRCheck(min_ic_ir=0.0)
        result = check.check(good_context)
        assert result.status == ValidationStatus.PASS

    def test_missing_data(self):
        check = ICIRCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL


class TestTStatCheck:
    def test_passes_with_good_data(self, good_context):
        check = TStatCheck(min_t_stat=0.0)
        result = check.check(good_context)
        assert result.status == ValidationStatus.PASS

    def test_missing_data(self):
        check = TStatCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL


class TestStratificationCheck:
    def test_passes_with_good_data(self, good_context):
        check = StratificationCheck(min_t_stat=0.0, n_quantiles=5)
        result = check.check(good_context)
        assert result.status == ValidationStatus.PASS

    def test_missing_data(self):
        check = StratificationCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL


class TestNeutralizationCheck:
    def test_alpha_survives(self):
        check = NeutralizationCheck(min_ratio=0.5)
        ctx = ValidationContext(
            metadata={
                "pre_neutralization_ic": 0.05,
                "post_neutralization_ic": 0.04,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS
        assert result.actual_value == 0.8

    def test_alpha_destroyed(self):
        check = NeutralizationCheck(min_ratio=0.5)
        ctx = ValidationContext(
            metadata={
                "pre_neutralization_ic": 0.05,
                "post_neutralization_ic": 0.01,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL
        assert "Beta" in result.detail

    def test_missing_metadata(self):
        check = NeutralizationCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_zero_pre_ic(self):
        check = NeutralizationCheck()
        ctx = ValidationContext(
            metadata={
                "pre_neutralization_ic": 0.0,
                "post_neutralization_ic": 0.01,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_ratio_exactly_at_threshold(self):
        check = NeutralizationCheck(min_ratio=0.5)
        ctx = ValidationContext(
            metadata={
                "pre_neutralization_ic": 0.04,
                "post_neutralization_ic": 0.02,  # exactly 0.5
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS


class TestMinSamplePeriodCheck:
    def test_passes_five_years(self):
        check = MinSamplePeriodCheck(min_years=3.0)
        ctx = ValidationContext(
            metadata={
                "train_start": "2020-01-01",
                "train_end": "2024-12-31",
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails_one_year(self):
        check = MinSamplePeriodCheck(min_years=3.0)
        ctx = ValidationContext(
            metadata={
                "train_start": "2024-01-01",
                "train_end": "2024-12-31",
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_missing_metadata(self):
        check = MinSamplePeriodCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_bad_date_format(self):
        check = MinSamplePeriodCheck()
        ctx = ValidationContext(
            metadata={
                "train_start": "not-a-date",
                "train_end": "also-not-a-date",
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_reversed_dates(self):
        check = MinSamplePeriodCheck()
        ctx = ValidationContext(
            metadata={
                "train_start": "2024-12-31",
                "train_end": "2020-01-01",
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL


# ==================================================================
# Backtest checks
# ==================================================================


class TestSharpeCheck:
    def test_passes(self):
        check = SharpeCheck(min_sharpe=1.0)
        ctx = ValidationContext(backtest_metrics={"sharpe_ratio": 1.5})
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails(self):
        check = SharpeCheck(min_sharpe=1.0)
        ctx = ValidationContext(backtest_metrics={"sharpe_ratio": 0.5})
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_missing(self):
        check = SharpeCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL


class TestMaxDrawdownCheck:
    def test_passes(self):
        check = MaxDrawdownCheck(max_drawdown_pct=25.0)
        ctx = ValidationContext(backtest_metrics={"max_drawdown_pct": -15.0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails(self):
        check = MaxDrawdownCheck(max_drawdown_pct=25.0)
        ctx = ValidationContext(backtest_metrics={"max_drawdown_pct": -35.0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL


class TestTurnoverCheck:
    def test_passes(self):
        check = TurnoverCheck()
        ctx = ValidationContext(backtest_metrics={"daily_turnover_pct": 30.0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails_too_high(self):
        check = TurnoverCheck(max_turnover_pct=200.0)
        ctx = ValidationContext(backtest_metrics={"daily_turnover_pct": 300.0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_skips_when_missing(self):
        check = TurnoverCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.PASS  # gracefully skips


class TestCostAdjustedCheck:
    def test_passes_post_cost(self):
        check = CostAdjustedCheck(min_sharpe=1.0, max_drawdown_pct=25.0)
        ctx = ValidationContext(
            backtest_metrics={
                "sharpe_ratio_net": 1.2,
                "max_drawdown_pct_net": -18.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails_post_cost(self):
        check = CostAdjustedCheck(min_sharpe=1.0, max_drawdown_pct=25.0)
        ctx = ValidationContext(
            backtest_metrics={
                "sharpe_ratio_net": 0.6,
                "max_drawdown_pct_net": -30.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_missing_metrics(self):
        check = CostAdjustedCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_total_cost_fallback(self):
        check = CostAdjustedCheck(min_sharpe=0.5)
        ctx = ValidationContext(
            backtest_metrics={
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": -10.0,
                "total_cost_pct": 0.5,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS


# ==================================================================
# Overfit checks
# ==================================================================


class TestOverfitCheck:
    def test_passes(self):
        check = OverfitCheck(min_oos_ratio=0.5)
        ctx = ValidationContext(
            metadata={
                "in_sample_ic": 0.06,
                "out_of_sample_ic": 0.04,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS
        assert result.actual_value == pytest.approx(0.667, abs=0.01)

    def test_fails_oos_decay(self):
        check = OverfitCheck(min_oos_ratio=0.5)
        ctx = ValidationContext(
            metadata={
                "in_sample_ic": 0.10,
                "out_of_sample_ic": 0.02,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_missing_metadata(self):
        check = OverfitCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_zero_is_ic(self):
        check = OverfitCheck()
        ctx = ValidationContext(
            metadata={
                "in_sample_ic": 0.0,
                "out_of_sample_ic": 0.01,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL


class TestFeatureImportanceCheck:
    def test_passes_low_concentration(self):
        check = FeatureImportanceCheck(max_top1_pct=0.80)
        ctx = ValidationContext(
            metadata={"feature_importance": np.array([0.3, 0.25, 0.2, 0.15, 0.1])}
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_fails_high_concentration(self):
        check = FeatureImportanceCheck(max_top1_pct=0.80)
        ctx = ValidationContext(
            metadata={"feature_importance": np.array([0.9, 0.05, 0.03, 0.02])}
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_empty_features(self):
        check = FeatureImportanceCheck()
        ctx = ValidationContext(metadata={"feature_importance": np.array([])})
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS  # nothing to check

    def test_missing_metadata(self):
        check = FeatureImportanceCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL


# ==================================================================
# RuleEngine
# ==================================================================


class TestRuleEngine:
    def test_empty_engine_passes(self):
        engine = RuleEngine()
        result = engine.validate(ValidationContext())
        assert result.status == ValidationStatus.PASS
        assert result.confidence == 0.0

    def test_all_pass(self, good_context):
        engine = RuleEngine()
        engine.register(SharpeCheck(min_sharpe=0.0))
        engine.register(MaxDrawdownCheck(max_drawdown_pct=100.0))
        result = engine.validate(good_context)
        assert result.status == ValidationStatus.PASS
        assert result.confidence == 1.0

    def test_one_fails_overall_fails(self):
        engine = RuleEngine()
        engine.register(SharpeCheck(min_sharpe=1.0))
        engine.register(MaxDrawdownCheck(max_drawdown_pct=25.0))
        ctx = ValidationContext(
            backtest_metrics={
                "sharpe_ratio": 0.3,
                "max_drawdown_pct": -10.0,
            }
        )
        result = engine.validate(ctx)
        assert result.status == ValidationStatus.FAIL
        assert len(result.failed_rules) == 1
        assert "sharpe_ratio" in result.failed_rules[0]

    def test_composite_score(self):
        engine = RuleEngine()
        engine.register(SharpeCheck(min_sharpe=1.0))
        engine.register(MaxDrawdownCheck(max_drawdown_pct=25.0))
        ctx = ValidationContext(
            backtest_metrics={
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": -15.0,
            }
        )
        result = engine.validate(ctx)
        assert result.score > 0
        assert result.confidence == 1.0

    def test_recommendation_on_fail(self):
        engine = RuleEngine()
        engine.register(SharpeCheck(min_sharpe=2.0))
        ctx = ValidationContext(backtest_metrics={"sharpe_ratio": 0.5})
        result = engine.validate(ctx)
        assert "Fix" in result.recommendation


# ==================================================================
# ValidationResult
# ==================================================================


class TestValidationResult:
    def test_passed_property(self):
        vr = ValidationResult(status=ValidationStatus.PASS)
        assert vr.passed is True
        vr2 = ValidationResult(status=ValidationStatus.FAIL)
        assert vr2.passed is False

    def test_to_dict(self):
        vr = ValidationResult(
            status=ValidationStatus.PASS,
            score=85.0,
            confidence=0.9,
            failed_rules=[],
            recommendation="OK",
            rules=[],
        )
        d = vr.to_dict()
        assert d["status"] == "pass"
        assert d["score"] == 85.0
        assert d["confidence"] == 0.9

    def test_to_dict_with_rules(self):
        from qp.validation.result import RuleResult

        r = RuleResult(
            rule_name="test",
            status=ValidationStatus.PASS,
            score=100.0,
            threshold=0.02,
            actual_value=0.05,
            detail="ok",
        )
        vr = ValidationResult(rules=[r])
        d = vr.to_dict()
        assert len(d["rules"]) == 1
        assert d["rules"][0]["rule_name"] == "test"


# ==================================================================
# ValidationContext
# ==================================================================


class TestValidationContext:
    def test_defaults(self):
        ctx = ValidationContext()
        assert ctx.strategy_id == ""
        assert ctx.backtest_metrics == {}
        assert ctx.metadata == {}

    def test_with_all_fields(self):
        ctx = ValidationContext(
            strategy_id="test_v1",
            backtest_metrics={"sharpe_ratio": 1.2},
            metadata={"train_start": "2020-01-01"},
        )
        assert ctx.strategy_id == "test_v1"
        assert ctx.backtest_metrics["sharpe_ratio"] == 1.2


# ==================================================================
# Paper Trading checks
# ==================================================================


class TestSignalCorrelationCheck:
    def test_missing_data(self):
        check = SignalCorrelationCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_identical_signals(self):
        from qp.validation.checks.paper_trading_checks import (
            SignalCorrelationCheck as SCC,
        )

        check = SCC(min_correlation=0.8)
        sigs = {
            "2024-01-01": [0.1, 0.3, 0.5, 0.7, 0.9],
            "2024-01-02": [0.2, 0.4, 0.6, 0.8, 1.0],
            "2024-01-03": [0.1, 0.3, 0.5, 0.7, 0.9],
            "2024-01-04": [0.2, 0.4, 0.6, 0.8, 1.0],
            "2024-01-05": [0.1, 0.3, 0.5, 0.7, 0.9],
        }
        ctx = ValidationContext(
            metadata={
                "paper_trading_signals": sigs,
                "backtest_signals": sigs,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS
        assert result.actual_value == pytest.approx(1.0, abs=0.001)

    def test_poor_correlation(self):
        check = SignalCorrelationCheck(min_correlation=0.8)
        rng = np.random.default_rng(42)
        ctx = ValidationContext(
            metadata={
                "paper_trading_signals": {
                    f"day{i}": list(rng.random(10)) for i in range(10)
                },
                "backtest_signals": {
                    f"day{i}": list(rng.random(10)) for i in range(10)
                },
            }
        )
        result = check.check(ctx)
        # random signals should have low correlation
        assert result.actual_value < 0.5


class TestSlippageDeviationCheck:
    def test_missing_data(self):
        check = SlippageDeviationCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_within_bounds(self):
        check = SlippageDeviationCheck(max_deviation_pct=0.50)
        ctx = ValidationContext(
            metadata={
                "actual_slippage_bps": 3.0,
                "assumed_slippage_bps": 2.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS  # 50% exactly at threshold

    def test_exceeds_bounds(self):
        check = SlippageDeviationCheck(max_deviation_pct=0.50)
        ctx = ValidationContext(
            metadata={
                "actual_slippage_bps": 5.0,
                "assumed_slippage_bps": 2.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL  # 150% deviation

    def test_zero_assumed(self):
        check = SlippageDeviationCheck()
        ctx = ValidationContext(
            metadata={
                "actual_slippage_bps": 0.0,
                "assumed_slippage_bps": 0.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS


class TestSignalInterruptionCheck:
    def test_missing_data(self):
        check = SignalInterruptionCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_no_gaps(self):
        check = SignalInterruptionCheck()
        dates = [f"2024-01-{d:02d}" for d in range(1, 21)]
        ctx = ValidationContext(
            metadata={
                "paper_trading_expected_dates": dates,
                "paper_trading_actual_dates": dates,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_consecutive_gaps_exceeded(self):
        check = SignalInterruptionCheck(max_consecutive_missing=2)
        dates = [f"2024-01-{d:02d}" for d in range(1, 31)]
        # Missing 3 consecutive days
        actual = [
            d for d in dates if d not in {"2024-01-10", "2024-01-11", "2024-01-12"}
        ]
        ctx = ValidationContext(
            metadata={
                "paper_trading_expected_dates": dates,
                "paper_trading_actual_dates": actual,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_empty_dates(self):
        check = SignalInterruptionCheck()
        ctx = ValidationContext(
            metadata={
                "paper_trading_expected_dates": [],
                "paper_trading_actual_dates": [],
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS  # nothing to check


# ==================================================================
# Shadow → Production checks
# ==================================================================


class TestKillSwitchHistoryCheck:
    def test_missing_data(self):
        check = KillSwitchHistoryCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_no_triggers(self):
        check = KillSwitchHistoryCheck()
        ctx = ValidationContext(metadata={"kill_switch_trigger_count": 0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_has_triggers(self):
        check = KillSwitchHistoryCheck()
        ctx = ValidationContext(
            metadata={
                "kill_switch_trigger_count": 2,
                "kill_switch_triggers": ["DrawdownTrigger", "PSITrigger"],
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL
        assert "2 time" in result.detail

    def test_nested_in_paper_metrics(self):
        check = KillSwitchHistoryCheck()
        ctx = ValidationContext(
            metadata={
                "paper_trading_metrics": {
                    "kill_switch_trigger_count": 0,
                }
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS


class TestHighVolSurvivalCheck:
    def test_missing_data(self):
        check = HighVolSurvivalCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_no_high_vol_days(self):
        check = HighVolSurvivalCheck()
        ctx = ValidationContext(metadata={"high_volatility_days": 0})
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_survived_high_vol(self):
        check = HighVolSurvivalCheck(max_dd_during_high_vol=25.0)
        ctx = ValidationContext(
            metadata={
                "high_volatility_days": 12,
                "high_vol_max_drawdown_pct": -10.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_failed_high_vol(self):
        check = HighVolSurvivalCheck(max_dd_during_high_vol=25.0)
        ctx = ValidationContext(
            metadata={
                "high_volatility_days": 8,
                "high_vol_max_drawdown_pct": -30.0,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL

    def test_no_dd_data_still_passes(self):
        """If high-vol days exist but no DD data, still pass (condition 2 skipped)."""
        check = HighVolSurvivalCheck()
        ctx = ValidationContext(
            metadata={
                "high_volatility_days": 5,
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS


# ==================================================================
# Process checks
# ==================================================================


class TestCodeReviewCheck:
    def test_missing(self):
        check = CodeReviewCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_passed_via_metadata(self):
        check = CodeReviewCheck()
        ctx = ValidationContext(
            metadata={
                "code_review_passed": True,
                "code_reviewer": "alice",
                "code_review_date": "2026-07-22",
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS
        assert "alice" in result.detail


class TestExperimentRecordCheck:
    def test_missing(self):
        check = ExperimentRecordCheck()
        result = check.check(ValidationContext())
        assert result.status == ValidationStatus.FAIL

    def test_passed_via_inline_json(self):
        check = ExperimentRecordCheck()
        ctx = ValidationContext(
            metadata={
                "experiment_json": {
                    "experiment_id": "exp_001",
                    "config": {"features": ["m1"]},
                    "metrics": {"ic_mean": 0.05},
                    "lineage": {"dataset": "dp@v1"},
                },
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.PASS

    def test_incomplete_json(self):
        check = ExperimentRecordCheck()
        ctx = ValidationContext(
            metadata={
                "experiment_json": {
                    "experiment_id": "exp_001",
                },
            }
        )
        result = check.check(ctx)
        assert result.status == ValidationStatus.FAIL


# ==================================================================
# ValidationPipeline
# ==================================================================


class TestValidationPipeline:
    def test_backtest_stage_registers_checks(self):
        from qp.validation.pipeline import ValidationPipelineConfig

        config = ValidationPipelineConfig(stage="backtest_passed", strategy_id="t")
        pipeline = ValidationPipeline(config=config)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.feature_df = None
        ctx.price_df = None
        ctx.backtest_metrics = {"sharpe_ratio": 0.5}
        ctx.metadata = {"train_start": "2024-01-01", "train_end": "2024-06-30"}

        result = pipeline.run(ctx)
        v = result.metadata["validation"]
        # backtest_passed = 10 factor + 4 backtest + 2 overfit = 16
        assert len(v["rules"]) == 16

    def test_research_stage_minimal(self):
        from qp.validation.pipeline import ValidationPipelineConfig

        config = ValidationPipelineConfig(stage="research", strategy_id="t")
        pipeline = ValidationPipeline(config=config)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.feature_df = None
        ctx.price_df = None
        ctx.backtest_metrics = {}
        ctx.metadata = {"train_start": "2024-01-01", "train_end": "2024-06-30"}

        result = pipeline.run(ctx)
        v = result.metadata["validation"]
        assert len(v["rules"]) == 10

    def test_production_stage_all_checks(self):
        from qp.validation.pipeline import ValidationPipelineConfig

        config = ValidationPipelineConfig(stage="production", strategy_id="t")
        pipeline = ValidationPipeline(config=config)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.feature_df = None
        ctx.price_df = None
        ctx.backtest_metrics = {"sharpe_ratio": 0.5}
        ctx.metadata = {"train_start": "2024-01-01", "train_end": "2024-06-30"}

        result = pipeline.run(ctx)
        v = result.metadata["validation"]
        assert len(v["rules"]) >= 17

    def test_name_property(self):
        from qp.validation.pipeline import ValidationPipelineConfig

        config = ValidationPipelineConfig(stage="paper_trading")
        pipeline = ValidationPipeline(config=config)
        assert pipeline.name == "validation_gate_paper_trading"

    def test_threshold_override(self):
        from qp.validation.pipeline import ValidationPipelineConfig

        config = ValidationPipelineConfig(
            stage="backtest_passed",
            strategy_id="t",
            overrides={"sharpe_ratio": {"min_sharpe": 0.3}},
        )
        pipeline = ValidationPipeline(config=config)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.feature_df = None
        ctx.price_df = None
        ctx.backtest_metrics = {"sharpe_ratio": 0.5}
        ctx.metadata = {"train_start": "2024-01-01", "train_end": "2024-06-30"}

        result = pipeline.run(ctx)
        v = result.metadata["validation"]
        sharpe_rule = next(r for r in v["rules"] if r["rule_name"] == "sharpe_ratio")
        assert sharpe_rule["status"] == "pass"
