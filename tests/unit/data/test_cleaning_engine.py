"""Tests for qp.data.cleaning.engine — CleaningEngine (Polars-native)."""

from __future__ import annotations

import pandas as pd
import polars as pl

from qp.data.cleaning.engine import CleaningEngine

# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------


class TestColumnMapping:
    def test_all_known_columns_mapped(self):
        df = pl.DataFrame(
            {
                "日期": ["2024-01-15"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.5],
                "成交量": [1000000.0],
                "成交额": [10500000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert "trade_date" in result.columns
        assert "open" in result.columns
        assert "close" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "volume" in result.columns
        assert "amount" in result.columns
        assert "日期" not in result.columns

    def test_already_english_columns_pass_through(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "volume": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert "trade_date" in result.columns
        assert "open" in result.columns


# ---------------------------------------------------------------------------
# Type conversion
# ---------------------------------------------------------------------------


class TestTypeConversion:
    def test_trade_date_converted_to_date(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "volume": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result["trade_date"].dtype.is_temporal()

    def test_numeric_coerced_to_float(self):
        df = pl.DataFrame(
            {
                "日期": ["2024-01-15"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.5],
                "成交量": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result["open"].dtype == pl.Float64
        assert result["volume"].dtype == pl.Float64


# ---------------------------------------------------------------------------
# Suspension marking
# ---------------------------------------------------------------------------


class TestSuspensionMarking:
    def test_zero_volume_is_suspended(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [10.0, 10.5],
                "close": [10.5, 10.3],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "volume": [0.0, 800000.0],
                "symbol": ["000001", "000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result["is_suspended"][0] is True
        assert result["is_suspended"][1] is False

    def test_negative_volume_is_suspended(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "volume": [-1.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result["is_suspended"][0] is True


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_sorted_by_symbol_then_date(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-16", "2024-01-15", "2024-01-16", "2024-01-15"],
                "open": [10.5, 10.0, 20.5, 20.0],
                "close": [10.3, 10.5, 20.3, 20.5],
                "high": [10.8, 11.0, 21.0, 21.5],
                "low": [10.0, 9.5, 20.0, 19.5],
                "volume": [800000.0, 1000000.0, 500000.0, 600000.0],
                "symbol": ["000002", "000002", "000001", "000001"],
            },
        )
        result = CleaningEngine().clean(df)
        symbols = result["symbol"].to_list()
        assert symbols == ["000001", "000001", "000002", "000002"]


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------


class TestNaNHandling:
    def test_nan_close_dropped(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [None, 10.5],
                "close": [None, 10.3],
                "high": [None, 10.8],
                "low": [None, 10.0],
                "volume": [1000000.0, 800000.0],
                "symbol": ["000001", "000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result.height == 1
        assert result["symbol"][0] == "000001"


# ---------------------------------------------------------------------------
# Empty DataFrame
# ---------------------------------------------------------------------------


class TestEmptyDataFrame:
    def test_empty_df_returns_empty(self):
        df = pl.DataFrame(
            schema={
                "trade_date": pl.Utf8, "open": pl.Float64, "close": pl.Float64,
                "high": pl.Float64, "low": pl.Float64, "volume": pl.Float64,
                "symbol": pl.Utf8,
            },
        ).clear()
        result = CleaningEngine().clean(df)
        assert result.is_empty()

    def test_empty_after_dropna(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [None],
                "close": [None],
                "high": [None],
                "low": [None],
                "volume": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert result.height == 0


# ---------------------------------------------------------------------------
# Pandas backward compatibility
# ---------------------------------------------------------------------------


class TestPandasCompatibility:
    def test_accepts_pandas_dataframe(self):
        """CleaningEngine.clean() accepts Pandas DataFrames and returns Polars."""
        df = pd.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "close": [10.5],
                "high": [11.0],
                "low": [9.5],
                "volume": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert isinstance(result, pl.DataFrame)
        assert result.height == 1

    def test_accepts_pandas_chinese_columns(self):
        df = pd.DataFrame(
            {
                "日期": ["2024-01-15"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.5],
                "成交量": [1000000.0],
                "symbol": ["000001"],
            },
        )
        result = CleaningEngine().clean(df)
        assert "trade_date" in result.columns
        assert result["open"][0] == 10.0
