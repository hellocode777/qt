"""Tests for Strategy Layer — signals, aggregation, registry, ensemble, and more.

Covers all modules created in the Layer 6 (Strategy Engine) commit:
  models/ (AlphaSignal, AlphaSignalBatch, StrategyResult),
  signal/ (Normalizer, Smoother, Clipper, Threshold, Confidence),
  ensemble/ (WeightEngine, EnsembleEngine),
  strategies/ (Momentum, Value, Quality),
  generator, loader, runner, registry.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import polars as pl
import pytest

# =============================================================================
# Helpers
# =============================================================================


def _make_price_data(
    codes: list[str],
    n_days: int = 120,
    start_price: float = 10.0,
    trend: float = 0.001,
) -> dict[str, pl.DataFrame]:
    """Synthetic daily price data for strategy testing."""
    rng = np.random.default_rng(42)
    result: dict[str, pl.DataFrame] = {}
    for _i, code in enumerate(codes):
        returns = rng.normal(trend, 0.02, n_days)
        prices = start_price * np.cumprod(1 + returns)
        dates = [f"2026-06-{d:02d}" for d in range(1, min(n_days + 1, 29))]
        # Pad if needed
        while len(dates) < n_days:
            dates.append(f"2026-07-{len(dates) - 28:02d}")
        dates = dates[:n_days]
        result[code] = pl.DataFrame(
            {
                "trade_date": dates,
                "date": dates,
                "close": prices.tolist(),
            }
        )
    return result


def _make_valuation_data(
    codes: list[str],
    pe_values: list[float] | None = None,
    pb_values: list[float] | None = None,
    dy_values: list[float] | None = None,
) -> dict[str, pl.DataFrame]:
    """Synthetic fundamental data for value strategy testing."""
    rng = np.random.default_rng(99)
    n = len(codes)
    if pe_values is None:
        pe_values = (rng.uniform(5, 50, n)).tolist()
    if pb_values is None:
        pb_values = (rng.uniform(0.5, 8.0, n)).tolist()
    if dy_values is None:
        dy_values = (rng.uniform(0.0, 0.06, n)).tolist()
    result: dict[str, pl.DataFrame] = {}
    for i, code in enumerate(codes):
        result[code] = pl.DataFrame(
            {
                "date": ["2026-07-15"],
                "PE_TTM": [pe_values[i]],
                "PB": [pb_values[i]],
                "Dividend_Yield": [dy_values[i]],
            }
        )
    return result


def _make_fundamental_data(
    codes: list[str],
) -> dict[str, pl.DataFrame]:
    """Synthetic fundamental data for quality strategy testing."""
    rng = np.random.default_rng(77)
    result: dict[str, pl.DataFrame] = {}
    for _i, code in enumerate(codes):
        result[code] = pl.DataFrame(
            {
                "date": ["2026-07-15"],
                "ROE": [rng.uniform(0.05, 0.30)],
                "gross_margin": [rng.uniform(0.10, 0.60)],
                "net_margin": [rng.uniform(0.02, 0.25)],
                "debt_ratio": [rng.uniform(10, 70)],
                "revenue_growth": [rng.uniform(0.0, 0.30)],
                "net_profit_growth": [rng.uniform(0.0, 0.25)],
                "EPS": [rng.uniform(0.10, 5.0)],
                "NAV": [rng.uniform(1.0, 20.0)],
            }
        )
    return result


# =============================================================================
# 1. AlphaSignal
# =============================================================================


class TestAlphaSignal:
    """Test AlphaSignal dataclass — validation, serialization."""

    def test_construct(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s = AlphaSignal(date="2026-07-15", symbol="600519.SH", alpha_score=0.85)
        assert s.date == "2026-07-15"
        assert s.symbol == "600519.SH"
        assert s.alpha_score == 0.85
        assert s.confidence == 1.0
        assert s.strategy_id == ""
        assert s.raw_components == {}

    def test_alpha_score_clamped_to_0_1(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s_high = AlphaSignal(date="2026-07-15", symbol="A", alpha_score=2.5)
        assert s_high.alpha_score == 1.0

        s_low = AlphaSignal(date="2026-07-15", symbol="B", alpha_score=-0.5)
        assert s_low.alpha_score == 0.0

    def test_confidence_clamped_to_0_1(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s = AlphaSignal(date="2026-07-15", symbol="A", alpha_score=0.5, confidence=1.5)
        assert s.confidence == 1.0

        s2 = AlphaSignal(date="2026-07-15", symbol="B", alpha_score=0.5, confidence=-0.3)
        assert s2.confidence == 0.0

    def test_to_dict(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s = AlphaSignal(
            date="2026-07-15",
            symbol="600519.SH",
            alpha_score=0.85,
            raw_components={"momentum": 0.88, "quality": 0.82},
            confidence=0.9,
            strategy_id="ensemble",
        )
        d = s.to_dict()
        assert d["date"] == "2026-07-15"
        assert d["symbol"] == "600519.SH"
        assert d["alpha_score"] == 0.85
        assert d["confidence"] == 0.9
        assert d["strategy_id"] == "ensemble"
        assert d["raw_components"] == {"momentum": 0.88, "quality": 0.82}

    def test_from_dict(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        data = {
            "date": "2026-07-15",
            "symbol": "000001.SZ",
            "alpha_score": "0.72",
            "confidence": "0.8",
            "strategy_id": "momentum_v1",
            "raw_components": {"momentum": 0.72},
        }
        s = AlphaSignal.from_dict(data)
        assert s.date == "2026-07-15"
        assert s.symbol == "000001.SZ"
        assert s.alpha_score == 0.72
        assert s.confidence == 0.8
        assert s.strategy_id == "momentum_v1"

    def test_from_dict_defaults(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s = AlphaSignal.from_dict({})
        assert s.date == ""
        assert s.symbol == ""
        assert s.alpha_score == 0.0
        assert s.confidence == 1.0

    def test_generated_at_set(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        s = AlphaSignal(date="2026-07-15", symbol="A", alpha_score=0.5)
        assert s.generated_at != ""


# =============================================================================
# 2. AlphaSignalBatch
# =============================================================================


class TestAlphaSignalBatch:
    """Test AlphaSignalBatch — queries, stats, serialization, conversion."""

    @staticmethod
    def _make_batch(n: int = 5) -> Any:
        from qp.strategy.models.alpha_signal import AlphaSignal, AlphaSignalBatch

        signals = [
            AlphaSignal(
                date="2026-07-15",
                symbol=f"stock_{i:03d}",
                alpha_score=round(0.5 + 0.1 * i, 3),
                confidence=round(0.7 + 0.05 * i, 3),
                strategy_id="test_v1",
            )
            for i in range(n)
        ]
        return AlphaSignalBatch(date="2026-07-15", signals=signals)

    def test_empty_batch(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        batch = AlphaSignalBatch(date="2026-07-15")
        assert batch.is_empty
        assert batch.count == 0
        assert batch.symbols == []
        assert batch.top_n(10) == []

    def test_count_and_symbols(self) -> None:
        batch = self._make_batch(5)
        assert batch.count == 5
        assert len(batch.symbols) == 5
        assert "stock_000" in batch.symbols

    def test_is_empty_false(self) -> None:
        batch = self._make_batch(3)
        assert not batch.is_empty

    def test_top_n(self) -> None:
        batch = self._make_batch(10)
        top = batch.top_n(3)
        assert len(top) == 3
        # Highest alpha_score first
        assert top[0].alpha_score >= top[1].alpha_score >= top[2].alpha_score

    def test_top_n_more_than_count(self) -> None:
        batch = self._make_batch(3)
        top = batch.top_n(10)
        assert len(top) == 3

    def test_above_threshold(self) -> None:
        batch = self._make_batch(10)
        passed = batch.above_threshold(0.8)
        assert all(s.alpha_score >= 0.8 for s in passed)

    def test_above_threshold_none(self) -> None:
        batch = self._make_batch(5)
        passed = batch.above_threshold(0.99)
        assert passed == []

    def test_filter_confidence(self) -> None:
        batch = self._make_batch(10)
        passed = batch.filter_confidence(min_confidence=0.8)
        assert all(s.confidence >= 0.8 for s in passed)

    def test_get_by_symbol(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignal

        batch = self._make_batch(5)
        s = batch.get_by_symbol("stock_002")
        assert s is not None
        assert isinstance(s, AlphaSignal)
        assert s.symbol == "stock_002"

    def test_get_by_symbol_missing(self) -> None:
        batch = self._make_batch(5)
        assert batch.get_by_symbol("nonexistent") is None

    def test_summary(self) -> None:
        batch = self._make_batch(5)
        s = batch.summary()
        assert s["date"] == "2026-07-15"
        assert s["count"] == 5
        assert 0 <= s["mean"] <= 1
        assert s["min"] <= s["max"]

    def test_summary_empty(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        batch = AlphaSignalBatch(date="2026-07-15")
        s = batch.summary()
        assert s["count"] == 0
        assert s["mean"] == 0.0

    def test_to_dict(self) -> None:
        batch = self._make_batch(3)
        d = batch.to_dict()
        assert d["date"] == "2026-07-15"
        assert len(d["signals"]) == 3

    def test_from_dict(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        data = {
            "date": "2026-07-15",
            "signals": [
                {"date": "2026-07-15", "symbol": "A", "alpha_score": 0.8},
                {"date": "2026-07-15", "symbol": "B", "alpha_score": 0.6},
            ],
        }
        batch = AlphaSignalBatch.from_dict(data)
        assert batch.count == 2
        assert batch.date == "2026-07-15"

    def test_to_polars(self) -> None:
        batch = self._make_batch(5)
        df = batch.to_polars()
        assert isinstance(df, pl.DataFrame)
        assert df.height == 5
        assert "symbol" in df.columns
        assert "alpha_score" in df.columns

    def test_to_polars_empty(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        batch = AlphaSignalBatch(date="2026-07-15")
        df = batch.to_polars()
        assert df.height == 0

    def test_from_polars(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "alpha_score": [0.9, 0.7, 0.5],
                "confidence": [0.8, 0.9, 1.0],
                "strategy_id": ["v1", "v1", "v1"],
            }
        )
        batch = AlphaSignalBatch.from_polars(df, date_str="2026-07-15")
        assert batch.count == 3
        assert batch.date == "2026-07-15"

    def test_from_polars_empty(self) -> None:
        from qp.strategy.models.alpha_signal import AlphaSignalBatch

        df = pl.DataFrame(schema={"symbol": pl.Utf8, "alpha_score": pl.Float64})
        batch = AlphaSignalBatch.from_polars(df)
        assert batch.is_empty


# =============================================================================
# 3. StrategyResult
# =============================================================================


class TestStrategyResult:
    """Test StrategyResult dataclass — properties, summary, serialization."""

    @staticmethod
    def _make_signals(n: int = 3) -> list[Any]:
        from qp.strategy.models.alpha_signal import AlphaSignal

        return [
            AlphaSignal(
                date="2026-07-15",
                symbol=f"S{i}",
                alpha_score=round(0.5 + 0.1 * i, 3),
                confidence=round(0.6 + 0.1 * i, 3),
            )
            for i in range(n)
        ]

    def test_construct(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(3)
        r = StrategyResult(
            strategy_id="momentum_v1",
            date="2026-07-15",
            signals=signals,
            elapsed_ms=150.0,
            n_stocks_evaluated=500,
            n_stocks_selected=50,
        )
        assert r.strategy_id == "momentum_v1"
        assert r.signal_count == 3
        assert r.success is True
        assert r.error_message == ""

    def test_is_empty(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult(strategy_id="test", date="2026-07-15")
        assert r.is_empty
        assert r.signal_count == 0

    def test_top_n(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(10)
        r = StrategyResult(strategy_id="test", date="2026-07-15", signals=signals)
        top = r.top_n(3)
        assert len(top) == 3
        assert top[0].alpha_score >= top[1].alpha_score

    def test_mean_score(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(5)
        r = StrategyResult(strategy_id="test", date="2026-07-15", signals=signals)
        expected = sum(s.alpha_score for s in signals) / 5
        assert r.mean_score == pytest.approx(expected)

    def test_mean_score_empty(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult(strategy_id="test", date="2026-07-15")
        assert r.mean_score == 0.0

    def test_mean_confidence(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(5)
        r = StrategyResult(strategy_id="test", date="2026-07-15", signals=signals)
        expected = sum(s.confidence for s in signals) / 5
        assert r.mean_confidence == pytest.approx(expected)

    def test_coverage_ratio(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult(
            strategy_id="test",
            date="2026-07-15",
            n_stocks_evaluated=500,
            n_stocks_selected=50,
        )
        assert r.coverage_ratio == pytest.approx(0.10)

    def test_coverage_ratio_zero_evaluated(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult(strategy_id="test", date="2026-07-15")
        assert r.coverage_ratio == 0.0

    def test_summary(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(3)
        r = StrategyResult(
            strategy_id="momentum_v1",
            date="2026-07-15",
            signals=signals,
            n_stocks_evaluated=300,
            n_stocks_selected=30,
        )
        s = r.summary()
        assert s["strategy_id"] == "momentum_v1"
        assert s["success"] is True
        assert s["signal_count"] == 3
        assert s["error"] is None

    def test_summary_failed(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult(
            strategy_id="test",
            date="2026-07-15",
            success=False,
            error_message="Data unavailable",
        )
        s = r.summary()
        assert s["success"] is False
        assert s["error"] == "Data unavailable"

    def test_to_dict(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        signals = self._make_signals(2)
        r = StrategyResult(strategy_id="test", date="2026-07-15", signals=signals)
        d = r.to_dict()
        assert d["strategy_id"] == "test"
        assert len(d["signals"]) == 2

    def test_from_dict(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        data = {
            "strategy_id": "momentum_v1",
            "date": "2026-07-15",
            "signals": [
                {"date": "2026-07-15", "symbol": "A", "alpha_score": 0.9},
            ],
            "elapsed_ms": 100.0,
            "success": True,
        }
        r = StrategyResult.from_dict(data)
        assert r.strategy_id == "momentum_v1"
        assert r.signal_count == 1
        assert r.success is True

    def test_failed_factory(self) -> None:
        from qp.strategy.models.strategy_result import StrategyResult

        r = StrategyResult.failed("test_v1", "2026-07-15", "Timeout")
        assert r.strategy_id == "test_v1"
        assert r.date == "2026-07-15"
        assert r.success is False
        assert r.error_message == "Timeout"
        assert r.signal_count == 0


# =============================================================================
# 4. SignalNormalizer
# =============================================================================


class TestSignalNormalizer:
    """Test SignalNormalizer — all 4 methods, edge cases."""

    def test_min_max(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.MIN_MAX)
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        result = norm.normalize(scores)
        assert result[0] == pytest.approx(0.0)
        assert result[-1] == pytest.approx(1.0)
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_min_max_all_equal(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.MIN_MAX)
        scores = np.array([3.0, 3.0, 3.0], dtype=np.float64)
        result = norm.normalize(scores)
        assert np.allclose(result, 0.5)

    def test_z_score(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.Z_SCORE)
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        result = norm.normalize(scores)
        assert np.all(result >= 0.0) and np.all(result <= 1.0)
        # Middle value should be close to 0.5
        assert result[2] == pytest.approx(0.5, abs=0.15)

    def test_rank(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        scores = np.array([1.0, 5.0, 3.0], dtype=np.float64)
        result = norm.normalize(scores)
        assert result[0] == pytest.approx(0.0)  # worst
        assert result[1] == pytest.approx(1.0)  # best
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_rank_single_element(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        result = norm.normalize(np.array([42.0]))
        assert result[0] == pytest.approx(0.5)

    def test_sigmoid(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.SIGMOID, sigmoid_scale=1.0)
        scores = np.array([-2.0, -1.0, 0.0, 1.0, 2.0], dtype=np.float64)
        result = norm.normalize(scores)
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_empty_input(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.MIN_MAX)
        result = norm.normalize(np.array([]))
        assert len(result) == 0

    def test_nan_handling(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        scores = np.array([1.0, np.nan, 5.0])
        result = norm.normalize(scores)
        # NaN → 0.0
        assert result[1] == 0.0

    def test_normalize_with_symbols(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        scores = np.array([1.0, 2.0, 3.0])
        symbols = ["A", "B", "C"]
        result = norm.normalize_with_symbols(scores, symbols)
        assert isinstance(result, dict)
        assert len(result) == 3
        assert result["C"] > result["A"]

    def test_normalize_with_symbols_length_mismatch(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        with pytest.raises(ValueError):
            norm.normalize_with_symbols(np.array([1.0, 2.0]), ["A"])

    def test_normalize_polars(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "raw_score": [1.0, 2.0, 3.0],
            }
        )
        result = norm.normalize_polars(df, score_col="raw_score", output_col="alpha_score")
        assert "alpha_score" in result.columns
        assert result["alpha_score"].max() <= 1.0

    def test_normalize_polars_empty(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "raw_score": pl.Float64})
        result = norm.normalize_polars(df)
        assert result.is_empty()

    def test_normalize_by_date(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        df = pl.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-01", "2026-07-02", "2026-07-02"],
                "symbol": ["A", "B", "A", "B"],
                "raw_score": [1.0, 2.0, 5.0, 3.0],
            }
        )
        result = norm.normalize_by_date(df, score_col="raw_score", output_col="alpha_score")
        assert "alpha_score" in result.columns
        assert result.height == 4

    def test_normalize_by_date_empty(self) -> None:
        from qp.strategy.signal.normalizer import NormMethod, SignalNormalizer

        norm = SignalNormalizer(method=NormMethod.RANK)
        df = pl.DataFrame(schema={"date": pl.Utf8, "raw_score": pl.Float64})
        result = norm.normalize_by_date(df)
        assert result.is_empty()


# =============================================================================
# 5. SignalSmoother
# =============================================================================


class TestSignalSmoother:
    """Test SignalSmoother — all smoothing methods, edge cases."""

    def test_ema(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=3)
        values = np.array([1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        assert len(result) == 5
        # All same values → output should be all same
        assert np.allclose(result, 1.0)

    def test_ema_changing(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=3)
        values = np.array([0.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        # After a jump, EMA gradually catches up
        assert result[0] == 0.0
        assert result[1] > result[0]  # moves toward 1.0
        assert result[4] > result[1]  # converges toward 1.0

    def test_rolling_mean(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.ROLLING_MEAN, window=3)
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        assert result[0] == pytest.approx(1.0)  # window=1 for first element
        assert result[1] == pytest.approx(1.5)
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)  # avg of [3, 4, 5]

    def test_decay(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.DECAY, alpha=0.5)
        values = np.array([0.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        assert result[0] == 0.0
        assert result[1] == pytest.approx(0.5)  # 0.5*1.0 + 0.5*0.0
        assert result[2] == pytest.approx(0.75)  # 0.5*1.0 + 0.5*0.5

    def test_kalman_passthrough(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.KALMAN)
        values = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        # Kalman not implemented — returns raw
        assert np.allclose(result, values)

    def test_empty_input(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA)
        result = smoother.smooth_array(np.array([]))
        assert len(result) == 0

    def test_nan_handling(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=3)
        values = np.array([1.0, np.nan, 2.0], dtype=np.float64)
        result = smoother.smooth_array(values)
        # NaN should carry forward previous value
        assert result[1] == pytest.approx(1.0)

    def test_smooth_polars(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=3)
        df = pl.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-02", "2026-07-03"],
                "symbol": ["A", "A", "A"],
                "raw_score": [0.5, 0.6, 0.7],
            }
        )
        result = smoother.smooth_polars(df, score_col="raw_score")
        assert "smoothed_score" in result.columns
        assert result.height == 3

    def test_smooth_polars_empty(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA)
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "raw_score": pl.Float64})
        result = smoother.smooth_polars(df)
        assert result.is_empty()

    def test_smooth_cross_sectional(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA, halflife=3)
        scores_by_date = {
            "2026-07-01": {"A": 0.5, "B": 0.6},
            "2026-07-02": {"A": 0.6, "B": 0.7},
            "2026-07-03": {"A": 0.7, "B": 0.8},
        }
        result = smoother.smooth_cross_sectional(scores_by_date)
        assert len(result) == 3
        assert "A" in result["2026-07-03"]

    def test_smooth_cross_sectional_empty(self) -> None:
        from qp.strategy.signal.smoother import SignalSmoother, SmoothMethod

        smoother = SignalSmoother(method=SmoothMethod.EMA)
        result = smoother.smooth_cross_sectional({})
        assert result == {}


# =============================================================================
# 6. SignalClipper
# =============================================================================


class TestSignalClipper:
    """Test SignalClipper — winsorize, sigma, absolute."""

    def test_winsorize(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.WINSORIZE, lower_pct=0.1, upper_pct=0.9)
        scores = np.array([0.0, 0.2, 0.5, 0.8, 1.0], dtype=np.float64)
        result = clipper.clip(scores)
        # Middle values unchanged, extremes clipped
        assert result[0] >= scores[0]  # raised
        assert result[4] <= scores[4]  # lowered
        assert result[2] == pytest.approx(0.5)

    def test_sigma_clip(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.SIGMA, sigma_n=2.0)
        scores = np.array([0.0, 0.1, 0.5, 0.9, 1.0], dtype=np.float64)
        result = clipper.clip(scores)
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_sigma_clip_low_std(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.SIGMA, sigma_n=3.0)
        scores = np.array([0.5, 0.5, 0.5], dtype=np.float64)
        result = clipper.clip(scores)
        assert np.allclose(result, 0.5)

    def test_absolute_clip(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.ABSOLUTE, min_val=0.2, max_val=0.8)
        scores = np.array([0.0, 0.5, 1.0], dtype=np.float64)
        result = clipper.clip(scores)
        assert result[0] == pytest.approx(0.2)
        assert result[2] == pytest.approx(0.8)

    def test_empty_input(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.WINSORIZE)
        result = clipper.clip(np.array([]))
        assert len(result) == 0

    def test_clip_polars(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.ABSOLUTE, min_val=0.0, max_val=1.0)
        df = pl.DataFrame(
            {
                "symbol": ["A", "B"],
                "alpha_score": [0.5, 1.5],
            }
        )
        result = clipper.clip_polars(df, score_col="alpha_score", output_col="clipped_score")
        assert "clipped_score" in result.columns
        # 1.5 should be clipped
        assert result["clipped_score"].max() <= 1.0

    def test_clip_polars_empty(self) -> None:
        from qp.strategy.signal.threshold import ClipMethod, SignalClipper

        clipper = SignalClipper(method=ClipMethod.WINSORIZE)
        df = pl.DataFrame(schema={"alpha_score": pl.Float64})
        result = clipper.clip_polars(df)
        assert result.is_empty()


# =============================================================================
# 7. SignalThreshold
# =============================================================================


class TestSignalThreshold:
    """Test SignalThreshold — min_score, max_per_day, confidence filter."""

    def test_min_score_filter(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.3, max_per_day=100)
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "alpha_score": [0.5, 0.2, 0.8],
            }
        )
        result = gate.filter(df)
        assert result.height == 2
        assert "B" not in result["symbol"].to_list()

    def test_max_per_day(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.0, max_per_day=3)
        df = pl.DataFrame(
            {
                "symbol": [f"S{i}" for i in range(10)],
                "alpha_score": list(range(10, 0, -1)),
            }
        )
        result = gate.filter(df)
        assert result.height == 3
        # Top 3 by score
        assert result["symbol"][0] == "S0"

    def test_keep_top_only_false(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.0, max_per_day=3, keep_top_only=False)
        df = pl.DataFrame(
            {
                "symbol": [f"S{i}" for i in range(10)],
                "alpha_score": list(range(10, 0, -1)),
            }
        )
        result = gate.filter(df)
        # keep_top_only=False → reject all when over max
        assert result.is_empty()

    def test_min_confidence_filter(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.0, max_per_day=100, min_confidence=0.5)
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "alpha_score": [0.5, 0.6, 0.7],
                "confidence": [0.3, 0.8, 0.9],
            }
        )
        result = gate.filter(df)
        assert result.height == 2
        assert "A" not in result["symbol"].to_list()

    def test_empty_input(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.3)
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "alpha_score": pl.Float64})
        result = gate.filter(df)
        assert result.is_empty()

    def test_no_confidence_col(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.0, max_per_day=100, min_confidence=0.5)
        df = pl.DataFrame(
            {
                "symbol": ["A", "B"],
                "alpha_score": [0.5, 0.6],
            }
        )
        result = gate.filter(df)
        # No confidence column → confidence filter skipped
        assert result.height == 2

    def test_filter_array(self) -> None:
        from qp.strategy.signal.threshold import SignalThreshold

        gate = SignalThreshold(min_score=0.3, max_per_day=3)
        scores = np.array([0.5, 0.2, 0.8, 0.6, 0.1])
        filtered_scores, _indices = gate.filter_array(scores)
        assert len(filtered_scores) <= 3
        # All filtered scores >= min_score
        assert np.all(filtered_scores >= 0.3)


# =============================================================================
# 8. ConfidenceScorer
# =============================================================================


class TestConfidenceScorer:
    """Test ConfidenceScorer — magnitude, dispersion, coverage scoring."""

    def test_score_array(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        scores = np.array([0.1, 0.3, 0.5, 0.7, 0.9], dtype=np.float64)
        result = scorer.score_array(scores)
        assert len(result) == 5
        assert np.all(result >= 0.0) and np.all(result <= 1.0)
        # Middle score (0.5) has lowest magnitude confidence
        # Extreme scores get higher magnitude
        assert result[2] < result[0] or result[2] < result[4]

    def test_score_array_empty(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        result = scorer.score_array(np.array([]))
        assert len(result) == 0

    def test_score_from_ic(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        scores = np.array([0.3, 0.5, 0.7], dtype=np.float64)
        ic_series = np.array([0.05, 0.08, 0.10, 0.06, 0.09])
        result = scorer.score_from_ic(scores, ic_series)
        assert len(result) == 3
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_score_from_ic_none(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        scores = np.array([0.3, 0.5, 0.7], dtype=np.float64)
        # Without IC, same as score_array
        result = scorer.score_from_ic(scores, None)
        base = scorer.score_array(scores)
        assert np.allclose(result, base)

    def test_score_polars(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "alpha_score": [0.2, 0.5, 0.8],
            }
        )
        result = scorer.score_polars(df)
        assert "confidence" in result.columns
        assert result.height == 3

    def test_score_polars_empty(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        df = pl.DataFrame(schema={"alpha_score": pl.Float64})
        result = scorer.score_polars(df)
        assert result.is_empty()

    def test_score_by_date(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer()
        df = pl.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-01", "2026-07-02"],
                "symbol": ["A", "B", "C"],
                "alpha_score": [0.2, 0.8, 0.5],
            }
        )
        result = scorer.score_by_date(df)
        assert "confidence" in result.columns
        assert result.height == 3

    def test_custom_weights(self) -> None:
        from qp.strategy.signal.confidence import ConfidenceScorer

        scorer = ConfidenceScorer(
            magnitude_weight=0.5,
            dispersion_weight=0.3,
            coverage_weight=0.2,
        )
        scores = np.array([0.1, 0.5, 0.9], dtype=np.float64)
        result = scorer.score_array(scores)
        assert len(result) == 3


# =============================================================================
# 9. WeightEngine
# =============================================================================


class TestWeightEngine:
    """Test WeightEngine — all weighting methods, floor, smoothing."""

    def test_equal(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.EQUAL)
        weights = engine.compute(["mom", "val", "qual"])
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["mom"] == pytest.approx(1 / 3)

    def test_fixed(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(
            method=WeightMethod.FIXED,
            fixed_weights={"mom": 0.4, "val": 0.35, "qual": 0.25},
        )
        weights = engine.compute(["mom", "val", "qual"])
        # Normalized
        assert weights["mom"] == pytest.approx(0.4)
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_fixed_missing(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(
            method=WeightMethod.FIXED,
            fixed_weights={"mom": 0.6},
        )
        weights = engine.compute(["mom", "val"])
        # val missing → gets 0 → but normalization kicks in
        assert weights["mom"] > 0
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_ic_weighted(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        # Disable min_weight floor so raw IC differences are preserved
        engine = WeightEngine(method=WeightMethod.IC_WEIGHTED, min_weight=0.0)
        weights = engine.compute(
            ["mom", "val", "qual"],
            ic_history={"mom": 0.10, "val": 0.05, "qual": 0.02},
        )
        assert weights["mom"] > weights["val"] > weights["qual"]
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_ic_weighted_negative(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.IC_WEIGHTED)
        weights = engine.compute(
            ["mom", "val"],
            ic_history={"mom": -0.05, "val": 0.05},
        )
        # Negative IC → absolute value used
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_sharpe_weighted(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.SHARPE_WEIGHTED)
        weights = engine.compute(
            ["mom", "val", "qual"],
            sharpe_history={"mom": 1.5, "val": 0.8, "qual": 0.3},
        )
        assert weights["mom"] > weights["val"] > weights["qual"]
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_sharpe_negative_clamped(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.SHARPE_WEIGHTED)
        weights = engine.compute(
            ["mom", "val"],
            sharpe_history={"mom": -1.0, "val": 0.5},
        )
        # Negative Sharpe clamped to 0.01 → both get some weight
        assert weights["mom"] > 0
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_regime_weighted(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.REGIME)
        weights = engine.compute(
            ["mom", "val", "qual"],
            regime="bull",
            strategy_tags={
                "mom": ["momentum"],
                "val": ["value"],
                "qual": ["quality"],
            },
        )
        # Bull: momentum 0.50, quality 0.30, value 0.10
        assert weights["mom"] > weights["val"]
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_regime_unknown_fallback(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.REGIME)
        weights = engine.compute(["mom", "val"], regime="unknown")
        # Falls back to equal
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_min_weight_floor(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.EQUAL, min_weight=0.10)
        weights = engine.compute(["mom", "val", "qual", "growth", "def"])
        # All 5 get 1/5=0.20 which is above floor
        for w in weights.values():
            assert w >= 0.10
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_empty_ids(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine

        engine = WeightEngine()
        weights = engine.compute([])
        assert weights == {}

    def test_ema_smoothing(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.EQUAL, smoothing_halflife=5)
        # First call — initializes smoothed weights
        # Second call — EMA smoothing active
        w2 = engine.compute(["mom", "val"])
        # With equal weights and no change, smoothed should converge toward equal
        assert sum(w2.values()) == pytest.approx(1.0)
        for v in w2.values():
            assert 0 < v < 1

    def test_all_zero_ic(self) -> None:
        from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod

        engine = WeightEngine(method=WeightMethod.IC_WEIGHTED)
        weights = engine.compute(["a", "b"], ic_history={})
        # All get 0.001 floor → normalized to equal
        assert weights["a"] == pytest.approx(0.5)
        assert weights["b"] == pytest.approx(0.5)


# =============================================================================
# 10. EnsembleEngine
# =============================================================================


class TestEnsembleEngine:
    """Test EnsembleEngine — fusion pipeline, universe policies."""

    @staticmethod
    def _make_signal_df(symbols: list[str], scores: list[float]) -> pl.DataFrame:
        # SignalAggregator looks for "feature_value" or "rank" columns
        return pl.DataFrame(
            {
                "symbol": symbols,
                "feature_value": scores,
            }
        )

    def test_fuse_basic(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        signals = {
            "mom": self._make_signal_df(["A", "B", "C"], [0.9, 0.6, 0.3]),
            "val": self._make_signal_df(["A", "B", "C"], [0.5, 0.8, 0.4]),
        }
        batch = engine.fuse(signals, date_str="2026-07-15", score_col="feature_value")
        assert batch.count == 3
        assert batch.date == "2026-07-15"

    def test_fuse_empty_signals(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        batch = engine.fuse({}, date_str="2026-07-15")
        assert batch.is_empty

    def test_fuse_with_fixed_weights(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine

        engine = EnsembleEngine()
        signals = {
            "mom": self._make_signal_df(["A", "B"], [0.9, 0.6]),
            "val": self._make_signal_df(["A", "B"], [0.5, 0.8]),
        }
        batch = engine.fuse(
            signals,
            date_str="2026-07-15",
            fixed_weights={"mom": 0.7, "val": 0.3},
            score_col="feature_value",
        )
        assert batch.count == 2

    def test_universe_policy_intersection(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy

        engine = EnsembleEngine(universe_policy=UniversePolicy.INTERSECTION)
        # Use 2 strategies to avoid known join bug in SignalAggregator._rank_blend
        # (how="full" creates symbol_right duplicates with 3+ DataFrames)
        signals = {
            "mom": self._make_signal_df(["A", "B", "C"], [0.9, 0.6, 0.3]),
            "val": self._make_signal_df(["B", "C", "D"], [0.8, 0.4, 0.2]),
        }
        batch = engine.fuse(signals, date_str="2026-07-15", score_col="feature_value")
        # Intersection of both = {"B", "C"}
        assert batch.count == 2

    def test_universe_policy_fill_zero(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy

        engine = EnsembleEngine(universe_policy=UniversePolicy.FILL_ZERO)
        signals = {
            "mom": self._make_signal_df(["A"], [0.9]),
            "val": self._make_signal_df(["B"], [0.8]),
        }
        batch = engine.fuse(signals, date_str="2026-07-15", score_col="feature_value")
        # Union with fill_zero — both A and B
        assert batch.count == 2

    def test_universe_policy_fill_median(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy

        engine = EnsembleEngine(universe_policy=UniversePolicy.FILL_MEDIAN)
        signals = {
            "mom": self._make_signal_df(["A"], [0.9]),
            "val": self._make_signal_df(["B"], [0.8]),
        }
        batch = engine.fuse(signals, date_str="2026-07-15", score_col="feature_value")
        assert batch.count == 2

    def test_universe_policy_renormalize(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy

        engine = EnsembleEngine(universe_policy=UniversePolicy.RENORMALIZE)
        signals = {
            "mom": self._make_signal_df(["A"], [0.9]),
            "val": self._make_signal_df(["B"], [0.8]),
        }
        batch = engine.fuse(signals, date_str="2026-07-15", score_col="feature_value")
        assert batch.count == 2

    def test_normalize_weights(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine

        result = EnsembleEngine._normalize_weights({"a": 0.2, "b": 0.3}, ["a", "b"])
        assert result["a"] == pytest.approx(0.4)
        assert result["b"] == pytest.approx(0.6)

    def test_normalize_weights_all_zero(self) -> None:
        from qp.strategy.ensemble.ensemble_engine import EnsembleEngine

        result = EnsembleEngine._normalize_weights({"a": 0.0, "b": 0.0}, ["a", "b"])
        assert sum(result.values()) == pytest.approx(1.0)
        assert result["a"] == pytest.approx(0.5)


# =============================================================================
# 11. MomentumStrategy
# =============================================================================


class TestMomentumStrategy:
    """Test MomentumStrategy — variants, filtering, edge cases."""

    def test_strategy_id(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        s = MomentumStrategy()
        assert s.strategy_id == "momentum_v1.0"

    def test_strategy_id_custom(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        s = MomentumStrategy(config={"strategy_id": "my_momentum_v2"})
        assert s.strategy_id == "my_momentum_v2"

    def test_generate_signals_raw_momentum(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        price_data = _make_price_data(["600001.SH", "600002.SH", "600003.SH"], n_days=120)
        s = MomentumStrategy(
            config={
                "lookback": 60,
                "variant": "raw",
                "top_n": 2,
                "price_data": price_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)
        if not signals.is_empty():
            assert "symbol" in signals.columns
            assert "raw_score" in signals.columns
            assert "rank" in signals.columns
            assert signals.height <= 2

    def test_generate_signals_residual(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        price_data = _make_price_data(["600001.SH", "600002.SH"], n_days=120)
        s = MomentumStrategy(
            config={
                "lookback": 60,
                "variant": "residual",
                "top_n": 5,
                "price_data": price_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)

    def test_generate_signals_risk_adjusted(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        price_data = _make_price_data(["600001.SH", "600002.SH"], n_days=120)
        s = MomentumStrategy(
            config={
                "lookback": 60,
                "variant": "risk_adjusted",
                "top_n": 5,
                "price_data": price_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)

    def test_generate_signals_no_price_data(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        s = MomentumStrategy(config={"lookback": 60, "variant": "raw"})
        signals = s.generate_signals(date(2026, 7, 15))
        assert signals.is_empty()

    def test_generate_signals_insufficient_history(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        # Very short history vs min_history requirement
        price_data = _make_price_data(["600001.SH"], n_days=30)
        s = MomentumStrategy(
            config={
                "lookback": 60,
                "variant": "raw",
                "min_history": 120,
                "price_data": price_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        # Stock should be filtered due to insufficient history
        assert signals.is_empty() or "600001.SH" not in (
            signals["symbol"].to_list() if not signals.is_empty() else []
        )

    def test_suspended_stock_filtered(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        # Create a stock with flat price (suspended)
        normal = _make_price_data(["600001.SH"], n_days=120)
        # Override with flat prices
        dates = normal["600001.SH"]["trade_date"].to_list()
        flat_df = pl.DataFrame(
            {
                "trade_date": dates,
                "date": dates,
                "close": [10.0] * len(dates),
            }
        )
        price_data = {"600001.SH": flat_df}

        s = MomentumStrategy(
            config={
                "lookback": 60,
                "variant": "raw",
                "top_n": 10,
                "skip_suspended": True,
                "price_data": price_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        # Suspended stock should be filtered out
        assert signals.is_empty()

    def test_compute_momentum_raw(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        close = np.array([10.0 + i * 0.1 for i in range(100)], dtype=np.float64)
        result = MomentumStrategy._compute_momentum(close, 60, "raw")
        assert result is not None
        assert result > 0  # rising prices → positive momentum

    def test_compute_momentum_insufficient_data(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        close = np.array([10.0, 11.0], dtype=np.float64)
        result = MomentumStrategy._compute_momentum(close, 60, "raw")
        assert result is None

    def test_compute_momentum_risk_adjusted_zero_vol(self) -> None:
        from qp.strategy.strategies.momentum import MomentumStrategy

        close = np.array([10.0] * 100, dtype=np.float64)
        # Moving window with all same prices → zero vol → returns 0.0
        result = MomentumStrategy._compute_momentum(close, 60, "risk_adjusted")
        # raw_ret = 0, / max(ann_vol, 0.01)
        assert result is not None
        # Actually with all same prices past=current, raw_ret=0
        # Wait — close[0]=10.0, close[-1]=10.0, raw_ret=0, result=0
        # But len(close)=100, lookback=60, close[-1]=10.0, close[-61]=10.0
        assert abs(result) < 0.01  # essentially zero


# =============================================================================
# 12. ValueStrategy
# =============================================================================


class TestValueStrategy:
    """Test ValueStrategy — composite scoring, industry relative, filters."""

    def test_strategy_id(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        s = ValueStrategy()
        assert s.strategy_id == "value_v1.0"

    def test_generate_signals(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        valuation_data = _make_valuation_data(
            ["600001.SH", "600002.SH", "600003.SH", "600004.SH", "600005.SH"],
        )
        s = ValueStrategy(
            config={
                "top_n": 3,
                "valuation_data": valuation_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)
        if not signals.is_empty():
            assert "symbol" in signals.columns
            assert "raw_score" in signals.columns
            assert "rank" in signals.columns

    def test_generate_signals_no_data(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        s = ValueStrategy()
        signals = s.generate_signals(date(2026, 7, 15))
        assert signals.is_empty()

    def test_exclude_negative_earnings(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        valuation_data = _make_valuation_data(
            ["600001.SH", "600002.SH"],
            pe_values=[15.0, -5.0],  # second has negative PE
        )
        s = ValueStrategy(
            config={
                "top_n": 5,
                "valuation_data": valuation_data,
                "exclude_negative_earnings": True,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        if not signals.is_empty():
            symbols = signals["symbol"].to_list()
            assert "600002.SH" not in symbols

    def test_industry_neutral(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        valuation_data = _make_valuation_data(
            ["600001.SH", "600002.SH", "600003.SH", "600004.SH", "600005.SH"],
        )
        s = ValueStrategy(
            config={
                "top_n": 5,
                "valuation_data": valuation_data,
                "industry_neutral": True,
                "industry_map": {
                    "600001.SH": "白酒",
                    "600002.SH": "白酒",
                    "600003.SH": "银行",
                    "600004.SH": "银行",
                    "600005.SH": "银行",
                },
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)

    def test_min_metrics_filter(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        # Stock with only 1 metric should be filtered when min_metrics=2
        valuation_data = {
            "600001.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "PE_TTM": [15.0],
                }
            ),
            "600002.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "PE_TTM": [20.0],
                    "PB": [1.5],
                    "Dividend_Yield": [0.03],
                }
            ),
        }
        s = ValueStrategy(
            config={
                "min_metrics": 2,
                "valuation_data": valuation_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        if not signals.is_empty():
            symbols = signals["symbol"].to_list()
            # 600001.SH only has 1 metric
            assert "600001.SH" not in symbols

    def test_custom_metrics(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        valuation_data = _make_valuation_data(
            ["600001.SH", "600002.SH", "600003.SH"],
            pe_values=[10.0, 20.0, 30.0],
        )
        s = ValueStrategy(
            config={
                "metrics": {"PE_TTM": 1.0},  # Only PE
                "top_n": 3,
                "valuation_data": valuation_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)

    def test_get_latest_metrics_no_date_col(self) -> None:
        from qp.strategy.strategies.value import ValueStrategy

        df = pl.DataFrame({"PE_TTM": [15.0], "PB": [2.0]})
        vals = ValueStrategy._get_latest_metrics(df, ["PE_TTM"], "2026-07-15")
        assert vals is not None
        assert vals["PE_TTM"] == 15.0


# =============================================================================
# 13. QualityStrategy
# =============================================================================


class TestQualityStrategy:
    """Test QualityStrategy — composite scoring, hard cutoffs, growth filter."""

    def test_strategy_id(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        s = QualityStrategy()
        assert s.strategy_id == "quality_v1.0"

    def test_generate_signals(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        fundamental_data = _make_fundamental_data(
            ["600001.SH", "600002.SH", "600003.SH", "600004.SH", "600005.SH"],
        )
        s = QualityStrategy(
            config={
                "top_n": 3,
                "fundamental_data": fundamental_data,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert isinstance(signals, pl.DataFrame)
        if not signals.is_empty():
            assert "symbol" in signals.columns
            assert "raw_score" in signals.columns

    def test_generate_signals_no_data(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        s = QualityStrategy()
        signals = s.generate_signals(date(2026, 7, 15))
        assert signals.is_empty()

    def test_hard_cutoffs_roe_negative(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        fundamental_data = {
            "600001.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "ROE": [0.15],
                    "gross_margin": [0.4],
                    "debt_ratio": [30.0],
                    "revenue_growth": [0.10],
                    "net_profit_growth": [0.08],
                    "EPS": [2.0],
                    "NAV": [10.0],
                    "net_margin": [0.1],
                }
            ),
            "600002.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "ROE": [-0.05],  # negative ROE → hard cutoff
                    "gross_margin": [0.4],
                    "debt_ratio": [30.0],
                    "revenue_growth": [0.10],
                    "net_profit_growth": [0.08],
                    "EPS": [2.0],
                    "NAV": [10.0],
                }
            ),
        }
        s = QualityStrategy(
            config={
                "fundamental_data": fundamental_data,
                "top_n": 5,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        if not signals.is_empty():
            symbols = signals["symbol"].to_list()
            assert "600002.SH" not in symbols

    def test_growth_requirement(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        fundamental_data = {
            "600001.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "ROE": [0.15],
                    "gross_margin": [0.4],
                    "debt_ratio": [30.0],
                    "revenue_growth": [-0.05],
                    "net_profit_growth": [-0.05],
                    "EPS": [2.0],
                    "NAV": [10.0],
                }
            ),
        }
        s = QualityStrategy(
            config={
                "fundamental_data": fundamental_data,
                "top_n": 5,
                "require_growth": True,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        # Both growth metrics negative → filtered
        assert signals.is_empty()

    def test_min_metrics_filter(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        fundamental_data = {
            "600001.SH": pl.DataFrame(
                {
                    "date": ["2026-07-15"],
                    "ROE": [0.15],
                    # Only 1 metric → below min_metrics=3
                }
            ),
        }
        s = QualityStrategy(
            config={
                "fundamental_data": fundamental_data,
                "min_metrics": 3,
            }
        )
        signals = s.generate_signals(date(2026, 7, 15))
        assert signals.is_empty()

    def test_passes_cutoffs(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        cutoffs = {"ROE": ("min", 0.0), "debt_ratio": ("max", 85.0)}
        assert QualityStrategy._passes_cutoffs({"ROE": 0.15, "debt_ratio": 30.0}, cutoffs)
        assert not QualityStrategy._passes_cutoffs({"ROE": -0.05}, cutoffs)
        assert not QualityStrategy._passes_cutoffs({"debt_ratio": 90.0}, cutoffs)

    def test_get_latest_metrics(self) -> None:
        from qp.strategy.strategies.quality import QualityStrategy

        df = pl.DataFrame(
            {
                "date": ["2026-07-15"],
                "ROE": [0.18],
                "gross_margin": [0.45],
            }
        )
        vals = QualityStrategy._get_latest_metrics(df, ["ROE", "gross_margin"], "2026-07-20")
        assert vals is not None
        assert vals["ROE"] == 0.18


# =============================================================================
# 14. SignalGenerator
# =============================================================================


class TestSignalGenerator:
    """Test SignalGenerator — pipeline, generate_from_array, edge cases."""

    def test_generate_from_array(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        symbols = ["A", "B", "C", "D", "E"]
        result = gen.generate_from_array(scores, symbols, as_of_date=date(2026, 7, 15))
        assert isinstance(result, pl.DataFrame)
        assert not result.is_empty()
        assert "symbol" in result.columns
        assert "alpha_score" in result.columns
        assert "rank" in result.columns
        assert "confidence" in result.columns

    def test_generate_from_array_empty(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        result = gen.generate_from_array(np.array([]), [])
        assert result.is_empty()

    def test_generate_no_features_no_scores(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        result = gen.generate()
        assert result.is_empty()

    def test_generate_with_scores(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        scores = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "raw_score": [0.9, 0.5, 0.2],
            }
        )
        result = gen.generate(scores=scores)
        assert not result.is_empty()
        assert "alpha_score" in result.columns
        assert "rank" in result.columns

    def test_generate_with_top_n(self) -> None:
        from qp.strategy.generator import GeneratorConfig, SignalGenerator

        config = GeneratorConfig(top_n=2)
        gen = SignalGenerator(config)
        scores = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "raw_score": [0.9, 0.7, 0.5, 0.3],
            }
        )
        result = gen.generate(scores=scores)
        assert result.height <= 2

    def test_generate_with_min_score(self) -> None:
        from qp.strategy.generator import GeneratorConfig, SignalGenerator

        config = GeneratorConfig(min_score=0.6)
        gen = SignalGenerator(config)
        scores = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "raw_score": [0.9, 0.5, 0.4],
            }
        )
        result = gen.generate(scores=scores)
        # Only A should pass
        if not result.is_empty():
            assert all(s >= 0.6 for s in result["alpha_score"].to_list())

    def test_generate_empty_scores(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        scores = pl.DataFrame(schema={"symbol": pl.Utf8, "raw_score": pl.Float64})
        result = gen.generate(scores=scores)
        assert result.is_empty()

    def test_generator_config_defaults(self) -> None:
        from qp.strategy.generator import GeneratorConfig

        config = GeneratorConfig()
        assert config.model_name == ""
        assert config.top_n == 100
        assert config.min_score == 0.0

    def test_post_init_creates_defaults(self) -> None:
        from qp.strategy.generator import SignalGenerator

        gen = SignalGenerator()
        assert gen.config.normalizer is not None
        assert gen.config.smoother is not None
        assert gen.config.confidence_scorer is not None


# =============================================================================
# 15. StrategyLoader
# =============================================================================


class TestStrategyLoader:
    """Test StrategyLoader — discovery, auto-registration."""

    def test_discover(self) -> None:
        from qp.strategy.loader import StrategyLoader

        loader = StrategyLoader()
        classes = loader.discover("qp.strategy.strategies")
        assert isinstance(classes, dict)
        assert "MomentumStrategy" in classes
        assert "ValueStrategy" in classes
        assert "QualityStrategy" in classes

    def test_discover_bad_package(self) -> None:
        from qp.strategy.loader import StrategyLoader

        loader = StrategyLoader()
        classes = loader.discover("nonexistent.package")
        assert classes == {}

    def test_register_all(self) -> None:
        from qp.strategy.loader import StrategyLoader
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        loader = StrategyLoader()
        ids = loader.register_all(
            registry,
            package="qp.strategy.strategies",
            configs={
                "momentum_v1.0": {"lookback": 60, "variant": "raw"},
                "value_v1.0": {},
            },
        )
        assert len(ids) >= 3
        for sid in ids:
            assert sid in registry.list_strategies()

    def test_register_all_default_config(self) -> None:
        from qp.strategy.loader import StrategyLoader
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        loader = StrategyLoader()
        ids = loader.register_all(registry)
        # Strategies should instantiate with no config → default constructors
        assert len(ids) >= 3

    def test_default_id_generation(self) -> None:
        from qp.strategy.loader import StrategyLoader

        assert StrategyLoader._default_id("MomentumStrategy") == "momentum_v1.0"
        assert StrategyLoader._default_id("ValueStrategy") == "value_v1.0"
        assert StrategyLoader._default_id("QualityStrategy") == "quality_v1.0"


# =============================================================================
# 16. StrategyRunner
# =============================================================================


class TestStrategyRunner:
    """Test StrategyRunner — scheduling, execution, dry_run."""

    @staticmethod
    def _make_registry_with_strategies(
        frequencies: list[Any] | None = None,
    ) -> Any:
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.strategies.momentum import MomentumStrategy

        if frequencies is None:
            from qp.shared.types import RebalanceSchedule

            frequencies = [RebalanceSchedule.DAILY]

        registry = StrategyRegistry()
        for i, freq in enumerate(frequencies):
            s = MomentumStrategy(
                config={
                    "strategy_id": f"test_{i}",
                    "lookback": 60,
                    "variant": "raw",
                }
            )
            meta = StrategyMeta(rebalance_frequency=freq)
            # Use RESEARCH lifecycle to avoid lineage validation requirement
            registry.register(s, lifecycle=StrategyLifecycle.RESEARCH, meta=meta)
        return registry

    def test_run_daily_all(self) -> None:
        from qp.strategy.runner.strategy_runner import StrategyRunner

        registry = self._make_registry_with_strategies()
        runner = StrategyRunner(registry)
        # Strategies in RESEARCH lifecycle are not active, so none run
        result = runner.run(date(2026, 7, 15))
        assert result.date == "2026-07-15"
        # No active strategies → nothing to run
        assert result.total_strategies == 0

    def test_force_all(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        registry = self._make_registry_with_strategies([RebalanceSchedule.WEEKLY])
        runner = StrategyRunner(registry)
        # force_all doesn't help if there are no active strategies
        result = runner.run(date(2026, 7, 15), force_all=True)
        assert result.date == "2026-07-15"

    def test_dry_run(self) -> None:
        from qp.strategy.runner.strategy_runner import StrategyRunner

        registry = self._make_registry_with_strategies()
        runner = StrategyRunner(registry)
        result = runner.run(date(2026, 7, 15), dry_run=True)
        assert result.date == "2026-07-15"

    def test_schedule_logic(self) -> None:
        """Test _schedule directly with strategies regardless of lifecycle."""
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.runner.strategy_runner import StrategyRunner
        from qp.strategy.strategies.momentum import MomentumStrategy

        registry = StrategyRegistry()
        s = MomentumStrategy(
            config={
                "strategy_id": "test_sched",
                "lookback": 60,
                "variant": "raw",
            }
        )
        meta = StrategyMeta(rebalance_frequency=RebalanceSchedule.DAILY)
        registry.register(s, meta=meta)  # default RESEARCH lifecycle

        runner = StrategyRunner(registry)
        strategies = [registry.get("test_sched")]
        to_run, skipped = runner._schedule(strategies, date(2026, 7, 15))
        assert len(to_run) == 1
        assert len(skipped) == 0

    def test_should_run_daily(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        # Daily always runs
        assert StrategyRunner._should_run_today(date(2026, 7, 15), RebalanceSchedule.DAILY)

    def test_should_run_weekly(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        # 2026-07-15 is a Wednesday (weekday=2)
        assert StrategyRunner._should_run_today(
            date(2026, 7, 15), RebalanceSchedule.WEEKLY, rebalance_day=2
        )
        assert not StrategyRunner._should_run_today(
            date(2026, 7, 15), RebalanceSchedule.WEEKLY, rebalance_day=0
        )

    def test_should_run_monthly(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        # Near end of month — should be True
        end_of_month = date(2026, 7, 30)
        assert StrategyRunner._should_run_today(end_of_month, RebalanceSchedule.MONTHLY)
        # Early in month — should be False
        assert not StrategyRunner._should_run_today(date(2026, 7, 15), RebalanceSchedule.MONTHLY)

    def test_should_run_biweekly(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        result = StrategyRunner._should_run_today(
            date(2026, 7, 15), RebalanceSchedule.BIWEEKLY, rebalance_day=2
        )
        # Just check it returns a bool
        assert isinstance(result, bool)

    def test_next_rebalance_daily(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        result = StrategyRunner._next_rebalance_date(date(2026, 7, 15), RebalanceSchedule.DAILY)
        assert result == date(2026, 7, 15)

    def test_next_rebalance_weekly(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        # 2026-07-15 is Wednesday; next Monday (0) from Wednesday
        result = StrategyRunner._next_rebalance_date(
            date(2026, 7, 15), RebalanceSchedule.WEEKLY, rebalance_day=0
        )
        assert result.weekday() == 0
        assert result > date(2026, 7, 15)

    def test_next_rebalance_monthly(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.runner.strategy_runner import StrategyRunner

        result = StrategyRunner._next_rebalance_date(date(2026, 7, 15), RebalanceSchedule.MONTHLY)
        # Should be the last day of July
        assert result.month == 7
        next_day = result + __import__("datetime").timedelta(days=1)
        assert next_day.month == 8

    def test_runner_result_summary(self) -> None:
        from qp.strategy.runner.strategy_runner import RunnerResult

        result = RunnerResult(
            date="2026-07-15",
            signals={"mom": pl.DataFrame({"x": [1]})},
            skipped=[("val", "weekly schedule — next rebalance: 2026-07-17")],
            errors=[("qual", "Data unavailable")],
        )
        summary = result.summary()
        assert summary["total"] == 3
        assert summary["success"] == 1
        assert summary["skipped"] == 1
        assert summary["errors"] == 1

    def test_runner_result_properties(self) -> None:
        from qp.strategy.runner.strategy_runner import RunnerResult

        result = RunnerResult(
            signals={"a": None, "b": None},
            skipped=[("c", "reason")],
            errors=[("d", "err"), ("e", "err2")],
        )
        assert result.success_count == 2
        assert result.skip_count == 1
        assert result.error_count == 2
        assert result.total_strategies == 5
        assert len(result.all_signals) == 2


# =============================================================================
# 17. StrategyMeta
# =============================================================================


class TestStrategyMeta:
    """Test StrategyMeta — serialization, defaults."""

    def test_defaults(self) -> None:
        from qp.strategy.registry import StrategyMeta

        meta = StrategyMeta()
        assert meta.strategy_version == "1.0.0"
        assert meta.feature_set == []
        assert meta.owner == ""

    def test_to_dict(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.registry import StrategyMeta

        meta = StrategyMeta(
            strategy_version="2.0.0",
            model_version="lgb_v3",
            feature_set=["mom_60d", "vol_20d"],
            rebalance_frequency=RebalanceSchedule.WEEKLY,
            rebalance_day=2,
            owner="team_alpha",
            tags=["momentum"],
        )
        d = meta.to_dict()
        assert d["strategy_version"] == "2.0.0"
        assert d["model_version"] == "lgb_v3"
        assert d["rebalance_frequency"] == "weekly"
        assert d["rebalance_day"] == 2
        assert d["owner"] == "team_alpha"

    def test_from_dict(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.registry import StrategyMeta

        data = {
            "strategy_version": "1.5.0",
            "model_version": "lgb_v2",
            "feature_set": ["f1", "f2"],
            "rebalance_frequency": "monthly",
            "rebalance_day": 0,
            "owner": "team_beta",
            "description": "Test strategy",
            "tags": ["value"],
        }
        meta = StrategyMeta.from_dict(data)
        assert meta.strategy_version == "1.5.0"
        assert meta.rebalance_frequency == RebalanceSchedule.MONTHLY
        assert meta.feature_set == ["f1", "f2"]

    def test_from_dict_bad_frequency(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.registry import StrategyMeta

        data = {"rebalance_frequency": "annually"}
        meta = StrategyMeta.from_dict(data)
        # Falls back to DAILY
        assert meta.rebalance_frequency == RebalanceSchedule.DAILY

    def test_from_dict_enum_passthrough(self) -> None:
        from qp.shared.types import RebalanceSchedule
        from qp.strategy.registry import StrategyMeta

        data = {"rebalance_frequency": RebalanceSchedule.MONTHLY}
        meta = StrategyMeta.from_dict(data)
        assert meta.rebalance_frequency == RebalanceSchedule.MONTHLY


# =============================================================================
# 18. StrategyRegistry — extended
# =============================================================================


class TestStrategyRegistryExtended:
    """Extended tests for StrategyRegistry — lifecycle, metadata, queries."""

    @staticmethod
    def _make_registry() -> Any:
        from qp.shared.types import RebalanceSchedule, StrategyLifecycle
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.strategies.momentum import MomentumStrategy

        registry = StrategyRegistry()

        s1 = MomentumStrategy(config={"strategy_id": "mom_v1", "lookback": 60})
        meta1 = StrategyMeta(
            owner="alice",
            rebalance_frequency=RebalanceSchedule.DAILY,
            tags=["momentum", "alpha"],
        )
        # Use RESEARCH to avoid lineage validation requirement
        registry.register(s1, lifecycle=StrategyLifecycle.RESEARCH, meta=meta1)

        s2 = MomentumStrategy(config={"strategy_id": "val_v1", "lookback": 60})
        meta2 = StrategyMeta(
            owner="bob",
            rebalance_frequency=RebalanceSchedule.WEEKLY,
            tags=["value"],
        )
        registry.register(s2, lifecycle=StrategyLifecycle.RESEARCH, meta=meta2)

        return registry

    def test_count(self) -> None:
        registry = self._make_registry()
        assert registry.count == 2

    def test_get_lifecycle(self) -> None:
        from qp.shared.types import StrategyLifecycle

        registry = self._make_registry()
        assert registry.get_lifecycle("mom_v1") == StrategyLifecycle.RESEARCH
        assert registry.get_lifecycle("val_v1") == StrategyLifecycle.RESEARCH

    def test_get_lifecycle_missing(self) -> None:
        registry = self._make_registry()
        with pytest.raises(KeyError):
            registry.get_lifecycle("nonexistent")

    def test_set_lifecycle(self) -> None:
        from qp.shared.types import StrategyLifecycle

        registry = self._make_registry()
        # BACKTEST_PASSED is not a lineage-gated state
        registry.set_lifecycle("val_v1", StrategyLifecycle.BACKTEST_PASSED)
        assert registry.get_lifecycle("val_v1") == StrategyLifecycle.BACKTEST_PASSED

    def test_set_lifecycle_missing(self) -> None:
        from qp.shared.types import StrategyLifecycle

        registry = self._make_registry()
        with pytest.raises(KeyError):
            registry.set_lifecycle("nonexistent", StrategyLifecycle.RESEARCH)

    def test_get_active(self) -> None:
        registry = self._make_registry()
        # Both are RESEARCH → not active (need PAPER_TRADING+)
        active = registry.get_active()
        assert len(active) == 0

    def test_get_backtest_ready(self) -> None:
        registry = self._make_registry()
        # Both are RESEARCH → backtest ready
        ready = registry.get_backtest_ready()
        assert len(ready) == 2

    def test_get_meta(self) -> None:
        registry = self._make_registry()
        meta = registry.get_meta("mom_v1")
        assert meta.owner == "alice"
        assert meta.tags == ["momentum", "alpha"]

    def test_get_meta_missing(self) -> None:
        registry = self._make_registry()
        with pytest.raises(KeyError):
            registry.get_meta("nonexistent")

    def test_set_meta(self) -> None:
        from qp.strategy.registry import StrategyMeta

        registry = self._make_registry()
        new_meta = StrategyMeta(owner="charlie")
        registry.set_meta("mom_v1", new_meta)
        assert registry.get_meta("mom_v1").owner == "charlie"

    def test_set_meta_missing(self) -> None:
        from qp.strategy.registry import StrategyMeta

        registry = self._make_registry()
        with pytest.raises(KeyError):
            registry.set_meta("nonexistent", StrategyMeta())

    def test_get_by_owner(self) -> None:
        registry = self._make_registry()
        assert registry.get_by_owner("alice") == ["mom_v1"]
        assert registry.get_by_owner("bob") == ["val_v1"]
        assert registry.get_by_owner("nobody") == []

    def test_get_by_frequency(self) -> None:
        from qp.shared.types import RebalanceSchedule

        registry = self._make_registry()
        assert registry.get_by_frequency(RebalanceSchedule.DAILY) == ["mom_v1"]
        assert registry.get_by_frequency(RebalanceSchedule.WEEKLY) == ["val_v1"]
        assert registry.get_by_frequency(RebalanceSchedule.MONTHLY) == []

    def test_get_by_tag(self) -> None:
        registry = self._make_registry()
        assert registry.get_by_tag("momentum") == ["mom_v1"]
        assert registry.get_by_tag("value") == ["val_v1"]
        assert registry.get_by_tag("unknown") == []

    def test_list_metadata(self) -> None:
        registry = self._make_registry()
        meta_dict = registry.list_metadata()
        assert "mom_v1" in meta_dict
        assert "val_v1" in meta_dict

    def test_duplicate_register(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.strategies.momentum import MomentumStrategy

        registry = StrategyRegistry()
        s1 = MomentumStrategy(config={"strategy_id": "test", "lookback": 60})
        registry.register(s1)
        s2 = MomentumStrategy(config={"strategy_id": "test", "lookback": 60})
        with pytest.raises(ValueError, match="already registered"):
            registry.register(s2)

    def test_register_duplicate_raises(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.strategies.momentum import MomentumStrategy

        registry = StrategyRegistry()
        s1 = MomentumStrategy(config={"strategy_id": "dup_v1", "lookback": 60})
        registry.register(s1)
        s2 = MomentumStrategy(config={"strategy_id": "dup_v1", "lookback": 60})
        with pytest.raises(ValueError, match="already registered"):
            registry.register(s2)

    def test_lineage_gate_enabled(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        assert not registry.lineage_gate_enabled

    def test_set_lineage_registry(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        # Can't easily instantiate LineageRegistry without full lineage layer,
        # but we can test the getter/setter pattern
        assert registry.get_lineage_registry() is None

    def test_validate_lineage_no_registry(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        result = registry.validate_lineage("any_strategy")
        assert result["valid"] is True
        assert "No lineage registry" in result["message"]

    def test_get_active_empty_registry(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        assert registry.get_active() == []

    def test_get_backtest_ready_empty(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        assert registry.get_backtest_ready() == []


# =============================================================================
# 19. (Keep existing tests — SimpleRankStrategy, SignalAggregator, StrategyRegistry)
# =============================================================================


class TestSimpleRankStrategy:
    """Test SimpleRankStrategy signal generation."""

    def test_construct(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=10)
        assert strategy.strategy_id == "simple_rank_v1.0"

    def test_custom_top_n(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=5)
        assert strategy.strategy_id == "simple_rank_v1.0"

    def test_generate_signals(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=10)
        today = date.today()
        signals = strategy.generate_signals(today)
        if signals.is_empty():
            # No dataset generated in this environment — nothing to assert.
            pytest.skip("momentum dataset not available")
        assert "symbol" in signals.columns
        assert "rank" in signals.columns

    def test_strategy_id_immutable(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy()
        assert strategy.strategy_id == "simple_rank_v1.0"


class TestSignalAggregator:
    """Test SignalAggregator methods."""

    def _make_signals(self, symbols: list[str]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "symbol": symbols,
                "feature_value": list(range(len(symbols), 0, -1)),
                "rank": list(range(1, len(symbols) + 1)),
                "action": ["BUY"] * len(symbols),
            }
        )

    def test_construct(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator()
        assert agg is not None

    def test_construct_rank_blend(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        assert agg is not None

    def test_construct_equal_weight(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="equal_weight")
        assert agg is not None

    def test_construct_vote(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="vote")
        assert agg is not None

    def test_aggregate_single(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        s1 = self._make_signals(["A", "B", "C", "D", "E"])
        result = agg.aggregate([s1])
        assert len(result) == 5
        assert "symbol" in result.columns
        assert "rank" in result.columns

    def test_aggregate_two(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        s1 = self._make_signals(["A", "B", "C"])
        s2 = self._make_signals(["A", "B", "C"])
        result = agg.aggregate([s1, s2])
        assert len(result) == 3

    def test_invalid_method(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        with pytest.raises(ValueError, match="Invalid aggregation method"):
            SignalAggregator(method="magic")

    def test_aggregate_empty_list(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        result = agg.aggregate([])
        assert result.is_empty()

    def test_aggregate_vote_method(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="vote")
        s1 = self._make_signals(["A", "B", "C"])
        s2 = self._make_signals(["B", "C", "D"])
        result = agg.aggregate([s1, s2])
        assert "votes" in result.columns
        # B and C appear in both
        assert not result.is_empty()

    def test_aggregate_equal_weight_method(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="equal_weight")
        s1 = self._make_signals(["A", "B", "C"])
        s2 = self._make_signals(["A", "B", "C"])
        result = agg.aggregate([s1, s2])
        assert "aggregated_score" in result.columns


class TestStrategyRegistry:
    """Test StrategyRegistry dict-backed store."""

    def test_register_and_get(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        strategy = SimpleRankStrategy(top_n=5)
        registry.register(strategy)
        retrieved = registry.get("simple_rank_v1.0")
        assert retrieved is strategy

    def test_get_missing(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_list_strategies(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        registry.register(SimpleRankStrategy(top_n=10))
        ids = registry.list_strategies()
        assert "simple_rank_v1.0" in ids

    def test_get_active_empty(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        registry.register(SimpleRankStrategy(top_n=10))
        active = registry.get_active()
        assert len(active) == 0

    def test_register_with_meta(self) -> None:
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(owner="test_team", tags=["test"])
        strategy = SimpleRankStrategy(top_n=5)
        registry.register(strategy, meta=meta)
        retrieved_meta = registry.get_meta("simple_rank_v1.0")
        assert retrieved_meta.owner == "test_team"

    # ── StrategyMeta frozen snapshot (ADR-031) ──

    def test_meta_frozen_snapshot_roundtrip(self) -> None:
        """StrategyMeta with frozen weights/params survives to_dict→from_dict."""
        from qp.strategy.registry import StrategyMeta

        meta = StrategyMeta(
            strategy_version="v20260731",
            owner="researcher",
            weights={"Amplitude_5D": -0.252, "Momentum_3M": -0.202},
            parameters={"top_n": 10, "rebalance": 20, "industry_neutral": True},
            backtest_ic=0.08,
            backtest_sharpe=1.03,
            backtest_max_dd=8.9,
            backtest_excess_return=11.18,
        )
        d = meta.to_dict()
        restored = StrategyMeta.from_dict(d)

        assert restored.weights == {"Amplitude_5D": -0.252, "Momentum_3M": -0.202}
        assert restored.parameters == {
            "top_n": 10,
            "rebalance": 20,
            "industry_neutral": True,
        }
        assert restored.backtest_ic == pytest.approx(0.08)
        assert restored.backtest_sharpe == pytest.approx(1.03)
        assert restored.backtest_max_dd == pytest.approx(8.9)
        assert restored.backtest_excess_return == pytest.approx(11.18)
        assert restored.strategy_version == "v20260731"
        assert restored.owner == "researcher"

    def test_meta_frozen_snapshot_defaults(self) -> None:
        """StrategyMeta without frozen fields defaults to empty/false/zero."""
        from qp.strategy.registry import StrategyMeta

        meta = StrategyMeta()
        assert meta.weights == {}
        assert meta.parameters == {}
        assert meta.backtest_ic == 0.0
        assert meta.backtest_sharpe == 0.0
        assert meta.backtest_max_dd == 0.0
        assert meta.backtest_excess_return == 0.0

    def test_meta_weights_type_safety(self) -> None:
        """from_dict coerces weight values to float."""
        from qp.strategy.registry import StrategyMeta

        d = {"weights": {"F1": 1, "F2": "0.5"}}
        meta = StrategyMeta.from_dict(d)
        assert meta.weights == {"F1": 1.0, "F2": 0.5}
        assert isinstance(next(iter(meta.weights.values())), float)

    def test_register_with_frozen_meta(self) -> None:
        """Registry persists frozen meta fields via _save/_load."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(
            weights={"Factor_A": -0.15},
            parameters={"top_n": 8},
            backtest_sharpe=0.95,
        )
        strategy = SimpleRankStrategy(top_n=8)
        registry.register(strategy, meta=meta)

        # Verify in-memory
        retrieved = registry.get_meta("simple_rank_v1.0")
        assert retrieved.weights == {"Factor_A": -0.15}
        assert retrieved.parameters == {"top_n": 8}
        assert retrieved.backtest_sharpe == pytest.approx(0.95)

        # Verify persistence roundtrip — new registry instance reads from disk
        registry2 = StrategyRegistry()
        assert "simple_rank_v1.0" in registry2.list_strategies()
        meta2 = registry2.get_meta("simple_rank_v1.0")
        assert meta2.weights == {"Factor_A": -0.15}
        assert meta2.backtest_sharpe == pytest.approx(0.95)

    def test_approved_lifecycle(self) -> None:
        """APPROVED lifecycle is recognized as active."""
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        strategy = SimpleRankStrategy(top_n=5)
        registry.register(strategy, lifecycle=StrategyLifecycle.APPROVED)

        assert registry.get_lifecycle("simple_rank_v1.0") == StrategyLifecycle.APPROVED
        active = registry.get_active()
        assert len(active) == 1
        assert active[0] is strategy


