"""Tests for qp.data.timestamp — dual-timestamp annotation."""

from __future__ import annotations

import pandas as pd
import polars as pl

from qp.data.timestamp import (
    _detect_date_column,
    _ingestion_now,
    annotate_timestamps_pd,
    annotate_timestamps_pl,
)

# ---------------------------------------------------------------------------
# _detect_date_column
# ---------------------------------------------------------------------------


class TestDetectDateColumn:
    def test_english_column(self):
        assert _detect_date_column(["symbol", "trade_date", "close"]) == "trade_date"

    def test_chinese_column(self):
        assert _detect_date_column(["symbol", "日期", "收盘"]) == "日期"

    def test_both_columns_prefers_english(self):
        assert _detect_date_column(["日期", "trade_date"]) == "trade_date"

    def test_no_date_column(self):
        assert _detect_date_column(["symbol", "close"]) is None

    def test_empty_list(self):
        assert _detect_date_column([]) is None


# ---------------------------------------------------------------------------
# _ingestion_now
# ---------------------------------------------------------------------------


class TestIngestionNow:
    def test_returns_iso_8601_string(self):
        ts = _ingestion_now()
        assert isinstance(ts, str)
        # Should end with +00:00 (UTC timezone marker)
        assert "+00:00" in ts

    def test_returns_reasonable_length(self):
        """Two calls each return a sensible ISO 8601 timestamp."""
        ts1 = _ingestion_now()
        ts2 = _ingestion_now()
        assert len(ts1) > 20  # sensible minimum ISO length
        assert len(ts2) > 20


# ---------------------------------------------------------------------------
# annotate_timestamps_pl
# ---------------------------------------------------------------------------


class TestAnnotateTimestampsPL:
    def test_basic_polars_dataframe(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16", "2024-01-17"],
                "symbol": ["000001", "000001", "000001"],
                "close": [10.5, 10.8, 10.3],
            }
        )
        result = annotate_timestamps_pl(df)

        assert "source_event_time" in result.columns
        assert "ingestion_received_time" in result.columns
        assert result.height == 3

        # source_event_time format: YYYY-MM-DDT15:00:00+08:00
        assert result["source_event_time"][0] == "2024-01-15T15:00:00+08:00"
        assert result["source_event_time"][1] == "2024-01-16T15:00:00+08:00"

        # ingestion_received_time: all rows same batch timestamp
        ingestion_ts = result["ingestion_received_time"][0]
        assert result["ingestion_received_time"][1] == ingestion_ts
        assert result["ingestion_received_time"][2] == ingestion_ts

    def test_explicit_ingestion_time(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-06-01"],
                "symbol": ["600519"],
                "close": [1500.0],
            }
        )
        result = annotate_timestamps_pl(df, ingestion_time="2024-06-01T08:30:00.123456+00:00")

        assert result["ingestion_received_time"][0] == "2024-06-01T08:30:00.123456+00:00"
        assert result["source_event_time"][0] == "2024-06-01T15:00:00+08:00"

    def test_chinese_date_column(self):
        """Timestamp annotator handles Chinese column name 日期."""
        df = pl.DataFrame(
            {
                "日期": ["2024-03-20"],
                "symbol": ["000001"],
                "收盘": [12.5],
            }
        )
        result = annotate_timestamps_pl(df)

        assert "source_event_time" in result.columns
        assert result["source_event_time"][0] == "2024-03-20T15:00:00+08:00"

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "close": pl.Float64})
        result = annotate_timestamps_pl(df.clear())

        assert result.is_empty()
        assert "source_event_time" in result.columns
        assert "ingestion_received_time" in result.columns

    def test_no_date_column(self):
        df = pl.DataFrame({"symbol": ["000001"], "close": [10.0]})
        result = annotate_timestamps_pl(df)

        assert result["source_event_time"][0] == ""
        assert result["ingestion_received_time"][0] != ""

    def test_original_columns_preserved(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "symbol": ["000001"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000000.0],
            }
        )
        result = annotate_timestamps_pl(df)

        for col in ["trade_date", "symbol", "open", "high", "low", "close", "volume"]:
            assert col in result.columns, f"Original column {col} should be preserved"


# ---------------------------------------------------------------------------
# annotate_timestamps_pd
# ---------------------------------------------------------------------------


class TestAnnotateTimestampsPD:
    def test_basic_pandas_dataframe(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "symbol": ["000001", "000001"],
                "close": [10.5, 10.8],
            }
        )
        result = annotate_timestamps_pd(df)

        assert "source_event_time" in result.columns
        assert "ingestion_received_time" in result.columns
        assert len(result) == 2

        assert result.loc[0, "source_event_time"] == "2024-01-15T15:00:00+08:00"
        assert result.loc[1, "source_event_time"] == "2024-01-16T15:00:00+08:00"

        # Same ingestion timestamp for all rows in the batch
        assert result.loc[0, "ingestion_received_time"] == result.loc[1, "ingestion_received_time"]

    def test_explicit_ingestion_time(self):
        df = pd.DataFrame({"trade_date": ["2024-06-01"], "symbol": ["600519"], "close": [1500.0]})
        result = annotate_timestamps_pd(df, ingestion_time="2024-06-01T08:30:00.000000+00:00")

        assert result.loc[0, "ingestion_received_time"] == "2024-06-01T08:30:00.000000+00:00"

    def test_original_df_not_mutated(self):
        df = pd.DataFrame({"trade_date": ["2024-01-15"], "symbol": ["000001"], "close": [10.5]})
        original_cols = set(df.columns)
        _result = annotate_timestamps_pd(df)

        # Original df should be unchanged
        assert set(df.columns) == original_cols

    def test_chinese_date_column(self):
        df = pd.DataFrame(
            {
                "日期": ["2024-03-20"],
                "symbol": ["000001"],
                "收盘": [12.5],
            }
        )
        result = annotate_timestamps_pd(df)

        assert "source_event_time" in result.columns
        assert result.loc[0, "source_event_time"] == "2024-03-20T15:00:00+08:00"

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["trade_date", "symbol", "close"])
        result = annotate_timestamps_pd(df)

        assert result.empty
        assert "source_event_time" in result.columns
        assert "ingestion_received_time" in result.columns
