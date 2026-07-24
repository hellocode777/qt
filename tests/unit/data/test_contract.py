"""Tests for qp.data.contract.daily_price — DailyPriceContract."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qp.data.contract.daily_price import DailyPriceContract


class TestSchemaDefinition:
    def test_required_columns(self):
        assert "trade_date" in DailyPriceContract.schema
        assert "symbol" in DailyPriceContract.schema
        assert "close" in DailyPriceContract.schema
        assert "volume" in DailyPriceContract.schema

    def test_optional_schema(self):
        """Timestamp columns are in optional_schema, not required."""
        assert "source_event_time" in DailyPriceContract.optional_schema
        assert "ingestion_received_time" in DailyPriceContract.optional_schema

    def test_primary_key(self):
        assert DailyPriceContract.primary_key == ["trade_date", "symbol"]

    def test_name_and_owner(self):
        assert DailyPriceContract.name == "daily_price"
        assert DailyPriceContract.owner == "data-layer"


class TestValidate:
    def test_valid_dataframe(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2024-01-15", "2024-01-16"]),
                "symbol": ["000001", "000001"],
                "open": [10.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
                "volume": [1000000.0, 800000.0],
            }
        )
        errors = DailyPriceContract.validate(df)
        assert len(errors) == 0

    def test_missing_column(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2024-01-15"]),
                "symbol": ["000001"],
                "close": [10.5],
                "volume": [1000000.0],
                # missing open, high, low
            }
        )
        errors = DailyPriceContract.validate(df)
        assert any("open" in e for e in errors)

    def test_wrong_date_type(self):
        df = pd.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],  # string, not datetime64
                "symbol": ["000001", "000001"],
                "open": [10.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
                "volume": [1000000.0, 800000.0],
            }
        )
        errors = DailyPriceContract.validate(df)
        assert any("datetime64" in e for e in errors)

    def test_null_close(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2024-01-15", "2024-01-16"]),
                "symbol": ["000001", "000001"],
                "open": [10.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [np.nan, 10.3],  # NaN close
                "volume": [1000000.0, 800000.0],
            }
        )
        errors = DailyPriceContract.validate(df)
        assert any("close" in e for e in errors)

    def test_null_symbol(self):
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2024-01-15"]),
                "symbol": [None],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000000.0],
            }
        )
        errors = DailyPriceContract.validate(df)
        assert any("symbol" in e for e in errors)

    def test_optional_timestamp_columns_allowed(self):
        """Having source_event_time / ingestion_received_time should not fail validation."""
        df = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2024-01-15"]),
                "symbol": ["000001"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000000.0],
                "source_event_time": ["2024-01-15T15:00:00+08:00"],
                "ingestion_received_time": ["2024-07-21T12:00:00+00:00"],
            }
        )
        errors = DailyPriceContract.validate(df)
        # Extra optional columns should not cause errors
        assert len(errors) == 0