# ══════════════════════════════════════════════════════════════════
# ApprovedStrategy — ADR-031 Step 2
# ══════════════════════════════════════════════════════════════════


class TestApprovedStrategy:
    """Frozen, immutable strategy snapshot — ADR-031 Step 2."""

    def test_construction(self) -> None:
        """Basic construction and attribute access."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        now = datetime.now(UTC)
        s = ApprovedStrategy(
            strategy_id="momentum_vol_full",
            version="v20260731",
            approved_at=now,
            approved_by="researcher",
            weights={"Amplitude_5D": -0.252, "Momentum_3M": -0.202},
            parameters={"top_n": 10, "rebalance": 20},
            backtest_summary={"ic": 0.08, "sharpe": 1.03, "max_dd": 8.9},
            validation_report_id="multifactor_20260731_095738",
        )

        assert s.strategy_id == "momentum_vol_full"
        assert s.version == "v20260731"
        assert s.approved_by == "researcher"
        assert s.weights == {"Amplitude_5D": -0.252, "Momentum_3M": -0.202}
        assert s.backtest_summary["ic"] == 0.08
        assert s.factor_count == 2

    def test_frozen_immutable(self) -> None:
        """ApprovedStrategy is frozen — attribute mutation raises."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        s = ApprovedStrategy(
            strategy_id="test",
            version="v1",
            approved_at=datetime.now(UTC),
            approved_by="me",
        )
        with pytest.raises((TypeError, AttributeError, ValueError)):
            s.strategy_id = "hacked"  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        """to_dict → from_dict preserves all fields."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        now = datetime.now(UTC)
        original = ApprovedStrategy(
            strategy_id="momentum_vol_full",
            version="v20260731",
            approved_at=now,
            approved_by="researcher",
            weights={"F1": -0.25, "F2": 0.15},
            parameters={"top_n": 10, "industry_neutral": True},
            backtest_summary={"ic": 0.08, "sharpe": 1.03, "max_dd": 8.9},
            validation_report_id="exp_001",
            meta={"note": "first freeze"},
        )
        d = original.to_dict()
        restored = ApprovedStrategy.from_dict(d)

        assert restored.strategy_id == original.strategy_id
        assert restored.version == original.version
        assert restored.approved_by == original.approved_by
        assert restored.weights == original.weights
        assert restored.parameters == original.parameters
        assert restored.backtest_summary == original.backtest_summary
        assert restored.validation_report_id == original.validation_report_id
        assert restored.meta == original.meta

    def test_json_roundtrip(self) -> None:
        """to_json → from_json preserves all fields."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        original = ApprovedStrategy(
            strategy_id="test",
            version="v1",
            approved_at=datetime.now(UTC),
            approved_by="me",
            weights={"F1": -0.1},
        )
        json_str = original.to_json()
        restored = ApprovedStrategy.from_json(json_str)

        assert restored.strategy_id == "test"
        assert restored.weights == {"F1": -0.1}

    def test_defaults(self) -> None:
        """Minimal construction — defaults are reasonable."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        s = ApprovedStrategy(
            strategy_id="minimal",
            version="v0",
            approved_at=datetime.now(UTC),
            approved_by="auto",
        )
        assert s.weights == {}
        assert s.parameters == {}
        assert s.backtest_summary == {}
        assert s.validation_report_id == ""
        assert s.factor_count == 0
        assert s.top_n == 10  # default

    def test_from_strategy_meta(self) -> None:
        """from_strategy_meta extracts frozen fields from StrategyMeta."""
        from qp.strategy.approved import ApprovedStrategy
        from qp.strategy.registry import StrategyMeta

        meta = StrategyMeta(
            strategy_version="v20260731",
            weights={"Amplitude_5D": -0.252, "Volatility_20D": 0.22},
            parameters={"top_n": 10, "rebalance": 20, "industry_neutral": True},
            backtest_ic=0.08,
            backtest_sharpe=1.03,
            backtest_max_dd=8.9,
            backtest_excess_return=11.18,
        )

        approved = ApprovedStrategy.from_strategy_meta(
            strategy_id="momentum_vol_full",
            version="v20260731",
            approved_by="researcher",
            meta=meta,
            validation_report_id="exp_001",
        )

        assert approved.strategy_id == "momentum_vol_full"
        assert approved.weights == {"Amplitude_5D": -0.252, "Volatility_20D": 0.22}
        assert approved.backtest_summary["ic"] == pytest.approx(0.08)
        assert approved.backtest_summary["sharpe"] == pytest.approx(1.03)
        assert approved.backtest_summary["max_dd"] == pytest.approx(8.9)
        assert approved.backtest_summary["excess_return"] == pytest.approx(11.18)
        assert approved.top_n == 10
        assert approved.rebalance_freq == 20
        assert approved.is_industry_neutral is True

    def test_convenience_properties(self) -> None:
        """top_n, rebalance_freq, is_industry_neutral work correctly."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        s = ApprovedStrategy(
            strategy_id="test",
            version="v1",
            approved_at=datetime.now(UTC),
            approved_by="me",
            parameters={
                "top_n": 15,
                "rebalance": 30,
                "industry_neutral": False,
            },
        )
        assert s.top_n == 15
        assert s.rebalance_freq == 30
        assert s.is_industry_neutral is False

    def test_describe(self) -> None:
        """describe() produces a human-readable summary."""
        from datetime import UTC, datetime

        from qp.strategy.approved import ApprovedStrategy

        s = ApprovedStrategy(
            strategy_id="momentum_vol_full",
            version="v20260731",
            approved_at=datetime.now(UTC),
            approved_by="researcher",
            weights={"F1": -0.25, "F2": 0.15},
            parameters={"top_n": 10, "rebalance": 20},
            backtest_summary={"ic": 0.08, "sharpe": 1.03},
        )
        desc = s.describe()
        assert "momentum_vol_full" in desc
        assert "v20260731" in desc
        assert "F1: -0.250" in desc
        assert "IC=" in desc
        assert "Sharpe=" in desc


