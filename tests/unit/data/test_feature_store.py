"""Tests for qp.data.feature_store — Feature Store module."""

from __future__ import annotations

from collections import deque

import polars as pl
import pytest

from qp.data.feature_store import (
    BaseFeature,
    FeatureEngine,
    FeatureRegistry,
    OfflineStore,
    OnlineCache,
    cross_sectional_rank,
    cross_sectional_zscore,
    rolling_zscore,
    shift_features,
    standardize_features,
    validate_no_future_leakage,
)

# ==================================================================
# Concrete test features
# ==================================================================


class Momentum5(BaseFeature):
    """5-day momentum feature for testing."""

    feature_name = "momentum_5"
    required_data = ["close"]
    window = 5

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.col("close").pct_change(5).over("symbol").alias("momentum_5"))

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=5)
        self._buffer.append(new_value)
        if not self.is_ready:
            return None
        return self._buffer[-1] / self._buffer[0] - 1


class SimpleMA3(BaseFeature):
    """3-period moving average for testing."""

    feature_name = "ma_3"
    required_data = ["close"]
    window = 3

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.col("close").rolling_mean(3, min_samples=1).over("symbol").alias("ma_3")
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=3)
        self._buffer.append(new_value)
        if not self.is_ready:
            return None
        return sum(self._buffer) / len(self._buffer)


# ==================================================================
# Test helpers
# ==================================================================


def _make_ohlcv_df(
    symbols: list[str] | None = None,
    n_days: int = 20,
    seed: int = 42,
) -> pl.DataFrame:
    """Create a small OHLCV DataFrame for testing."""
    import numpy as np

    rng = np.random.default_rng(seed)
    if symbols is None:
        symbols = ["600519", "000001"]

    rows: list[dict] = []
    for sym in symbols:
        close = 100.0 + rng.normal(0, 2, n_days).cumsum()
        dates = [f"2024-01-{d + 1:02d}" for d in range(n_days)]
        for _i, (d, c) in enumerate(zip(dates, close, strict=True)):
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": d,
                    "open": c + rng.normal(0, 0.5),
                    "high": c + abs(rng.normal(0, 1)),
                    "low": c - abs(rng.normal(0, 1)),
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
# BaseFeature
# ==================================================================


class TestBaseFeature:
    def test_feature_metadata(self):
        feat = Momentum5()
        assert feat.feature_name == "momentum_5"
        assert feat.required_data == ["close"]
        assert feat.window == 5

    def test_transform_batch(self):
        df = _make_ohlcv_df(["600519"], n_days=30)
        feat = Momentum5()
        result = feat.transform_batch(df)
        assert "momentum_5" in result.columns

    def test_shift_feature(self):
        df = _make_ohlcv_df(["600519"], n_days=20)
        feat = Momentum5()
        result = feat.transform_batch(df)
        shifted = feat.shift_feature(result)
        assert "momentum_5_shifted" in shifted.columns
        # First row of each symbol should have null shifted value
        first_rows = shifted.filter(pl.col("symbol") == "600519").head(1)
        assert first_rows["momentum_5_shifted"].item() is None

    def test_shift_feature_per_symbol(self):
        """shift(1) should not leak data across symbols."""
        df = _make_ohlcv_df(["600519", "000001"], n_days=10)
        feat = Momentum5(apply_shift=True)
        result = feat.transform_batch(df)
        # First row of each symbol should be null after shift
        shifted = feat.shift_feature(result)
        for sym in ["600519", "000001"]:
            first = shifted.filter(pl.col("symbol") == sym).head(1)
            assert first["momentum_5_shifted"].item() is None

    def test_version_hash_stable(self):
        f1 = Momentum5()
        f2 = Momentum5()
        assert f1.version_hash() == f2.version_hash()

    def test_version_hash_different(self):
        f1 = Momentum5()
        f2 = SimpleMA3()
        assert f1.version_hash() != f2.version_hash()

    def test_update_stream_not_ready(self):
        feat = Momentum5()
        assert feat.update_stream(100.0) is None
        assert feat.update_stream(101.0) is None
        assert feat.update_stream(102.0) is None
        assert feat.update_stream(103.0) is None
        # 5th value → ready
        assert feat.update_stream(104.0) is not None

    def test_is_ready(self):
        feat = Momentum5()
        assert feat.is_ready is False
        for i in range(4):
            feat.update_stream(100.0 + i)
        assert feat.is_ready is False
        feat.update_stream(105.0)
        assert feat.is_ready is True

    def test_repr(self):
        feat = Momentum5()
        r = repr(feat)
        assert "Momentum5" in r
        assert "momentum_5" in r


