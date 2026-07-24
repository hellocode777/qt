"""Tests for qp.data.adapter.demo_adapter — DemoAdapter (Polars-native)."""

from __future__ import annotations

from datetime import date

import polars as pl

from qp.data.adapter.demo_adapter import DemoAdapter


class TestDemoAdapter:
    def test_dataset_name(self):
        adapter = DemoAdapter()
        assert adapter.dataset_name == "daily_price"

    def test_fetch_raw_default_symbols(self):
        adapter = DemoAdapter()
        df = adapter.fetch_raw(date(2024, 1, 15), date(2024, 1, 19))
        assert not df.is_empty()
        assert "symbol" in df.columns
        assert "日期" in df.columns
        # 15 default symbols × ~5 trading days
        assert df.height >= 15 * 3

    def test_fetch_raw_custom_symbols(self):
        adapter = DemoAdapter()
        df = adapter.fetch_raw(
            date(2024, 1, 15),
            date(2024, 1, 16),
            symbols=["600519", "000858"],
        )
        symbols = df["symbol"].unique().to_list()
        assert "600519" in symbols
        assert "000858" in symbols

    def test_deterministic_output(self):
        """Same inputs produce same outputs (seed 42)."""
        adapter1 = DemoAdapter()
        adapter2 = DemoAdapter()
        df1 = adapter1.fetch_raw(date(2024, 1, 15), date(2024, 1, 19), symbols=["600519"])
        df2 = adapter2.fetch_raw(date(2024, 1, 15), date(2024, 1, 19), symbols=["600519"])
        assert df1["收盘"].to_list() == df2["收盘"].to_list()

    def test_ohlc_values_reasonable(self):
        adapter = DemoAdapter()
        df = adapter.fetch_raw(date(2024, 1, 15), date(2024, 6, 28), symbols=["600519"])
        assert (df["开盘"] > 0).all()
        assert (df["收盘"] > 0).all()
        assert (df["最高"] > 0).all()
        assert (df["最低"] > 0).all()

    def test_volume_positive(self):
        adapter = DemoAdapter()
        df = adapter.fetch_raw(date(2024, 1, 15), date(2024, 1, 19), symbols=["000001"])
        assert (df["成交量"] > 0).all()

    def test_validate_schema_passes(self):
        adapter = DemoAdapter()
        df = adapter.fetch_raw(date(2024, 1, 15), date(2024, 1, 16))
        assert adapter.validate_schema(df) is True

    def test_validate_schema_fails_on_missing_col(self):
        adapter = DemoAdapter()
        bad_df = pl.DataFrame({"wrong_col": [1, 2, 3]})
        assert adapter.validate_schema(bad_df) is False

    def test_weekend_excluded(self):
        adapter = DemoAdapter()
        # 2024-01-13 is Saturday, 2024-01-15 is Monday
        df = adapter.fetch_raw(date(2024, 1, 13), date(2024, 1, 15), symbols=["600519"])
        dates = df["日期"].unique().to_list()
        assert "2024-01-13" not in dates
        assert "2024-01-14" not in dates
        assert "2024-01-15" in dates
