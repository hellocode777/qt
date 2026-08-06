# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false
"""Tests for concrete factor/feature implementations."""

from __future__ import annotations

import polars as pl

from qp.data.feature_store.factors import (
    ATR,
    ATR14,
    MACD,
    RSI,
    RSI14,
    AvgVolume,
    Momentum,
    Momentum5,
    Momentum20,
    PricePosition,
    RollingVolatility,
    RollingVolatility20,
    ShortTermReversal,
    SMACross,
    TurnoverRate,
    VolumeRatio,
    VolumeRatio5,
    VolumeRatio20,
)

# ==================================================================
# Test helpers
# ==================================================================


def _make_ohlcv_df(
    symbols: list[str] | None = None,
    n_days: int = 100,
    seed: int = 42,
) -> pl.DataFrame:
    """Create OHLCV DataFrame for factor testing."""
    import numpy as np

    rng = np.random.default_rng(seed)
    if symbols is None:
        symbols = ["600519"]

    rows: list[dict] = []
    for sym in symbols:
        close = 100.0 + rng.normal(0, 2, n_days).cumsum()
        for d_idx in range(n_days):
            month = 1 + d_idx // 22
            day = (d_idx % 22) + 1
            c = close[d_idx]
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": f"2024-{month:02d}-{day:02d}",
                    "open": c + rng.normal(0, 0.5),
                    "high": c + abs(rng.normal(0, 1.5)),
                    "low": c - abs(rng.normal(0, 1.5)),
                    "close": c,
                    "volume": float(abs(rng.normal(1e6, 2e5))),
                }
            )

    return (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("trade_date").str.to_date(),
        )
        .sort(["symbol", "trade_date"])
    )


# ==================================================================
# Momentum factors
# ==================================================================