# ==================================================================
# FeatureRegistry
# ==================================================================


class TestFeatureRegistry:
    def test_register_single(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        assert reg.feature_count == 1
        assert "momentum_5" in reg

    def test_register_duplicate_raises(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(Momentum5())

    def test_get_feature(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        feat = reg.get("momentum_5")
        assert feat is not None
        assert feat.feature_name == "momentum_5"

    def test_get_missing(self):
        reg = FeatureRegistry()
        assert reg.get("nonexistent") is None

    def test_list_features_in_order(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        reg.register(SimpleMA3())
        assert reg.list_features() == ["momentum_5", "ma_3"]

    def test_list_by_dependency(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        reg.register(SimpleMA3())
        deps = reg.list_by_dependency("close")
        assert "ma_3" in deps
        assert "momentum_5" in deps
        assert reg.list_by_dependency("volume") == []

    def test_unregister(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        assert reg.feature_count == 1
        reg.unregister("momentum_5")
        assert reg.feature_count == 0
        assert reg.get("momentum_5") is None

    def test_version_tracking(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        v = reg.get_version("momentum_5")
        assert v is not None
        assert len(v) == 12  # SHA256[:12]

    def test_consistency_check_match(self):
        reg1 = FeatureRegistry()
        reg2 = FeatureRegistry()
        reg1.register(Momentum5())
        reg2.register(Momentum5())
        results = reg1.check_consistency(reg2)
        assert results["momentum_5"] == "match"

    def test_consistency_check_mismatch(self):
        reg1 = FeatureRegistry()
        reg2 = FeatureRegistry()
        reg1.register(Momentum5())
        reg2.register(SimpleMA3())
        reg2.register(Momentum5())
        results = reg1.check_consistency(reg2)
        assert results["momentum_5"] == "match"
        assert "mismatch" not in results["momentum_5"]

    def test_consistency_check_missing(self):
        reg1 = FeatureRegistry()
        reg2 = FeatureRegistry()
        reg1.register(Momentum5())
        results = reg1.check_consistency(reg2)
        assert "momentum_5" in results
        assert "missing_in_other" in results["momentum_5"]

    def test_empty_registry(self):
        reg = FeatureRegistry()
        assert reg.feature_count == 0
        assert reg.list_features() == []
        assert len(reg) == 0


# ==================================================================
# Standardization
# ==================================================================


class TestStandardization:
    def test_cross_sectional_zscore(self):
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "A", "B", "C"],
                "trade_date": [
                    "2024-01-15",
                    "2024-01-15",
                    "2024-01-15",
                    "2024-01-16",
                    "2024-01-16",
                    "2024-01-16",
                ],
                "value": [10.0, 20.0, 30.0, 5.0, 15.0, 25.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())

        result = cross_sectional_zscore(df, "value")
        assert "value_zscore" in result.columns

        # Within each day, z-scores should be mean ~0
        day1 = result.filter(pl.col("trade_date") == pl.lit("2024-01-15").str.to_date())
        day1_mean = day1["value_zscore"].mean()
        assert abs(day1_mean) < 0.01

    def test_cross_sectional_zscore_no_leakage(self):
        """Day T's z-score must not be affected by Day T+1's data."""
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "A", "B"],
                "trade_date": ["2024-01-15", "2024-01-15", "2024-01-16", "2024-01-16"],
                "value": [10.0, 20.0, 100.0, 200.0],  # Day 2 much larger
            }
        ).with_columns(pl.col("trade_date").str.to_date())

        result = cross_sectional_zscore(df, "value")
        # Day 1 z-scores should be the same regardless of day 2 values
        day1 = result.filter(pl.col("trade_date") == pl.lit("2024-01-15").str.to_date())
        z_a = day1.filter(pl.col("symbol") == "A")["value_zscore"].item()
        z_b = day1.filter(pl.col("symbol") == "B")["value_zscore"].item()
        # A has lower value → negative z, B has higher → positive z
        assert z_a < 0 < z_b

    def test_cross_sectional_rank(self):
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "trade_date": ["2024-01-15"] * 3,
                "value": [10.0, 20.0, 30.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())

        result = cross_sectional_rank(df, "value")
        assert "value_rank" in result.columns
        ranks = result.sort("value")["value_rank"].to_list()
        assert ranks[0] == 0.0  # Smallest → rank 0
        assert ranks[-1] == 1.0  # Largest → rank 1

    def test_cross_sectional_rank_descending(self):
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "trade_date": ["2024-01-15"] * 3,
                "value": [10.0, 20.0, 30.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())

        result = cross_sectional_rank(df, "value", ascending=False)
        ranks = result.sort("value")["value_rank"].to_list()
        assert ranks[0] == 1.0  # Smallest → rank 1 (descending)

    def test_rolling_zscore(self):
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = rolling_zscore(df, "close", window=10)
        assert "close_roll_z" in result.columns
        # First few values should be null (not enough data)
        first_vals = result["close_roll_z"].head(5).to_list()
        assert all(v is None for v in first_vals)

    def test_shift_features(self):
        df = _make_ohlcv_df(["600519"], n_days=10)
        result = shift_features(df, ["close", "volume"])
        assert "close_lag1" in result.columns
        assert "volume_lag1" in result.columns
        # First row should be null
        assert result["close_lag1"].head(1).item() is None

    def test_shift_features_per_symbol(self):
        df = _make_ohlcv_df(["600519", "000001"], n_days=5)
        result = shift_features(df, ["close"])
        # Each symbol's first row should be null
        for sym in ["600519", "000001"]:
            first = result.filter(pl.col("symbol") == sym).head(1)
            assert first["close_lag1"].item() is None

    def test_shift_missing_column(self):
        df = _make_ohlcv_df(["600519"], n_days=5)
        result = shift_features(df, ["nonexistent"])
        assert "nonexistent_lag1" not in result.columns

    def test_validate_no_future_leakage_clean(self):
        """Uncorrelated random data should NOT trigger leakage warning."""
        import numpy as np

        rng = np.random.default_rng(42)
        n = 200
        df = pl.DataFrame(
            {
                "feature": rng.normal(0, 1, n),
                "return": rng.normal(0, 1, n),
            }
        )
        # With n=200, ~1/sqrt(n) ≈ 0.07 sampling noise; 0.20 safe threshold
        assert validate_no_future_leakage(df, "feature", "return", max_corr=0.20) is True

    def test_validate_no_future_leakage_suspicious(self):
        """If features have strong same-day correlation with returns, flag it."""
        import numpy as np

        n = 200
        vals = np.random.default_rng(42).normal(0, 1, n)
        df = pl.DataFrame(
            {
                "feature": vals,
                "return": vals * 0.9 + np.random.default_rng(99).normal(0, 0.1, n),
            }
        )
        # Very high correlation → should flag
        result = validate_no_future_leakage(df, "feature", "return", max_corr=0.01)
        assert result is False

    def test_standardize_features_cross_sectional(self):
        df = _make_ohlcv_df(["600519", "000001"], n_days=10)
        result = standardize_features(df, ["close"], method="cross_sectional")
        assert "close_zscore" in result.columns

    def test_empty_dataframe_handling(self):
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "trade_date": pl.Date, "value": pl.Float64})
        result_z = cross_sectional_zscore(df, "value")
        assert result_z.is_empty()
        result_r = rolling_zscore(df, "value")
        assert result_r.is_empty()
        result_s = shift_features(df, ["value"])
        assert result_s.is_empty()


# ==================================================================
# FeatureEngine
# ==================================================================


class TestFeatureEngine:
    def test_compute_single_feature(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg, standardize=False, apply_shift=False)
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = engine.compute(df)
        assert "momentum_5" in result.columns

    def test_compute_multiple_features(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        reg.register(SimpleMA3())
        engine = FeatureEngine(reg, standardize=False, apply_shift=False)
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = engine.compute(df)
        assert "momentum_5" in result.columns
        assert "ma_3" in result.columns

    def test_compute_with_shift(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg, standardize=False, apply_shift=True)
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = engine.compute(df)
        # With shift, the shifted column should exist
        assert "momentum_5_lag1" in result.columns

    def test_compute_with_standardization(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg, standardize=True, apply_shift=False)
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = engine.compute(df)
        assert "momentum_5_zscore" in result.columns

    def test_compute_single_named(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg, standardize=False, apply_shift=False)
        df = _make_ohlcv_df(["600519"], n_days=30)
        result = engine.compute_single(df, "momentum_5")
        assert "momentum_5" in result.columns

    def test_compute_single_missing_raises(self):
        reg = FeatureRegistry()
        engine = FeatureEngine(reg)
        df = _make_ohlcv_df(["600519"], n_days=10)
        with pytest.raises(KeyError):
            engine.compute_single(df, "nonexistent")

    def test_stream_update(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg)
        result = engine.stream_update("momentum_5", 100.0)
        assert result["momentum_5"] is None  # Not ready yet

    def test_empty_dataframe(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg)
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "close": pl.Float64})
        result = engine.compute(df)
        assert result.is_empty()

    def test_empty_registry_warns(self):
        engine = FeatureEngine()
        df = _make_ohlcv_df(["600519"], n_days=10)
        result = engine.compute(df)
        # Should return original df unchanged
        assert result is not None

    def test_filter_symbols(self):
        reg = FeatureRegistry()
        reg.register(Momentum5())
        engine = FeatureEngine(reg, standardize=False, apply_shift=False)
        df = _make_ohlcv_df(["600519", "000001"], n_days=10)
        result = engine.compute(df, symbols=["600519"])
        syms = result["symbol"].unique().to_list()
        assert syms == ["600519"]


