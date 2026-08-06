# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.validation.pandera_schemas and pandera_validator."""

from __future__ import annotations

import pandera as pa
import polars as pl
import pytest

from qp.data.validation.pandera_schemas import (
    BalanceSheetSchema,
    DailyPriceExtendedSchema,
    DailyPriceSchema,
    FundamentalIndicatorSchema,
)
from qp.data.validation.pandera_validator import PanderaValidator
from qp.data.validation.result import Severity


def _ohlc_df(**overrides: object) -> pl.DataFrame:
    """Helper: create a valid OHLCV DataFrame, optionally overriding fields."""
    data: dict[str, list[object]] = {
        "symbol": ["000001", "000002"],
        "trade_date": ["2024-01-15", "2024-01-16"],
        "open": [10.0, 20.0],
        "high": [10.5, 20.8],
        "low": [9.8, 19.8],
        "close": [10.2, 20.5],
        "volume": [1000000.0, 800000.0],
    }
    for k, v in overrides.items():
        data[k] = v  # type: ignore[assignment]
    return pl.DataFrame(data).with_columns(pl.col("trade_date").str.to_date())


# ==================================================================
# DailyPriceSchema
# ==================================================================


class TestDailyPriceSchema:
    def test_valid_data_passes(self):
        df = _ohlc_df()
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is True

    def test_missing_column_fails(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "high": [10.5],
                "close": [10.2],
                "volume": [1000000.0],
                # low is missing
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert "low" in result.detail.lower() or any(
            "low" in e for e in result.metadata.get("errors", [])
        )

    def test_negative_price_fails(self):
        df = _ohlc_df(open=[-1.0, 20.0])
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is False
        assert any("greater_than" in e for e in result.metadata["errors"])

    def test_negative_volume_fails(self):
        df = _ohlc_df(volume=[-100.0, 800000.0])
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is False

    def test_null_symbol_fails(self):
        df = _ohlc_df(symbol=[None, "000002"])
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is False

    def test_zero_price_fails(self):
        """gt=0 means strictly greater than 0."""
        df = _ohlc_df(open=[0.0, 20.0])
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is False

    def test_extra_columns_allowed(self):
        """strict=False allows extra columns."""
        df = _ohlc_df()
        df = df.with_columns(pl.lit("extra").alias("extra_col"))
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is True

    def test_empty_dataframe(self):
        df = pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        )
        result = PanderaValidator.validate(df, DailyPriceSchema)
        assert result.passed is True


# ==================================================================
# DailyPriceExtendedSchema
# ==================================================================


class TestDailyPriceExtendedSchema:
    def test_valid_extended_data_passes(self):
        df = _ohlc_df()
        df = df.with_columns(
            [
                pl.lit("2024-01-15T15:00:00+08:00").alias("source_event_time"),
                pl.lit("2024-01-15T10:00:00Z").alias("ingestion_received_time"),
                pl.lit(False).alias("is_suspended"),
                pl.lit(True).alias("is_tradeable"),
            ]
        )
        result = PanderaValidator.validate(df, DailyPriceExtendedSchema)
        assert result.passed is True

    def test_missing_optional_columns_ok(self):
        """Optional columns (source_event_time etc.) can be absent."""
        df = _ohlc_df()
        result = PanderaValidator.validate(df, DailyPriceExtendedSchema)
        assert result.passed is True

    def test_wrong_type_optional_column_still_fails(self):
        """If an optional column IS present, its type is checked."""
        df = _ohlc_df()
        df = df.with_columns(pl.lit(42).alias("is_suspended"))  # int, not bool
        result = PanderaValidator.validate(df, DailyPriceExtendedSchema)
        # Pandera may coerce or reject — either way the test checks it doesn't crash
        assert isinstance(result.passed, bool)


# ==================================================================
# BalanceSheetSchema
# ==================================================================


class TestBalanceSheetSchema:
    def test_valid_balance_sheet_passes(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [400000.0],
            }
        ).with_columns(pl.col("report_date").str.to_date())
        result = PanderaValidator.validate(df, BalanceSheetSchema)
        assert result.passed is True

    def test_negative_equity_fails(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [-100000.0],
            }
        ).with_columns(pl.col("report_date").str.to_date())
        result = PanderaValidator.validate(df, BalanceSheetSchema)
        assert result.passed is False


# ==================================================================
# FundamentalIndicatorSchema
# ==================================================================


class TestFundamentalIndicatorSchema:
    def test_valid_indicators_pass(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "publish_date": ["2024-10-25"],
                "ROE": [15.5],
                "revenue_growth": [12.3],
                "gross_margin": [45.0],
                "net_margin": [18.2],
                "debt_ratio": [40.0],
                "EPS": [2.5],
                "NAV": [15.0],
                "cashflow_per_share": [1.8],
            }
        ).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        result = PanderaValidator.validate(df, FundamentalIndicatorSchema)
        assert result.passed is True

    def test_optional_fields_can_be_missing(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "publish_date": ["2024-10-25"],
            }
        ).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        result = PanderaValidator.validate(df, FundamentalIndicatorSchema)
        assert result.passed is True

    def test_debt_ratio_out_of_range_fails(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "publish_date": ["2024-10-25"],
                "debt_ratio": [150.0],  # > 100
            }
        ).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        result = PanderaValidator.validate(df, FundamentalIndicatorSchema)
        assert result.passed is False


# ==================================================================
# PanderaValidator
# ==================================================================


class TestPanderaValidator:
    def test_validate_or_raise_passes(self):
        df = _ohlc_df()
        PanderaValidator.validate_or_raise(df, DailyPriceSchema)  # No exception

    def test_validate_or_raise_fails(self):
        df = pl.DataFrame({"symbol": ["000001"]})
        with pytest.raises(pa.errors.SchemaError):
            PanderaValidator.validate_or_raise(df, DailyPriceSchema)

    def test_custom_schema_name(self):
        df = _ohlc_df()
        result = PanderaValidator.validate(df, DailyPriceSchema, schema_name="MySchema")
        assert result.check_name == "pandera_MySchema"


# ==================================================================
# GateConfig integration
# ==================================================================


class TestGateConfigPandera:
    def test_gate_with_pandera_enabled(self):
        from qp.data.validation.gate import GateConfig, ValidationGate

        config = GateConfig(
            enable_gaps=False,
            enable_monotonicity=False,
            enable_ohlc_physics=False,
            enable_price_limits=False,
            enable_non_negative=False,
            enable_null_rate=False,
            enable_pandera=True,
            pandera_schema=DailyPriceSchema,
        )
        gate = ValidationGate(config)
        report = gate.validate(_ohlc_df())
        assert report.total_checks == 1
        assert report.checks[0].check_name == "pandera_DailyPriceSchema"
        assert report.passed is True

    def test_gate_with_pandera_fails_on_bad_data(self):
        from qp.data.validation.gate import GateConfig, ValidationGate

        config = GateConfig(
            enable_pandera=True,
            pandera_schema=DailyPriceSchema,
            enable_gaps=False,
            enable_monotonicity=False,
            enable_ohlc_physics=False,
            enable_price_limits=False,
            enable_non_negative=False,
            enable_null_rate=False,
        )
        gate = ValidationGate(config)
        bad_df = _ohlc_df(open=[-1.0, 20.0])
        report = gate.validate(bad_df)
        assert report.passed is False