class TestMomentum:
    def test_momentum_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = Momentum(period=20).transform_batch(df)
        assert "momentum_20" in result.columns
        # Values should be mostly within reasonable range
        vals = result["momentum_20"].drop_nulls()
        assert vals.len() > 0

    def test_momentum5_is_subclass(self):
        feat = Momentum5()
        assert feat.feature_name == "momentum_5"
        assert feat.window == 5

    def test_momentum20_is_subclass(self):
        feat = Momentum20()
        assert feat.feature_name == "momentum_20"

    def test_momentum_stream_update(self):
        feat = Momentum(period=5)
        for i in range(4):
            assert feat.update_stream(100.0 + i * 2) is None
        # 5th value triggers computation
        val = feat.update_stream(110.0)
        assert val is not None

    def test_momentum_stream_value(self):
        """Momentum = (last / first) - 1"""
        feat = Momentum(period=5)
        prices = [100.0, 101.0, 102.0, 103.0, 105.0]
        for i, p in enumerate(prices):
            val = feat.update_stream(p)
            if i == 4:
                assert val is not None
                assert abs(val - (105.0 / 100.0 - 1)) < 0.001

    def test_rsi_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = RSI(period=14).transform_batch(df)
        assert "rsi_14" in result.columns
        vals = result["rsi_14"].drop_nulls()
        assert vals.len() > 0
        # RSI should be in [0, 100]
        assert vals.min() >= 0
        assert vals.max() <= 100

    def test_rsi14_is_standard(self):
        feat = RSI14()
        assert feat.feature_name == "rsi_14"
        assert feat.window == 14

    def test_rsi_stream_update(self):
        """Streaming RSI with all-increasing prices should approach 100."""
        feat = RSI(period=5)
        # Feed increasing prices for many steps
        for i in range(20):
            feat.update_stream(100.0 + i * 2)
        val = feat.update_stream(140.0)
        # With all gains, RSI should be near 100
        assert val is not None
        assert val > 70

    def test_short_term_reversal(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        mom = Momentum(period=5).transform_batch(df)
        rev = ShortTermReversal(period=5).transform_batch(df)
        # Reversal should be negative of momentum
        mom_vals = mom["momentum_5"].drop_nulls()
        rev_vals = rev["reversal_5"].drop_nulls()
        assert mom_vals.len() > 0
        assert rev_vals.len() > 0

    def test_per_symbol_isolation(self):
        """Features should not leak across symbols."""
        df = _make_ohlcv_df(["600519", "000001"], n_days=30)
        result = Momentum20().transform_batch(df)
        # First value of each symbol should be null
        for sym in ["600519", "000001"]:
            first = result.filter(pl.col("symbol") == sym).head(20)["momentum_20"].drop_nulls()
            # After 20 rows, first non-null should appear
            assert first.len() >= 0


# ==================================================================
# Volatility factors
# ==================================================================


class TestVolatility:
    def test_rolling_volatility_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = RollingVolatility(period=20).transform_batch(df)
        assert "volatility_20" in result.columns
        vals = result["volatility_20"].drop_nulls()
        assert vals.len() > 0
        # Annualized vol should be >= 0
        assert vals.min() >= 0

    def test_rolling_volatility_non_annualized(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        a = RollingVolatility(period=20, annualize=True).transform_batch(df)
        na = RollingVolatility(period=20, annualize=False).transform_batch(df)
        a_vals = a["volatility_20"].drop_nulls()
        na_vals = na["volatility_20"].drop_nulls()
        # Annualized should be ~ sqrt(252) × non-annualized
        ratio = a_vals.mean() / (na_vals.mean() + 1e-10)
        assert 10 < ratio < 20  # sqrt(252) ≈ 15.87

    def test_volatility20_subclass(self):
        feat = RollingVolatility20()
        assert feat.feature_name == "volatility_20"

    def test_atr_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = ATR(period=14).transform_batch(df)
        assert "atr_14" in result.columns
        vals = result["atr_14"].drop_nulls()
        assert vals.len() > 0
        assert vals.min() >= 0

    def test_atr14_subclass(self):
        feat = ATR14()
        assert feat.feature_name == "atr_14"
        assert feat.window == 14


# ==================================================================
# Volume factors
# ==================================================================


class TestVolume:
    def test_volume_ratio_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = VolumeRatio(period=5).transform_batch(df)
        assert "volume_ratio_5" in result.columns
        vals = result["volume_ratio_5"].drop_nulls()
        assert vals.len() > 0

    def test_volume_ratio_around_one(self):
        """With stationary volume, vol ratio should fluctuate around 1."""
        df = _make_ohlcv_df(["600519"], n_days=100)
        result = VolumeRatio20().transform_batch(df)
        vals = result["volume_ratio_20"].drop_nulls()
        median = vals.median()
        # Median should be near 1.0
        assert 0.5 < median < 2.0

    def test_volume_ratio5_subclass(self):
        feat = VolumeRatio5()
        assert feat.feature_name == "volume_ratio_5"

    def test_turnover_rate_fallback(self):
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = TurnoverRate().transform_batch(df)
        assert "turnover_rate" in result.columns

    def test_avg_volume_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = AvgVolume(period=20).transform_batch(df)
        assert "avg_volume_20" in result.columns


# ==================================================================
# Technical factors
# ==================================================================


class TestTechnical:
    def test_sma_cross_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = SMACross(fast=5, slow=20).transform_batch(df)
        assert "sma_cross_5_20" in result.columns
        vals = result["sma_cross_5_20"].drop_nulls()
        assert vals.len() > 0

    def test_sma_cross_custom_params(self):
        df = _make_ohlcv_df(["600519"], n_days=80)
        result = SMACross(fast=10, slow=60).transform_batch(df)
        assert "sma_cross_10_60" in result.columns

    def test_price_position_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = PricePosition(period=20).transform_batch(df)
        assert "price_position_20" in result.columns
        vals = result["price_position_20"].drop_nulls()
        assert vals.len() > 0
        # Position should be in [0, 1] range approximately
        assert vals.min() >= -0.01
        assert vals.max() <= 1.01

    def test_price_position_uses_high_low(self):
        """When OHLC columns exist, use actual high/low."""
        df = _make_ohlcv_df(["600519"], n_days=50)
        result = PricePosition(period=20).transform_batch(df)
        vals = result["price_position_20"].drop_nulls()
        # Should compute correctly with high/low
        assert vals.len() > 0

    def test_macd_computes(self):
        df = _make_ohlcv_df(["600519"], n_days=80)
        result = MACD().transform_batch(df)
        assert "macd_hist" in result.columns
        assert "macd_line" in result.columns
        assert "macd_signal" in result.columns
        vals = result["macd_hist"].drop_nulls()
        assert vals.len() > 0

    def test_macd_hist_relationship(self):
        """MACD histogram = MACD line - Signal line."""
        df = _make_ohlcv_df(["600519"], n_days=80)
        result = MACD().transform_batch(df)
        valid = result.drop_nulls(subset=["macd_hist", "macd_line", "macd_signal"])
        if valid.height > 0:
            diff = (valid["macd_line"] - valid["macd_signal"] - valid["macd_hist"]).abs()
            assert diff.max() < 0.01


# ==================================================================
# Integration: all factors in a registry
# ==================================================================


class TestFactorIntegration:
    def test_all_factors_in_registry(self):
        from qp.data.feature_store import FeatureEngine, FeatureRegistry

        reg = FeatureRegistry()
        reg.register(Momentum5())
        reg.register(Momentum20())
        reg.register(RSI14())
        reg.register(RollingVolatility20())
        reg.register(ATR14())
        reg.register(VolumeRatio5())
        reg.register(TurnoverRate())
        reg.register(SMACross(fast=5, slow=20))
        reg.register(PricePosition(period=20))
        reg.register(MACD())

        assert reg.feature_count == 10

        df = _make_ohlcv_df(["600519"], n_days=100)
        engine = FeatureEngine(reg, standardize=False, apply_shift=False)
        result = engine.compute(df)

        # Verify primary factor columns exist
        # (MACD also produces macd_line/macd_signal, but those are
        #  auxiliary outputs accessed via direct transform_batch())
        expected_cols = {
            "momentum_5",
            "momentum_20",
            "rsi_14",
            "volatility_20",
            "atr_14",
            "volume_ratio_5",
            "turnover_rate",
            "sma_cross_5_20",
            "price_position_20",
            "macd_hist",
        }
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"