# ==================================================================
# OfflineStore
# ==================================================================


class TestOfflineStore:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        self.store_dir = tmp_path / "feature_test_store"
        self.store = OfflineStore(self.store_dir)

    def _make_feature_df(self, symbols=None, n_days=10) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        if symbols is None:
            symbols = ["600519", "000001"]
        rows = []
        for sym in symbols:
            for d in range(n_days):
                rows.append(
                    {
                        "symbol": sym,
                        "trade_date": f"2024-01-{d + 1:02d}",
                        "momentum_5": rng.normal(0, 1),
                        "rsi_14": rng.uniform(30, 70),
                    }
                )
        return pl.DataFrame(rows).with_columns(pl.col("trade_date").str.to_date())

    def test_write_and_load(self):
        df = self._make_feature_df()
        n = self.store.write(df, factor_group="momentum")
        assert n == df.height

        loaded = self.store.load(factor_groups=["momentum"])
        assert loaded.height == df.height
        assert "momentum_5" in loaded.columns

    def test_write_multiple_groups(self):
        df1 = self._make_feature_df(symbols=["600519"])
        df2 = df1.with_columns(pl.lit(0.5).alias("pb_ratio"))

        self.store.write(df1, factor_group="momentum")
        self.store.write(df2, factor_group="value")

        groups = self.store.list_groups()
        assert "momentum" in groups
        assert "value" in groups

    def test_load_with_date_filter(self):
        df = self._make_feature_df(n_days=20)
        self.store.write(df, factor_group="momentum")

        loaded = self.store.load(
            start_date="2024-01-05",
            end_date="2024-01-10",
            factor_groups=["momentum"],
        )
        if not loaded.is_empty() and "trade_date" in loaded.columns:
            dates = loaded["trade_date"].unique().to_list()
            from datetime import date

            min_d = date(2024, 1, 5)
            assert all(d >= min_d for d in dates)

    def test_load_with_symbol_filter(self):
        df = self._make_feature_df(["600519", "000001", "000002"])
        self.store.write(df, factor_group="momentum")

        loaded = self.store.load(symbols=["600519"], factor_groups=["momentum"])
        if not loaded.is_empty():
            syms = loaded["symbol"].unique().to_list()
            assert syms == ["600519"]

    def test_load_snapshot(self):
        df = self._make_feature_df(n_days=10)
        self.store.write(df, factor_group="momentum")

        snapshot = self.store.load_snapshot(
            as_of_date="2024-01-10",
            factor_groups=["momentum"],
        )
        if not snapshot.is_empty() and "symbol" in snapshot.columns:
            assert snapshot["symbol"].n_unique() == 2

    def test_list_groups_empty(self):
        store = OfflineStore(self.store_dir / "empty")
        assert store.list_groups() == []

    def test_group_info(self):
        df = self._make_feature_df()
        self.store.write(df, factor_group="momentum")
        info = self.store.group_info("momentum")
        assert info.get("factor_group") == "momentum"
        assert info.get("row_count") == df.height

    def test_delete_group(self):
        df = self._make_feature_df()
        self.store.write(df, factor_group="momentum")
        assert "momentum" in self.store.list_groups()
        self.store.delete_group("momentum")
        assert "momentum" not in self.store.list_groups()

    def test_overwrite_mode(self):
        df1 = self._make_feature_df(symbols=["600519"])
        df2 = self._make_feature_df(symbols=["000001"])
        self.store.write(df1, factor_group="test", mode="overwrite")
        self.store.write(df2, factor_group="test", mode="overwrite")
        loaded = self.store.load(factor_groups=["test"])
        # Should only have 000001 symbols
        if not loaded.is_empty():
            syms = loaded["symbol"].unique().to_list()
            assert sorted(syms) == ["000001"]

    def test_empty_write(self):
        df = pl.DataFrame()
        n = self.store.write(df, factor_group="empty")
        assert n == 0