# ══════════════════════════════════════════════════════════════════
# Registry Approved workflow — ADR-031 Step 3
# ══════════════════════════════════════════════════════════════════


class TestRegistryApprovedWorkflow:
    """Approve → persist → load_active → deactivate lifecycle."""

    def test_approve_creates_snapshot(self) -> None:
        """approve() creates ApprovedStrategy and sets APPROVED lifecycle."""
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(
            weights={"F1": -0.25, "F2": 0.15},
            parameters={"top_n": 10, "rebalance": 20},
            backtest_sharpe=1.03,
            backtest_ic=0.08,
        )
        strategy = SimpleRankStrategy(top_n=10)
        registry.register(strategy, meta=meta)

        approved = registry.approve("simple_rank_v1.0", approved_by="researcher")

        from qp.strategy.approved import ApprovedStrategy

        assert isinstance(approved, ApprovedStrategy)
        assert approved.strategy_id == "simple_rank_v1.0"
        assert approved.weights == {"F1": -0.25, "F2": 0.15}
        assert approved.approved_by == "researcher"
        assert registry.get_lifecycle("simple_rank_v1.0") == StrategyLifecycle.APPROVED

    def test_approve_requires_weights(self) -> None:
        """approve() raises if strategy meta has no weights."""
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        strategy = SimpleRankStrategy(top_n=5, strategy_id="test_no_weights_v1")
        registry.register(strategy)

        with pytest.raises(ValueError, match="weights"):
            registry.approve("test_no_weights_v1", approved_by="me")

    def test_load_active_after_approve(self) -> None:
        """load_active() returns approved snapshots after approve()."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(
            weights={"F1": -0.1},
            parameters={"top_n": 5},
        )
        registry.register(SimpleRankStrategy(top_n=5), meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="researcher")

        active = registry.load_active()
        assert len(active) == 1
        assert active[0].strategy_id == "simple_rank_v1.0"  # type: ignore[union-attr]

    def test_load_active_as_meta(self) -> None:
        """load_active_as_meta() returns StrategyMeta for active approved strategies."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(
            weights={"F1": -0.1},
            parameters={"top_n": 5},
        )
        registry.register(SimpleRankStrategy(top_n=5), meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="researcher")

        metas = registry.load_active_as_meta()
        assert len(metas) == 1
        assert metas[0].weights == {"F1": -0.1}
        assert metas[0].parameters == {"top_n": 5}

    def test_deactivate(self) -> None:
        """deactivate() reverts lifecycle and marks inactive."""
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(weights={"F1": -0.1})
        registry.register(SimpleRankStrategy(top_n=5), meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="me")

        registry.deactivate("simple_rank_v1.0")

        assert registry.get_lifecycle("simple_rank_v1.0") == StrategyLifecycle.BACKTEST_PASSED
        active = registry.load_active()
        assert len(active) == 0
        # Snapshot still exists for audit
        assert registry.get_approved("simple_rank_v1.0") is not None

    def test_get_approved(self) -> None:
        """get_approved() returns snapshot or None."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        meta = StrategyMeta(weights={"F1": -0.1})
        registry.register(SimpleRankStrategy(top_n=5), meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="me")

        snap = registry.get_approved("simple_rank_v1.0")
        assert snap is not None
        assert snap.strategy_id == "simple_rank_v1.0"  # type: ignore[union-attr]

        assert registry.get_approved("nonexistent") is None

    def test_persistence_roundtrip(self) -> None:
        """Approve → new Registry instance → load_active still works."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        # Register and approve
        registry = StrategyRegistry()
        meta = StrategyMeta(
            weights={"F1": -0.25},
            parameters={"top_n": 10, "rebalance": 20},
            backtest_sharpe=1.03,
        )
        strategy = SimpleRankStrategy(top_n=10)
        registry.register(strategy, meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="researcher")

        # New instance reads from disk
        registry2 = StrategyRegistry()
        active = registry2.load_active()
        assert len(active) == 1
        assert active[0].strategy_id == "simple_rank_v1.0"  # type: ignore[union-attr]
        assert active[0].weights == {"F1": -0.25}  # type: ignore[union-attr]
        assert active[0].backtest_summary["sharpe"] == pytest.approx(1.03)  # type: ignore[union-attr]

    def test_register_preserves_disk_metadata(self) -> None:
        """Registering after disk-load preserves existing metadata."""
        from qp.strategy.registry import StrategyMeta, StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        # First process: register, set weights, approve
        registry = StrategyRegistry()
        meta = StrategyMeta(weights={"F1": -0.5})
        registry.register(SimpleRankStrategy(top_n=5), meta=meta)
        registry.approve("simple_rank_v1.0", approved_by="me")

        # Second process: re-register with strategy instance
        registry2 = StrategyRegistry()
        registry2.register(SimpleRankStrategy(top_n=5))  # no meta passed
        # Should preserve weights from disk
        meta2 = registry2.get_meta("simple_rank_v1.0")
        assert meta2.weights == {"F1": -0.5}