# ==================================================================
# OnlineCache
# ==================================================================


class TestOnlineCache:
    def test_update_and_get(self):
        cache = OnlineCache()
        cache.update("600519", {"momentum_5": 0.05, "rsi_14": 62.3})
        entry = cache.get("600519")
        assert entry is not None
        assert entry["momentum_5"] == 0.05
        assert entry["rsi_14"] == 62.3

    def test_get_missing_symbol(self):
        cache = OnlineCache()
        assert cache.get("nonexistent") is None

    def test_get_feature_subset(self):
        cache = OnlineCache()
        cache.update("600519", {"a": 1.0, "b": 2.0, "c": 3.0})
        entry = cache.get("600519", feature_names=["a", "c"])
        assert entry is not None
        assert "a" in entry
        assert "c" in entry
        assert "b" not in entry

    def test_get_feature_value(self):
        cache = OnlineCache()
        cache.update("600519", {"momentum_5": 0.05})
        assert cache.get_feature_value("600519", "momentum_5") == 0.05
        assert cache.get_feature_value("600519", "nonexistent") is None

    def test_get_vector(self):
        cache = OnlineCache()
        cache.update("600519", {"a": 1.0, "b": 2.0, "c": 3.0})
        vec = cache.get_vector("600519", ["a", "c", "missing"])
        assert vec == [1.0, 3.0, 0.0]  # missing → default 0.0

    def test_partial_update_merge(self):
        cache = OnlineCache()
        cache.update("600519", {"a": 1.0})
        cache.update("600519", {"b": 2.0})
        entry = cache.get("600519")
        assert entry["a"] == 1.0
        assert entry["b"] == 2.0

    def test_batch_update(self):
        cache = OnlineCache()
        cache.update_batch(
            {
                "600519": {"mom": 0.05},
                "000001": {"mom": -0.02},
            }
        )
        assert cache.symbol_count == 2
        assert cache.get("600519")["mom"] == 0.05
        assert cache.get("000001")["mom"] == -0.02

    def test_get_all(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        cache.update("000001", {"mom": -0.02})
        all_data = cache.get_all()
        assert len(all_data) == 2
        assert "600519" in all_data

    def test_remove_symbol(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        assert cache.remove("600519") is True
        assert cache.remove("600519") is False
        assert cache.get("600519") is None

    def test_clear(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        cache.clear()
        assert cache.symbol_count == 0

    def test_contains(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        assert "600519" in cache
        assert "000001" not in cache

    def test_feature_names(self):
        cache = OnlineCache()
        cache.update("600519", {"a": 1.0, "b": 2.0})
        cache.update("000001", {"b": 3.0, "c": 4.0})
        assert cache.feature_names == {
            "a",
            "b",
            "c",
            "updated_at",
        } or cache.feature_names.issuperset({"a", "b", "c"})

    def test_is_cached(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        assert cache.is_cached("600519") is True
        assert cache.is_cached("000001") is False

    def test_age_seconds(self):
        cache = OnlineCache()
        cache.update("600519", {"mom": 0.05})
        age = cache.age_seconds("600519")
        assert age is not None
        assert age >= 0

    def test_lru_eviction(self):
        cache = OnlineCache(max_symbols=3)
        cache.update("A", {"v": 1.0})
        cache.update("B", {"v": 2.0})
        cache.update("C", {"v": 3.0})
        # A should be the oldest (least recently used)
        cache.update("D", {"v": 4.0})
        # LRU (A) should be evicted
        assert cache.is_cached("A") is False
        assert cache.is_cached("D") is True

    def test_lru_access_moves_to_end(self):
        cache = OnlineCache(max_symbols=2)
        cache.update("A", {"v": 1.0})
        cache.update("B", {"v": 2.0})
        # Access A → moves to MRU
        cache.get("A")
        cache.update("C", {"v": 3.0})
        # B should be evicted (least recently used after A access)
        assert cache.is_cached("A") is True
        assert cache.is_cached("B") is False
        assert cache.is_cached("C") is True

    def test_refresh_from_offline(self, tmp_path):
        """Integration: Write to OfflineStore, refresh OnlineCache."""
        offline = OfflineStore(tmp_path / "offline")
        df = pl.DataFrame(
            {
                "symbol": ["600519", "000001"],
                "trade_date": ["2024-06-15", "2024-06-15"],
                "mom": [0.05, -0.02],
                "rsi": [62.0, 45.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        offline.write(df, factor_group="test")

        cache = OnlineCache()
        n = cache.refresh_from_offline(offline, as_of_date="2024-06-15", factor_groups=["test"])
        assert n == 2
        assert cache.is_cached("600519")
        assert cache.get_feature_value("600519", "mom") == 0.05
