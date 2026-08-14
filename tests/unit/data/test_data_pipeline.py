# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.pipeline — DataPipeline critical functions.

Covers the three core pure functions that were previously at ~9% coverage:
  - _validate_data_gate (7 validation checks)
  - _trading_days_between (trading-day gap count)
  - _normalize_volume_relative (股→手 unit normalization, 8/5 incident guard)
Plus the DataPipeline demo short-circuit path (never writes to production).
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from qp.data.pipeline import (
    DataPipeline,
    _normalize_volume_relative,
    _trading_days_between,
    _validate_data_gate,
)
from qp.platform.pipeline.context import PipelineContext


def _valid_df(n_symbols: int = 12, n_days: int = 5, base_date: str = "2026-07-01") -> pl.DataFrame:
    """Build a minimal valid OHLCV frame."""
    rows: list[dict] = []
    start = date.fromisoformat(base_date)
    for i in range(n_symbols):
        for d in range(n_days):
            rows.append(
                {
                    "trade_date": (start + timedelta(days=d)).isoformat(),
                    "symbol": f"{i:06d}",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1_000_000,
                }
            )
    return pl.DataFrame(rows)


class TestValidateDataGate:
    def test_valid_data_passes(self) -> None:
        errors = _validate_data_gate(_valid_df())
        assert errors == []

    def test_empty_dataframe_fails(self) -> None:
        errors = _validate_data_gate(pl.DataFrame())
        assert any("empty" in e for e in errors)

    def test_missing_required_columns(self) -> None:
        df = pl.DataFrame({"trade_date": ["2026-07-01"], "symbol": ["000001"]})
        errors = _validate_data_gate(df)
        assert any("Missing required" in e for e in errors)

    def test_negative_close_fails(self) -> None:
        df = _valid_df().with_columns(pl.lit(-5.0).alias("close"))
        errors = _validate_data_gate(df)
        assert any("close <= 0" in e for e in errors)

    def test_high_below_low_fails(self) -> None:
        df = _valid_df().with_columns([pl.lit(9.0).alias("high"), pl.lit(11.0).alias("low")])
        errors = _validate_data_gate(df)
        assert any("high < low" in e for e in errors)

    def test_high_below_close_fails(self) -> None:
        df = _valid_df().with_columns([pl.lit(10.0).alias("high"), pl.lit(10.5).alias("close")])
        errors = _validate_data_gate(df)
        assert any("high < close" in e for e in errors)

    def test_close_below_low_fails(self) -> None:
        df = _valid_df().with_columns([pl.lit(9.5).alias("close"), pl.lit(10.0).alias("low")])
        errors = _validate_data_gate(df)
        assert any("close < low" in e for e in errors)

    def test_negative_volume_fails(self) -> None:
        df = _valid_df().with_columns(pl.lit(-100.0).alias("volume"))
        errors = _validate_data_gate(df)
        assert any("volume < 0" in e for e in errors)

    def test_too_few_symbols_fails(self) -> None:
        df = _valid_df(n_symbols=3)
        errors = _validate_data_gate(df)
        assert any("symbols" in e and "API" in e for e in errors)

    def test_future_date_fails(self) -> None:
        future = (date.today() + timedelta(days=10)).isoformat()
        df = _valid_df().with_columns(pl.lit(future).alias("trade_date"))
        errors = _validate_data_gate(df)
        assert any("future" in e for e in errors)

    def test_date_regression_detected(self) -> None:
        """Existing data max date is far AHEAD of incoming → reject."""
        existing = _valid_df(n_days=1, base_date="2026-07-10")
        incoming = _valid_df(n_days=1, base_date="2026-06-01")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "daily.parquet"
            existing.write_parquet(p)
            errors = _validate_data_gate(incoming, existing_path=p)
        assert any("Date regression" in e for e in errors)

    def test_symbol_drift_detected(self) -> None:
        df = _valid_df(n_symbols=100)
        prev_meta = {"symbols": 50}
        errors = _validate_data_gate(df, registry_meta=prev_meta)
        assert any("Symbol drift" in e for e in errors)

    def test_no_drift_within_threshold(self) -> None:
        df = _valid_df(n_symbols=52)
        prev_meta = {"symbols": 50}
        errors = _validate_data_gate(df, registry_meta=prev_meta)
        assert all("drift" not in e.lower() for e in errors)


class TestTradingDaysBetween:
    def test_same_day_zero(self) -> None:
        assert _trading_days_between("2026-07-13", "2026-07-13") == 0

    def test_monday_to_friday_is_four(self) -> None:
        assert _trading_days_between("2026-07-13", "2026-07-17") == 4

    def test_friday_to_monday_is_one(self) -> None:
        # 2026-07-17 is Friday, 2026-07-20 is Monday
        assert _trading_days_between("2026-07-17", "2026-07-20") == 1

    def test_reverse_is_negative(self) -> None:
        assert _trading_days_between("2026-07-20", "2026-07-17") == -1

    def test_weekend_span_counted(self) -> None:
        # Thu→Tue: Fri + Mon + Tue(终点含入) = 3
        assert _trading_days_between("2026-07-16", "2026-07-21") == 3


class TestNormalizeVolumeRelative:
    def _make_volume_df(self, volume: float) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": ["2026-07-01", "2026-07-02"],
                "symbol": ["000001", "000002"],
                "close": [10.0, 10.5],
                "volume": [volume, volume],
            }
        )

    def test_no_volume_column_unchanged(self) -> None:
        df = pl.DataFrame({"trade_date": ["2026-07-01"], "symbol": ["000001"]})
        result = _normalize_volume_relative(df, None, None)
        assert result is df  # returned as-is, no copy

    def test_empty_df_unchanged(self) -> None:
        df = pl.DataFrame()
        result = _normalize_volume_relative(df, None, None)
        assert result.height == 0

    def test_same_unit_unchanged(self) -> None:
        """Incoming median ≈ existing median (手) → left alone."""
        df = self._make_volume_df(1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "daily.parquet"
            existing = self._make_volume_df(900_000)
            existing.write_parquet(p)
            result = _normalize_volume_relative(df, p, None)
        assert result["volume"].to_list() == [1_000_000, 1_000_000]

    def test_unit_mismatch_divided_by_100(self) -> None:
        """Incoming in 股 (100x) vs existing in 手 → divide by 100."""
        from loguru import logger

        df = self._make_volume_df(100_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "daily.parquet"
            existing = self._make_volume_df(1_000_000)
            existing.write_parquet(p)
            result = _normalize_volume_relative(df, p, logger)
        assert result["volume"].to_list() == [1_000_000, 1_000_000]

    def test_no_existing_small_volume_unchanged(self) -> None:
        """No reference → absolute heuristic: median ≤ 20M stays."""
        df = self._make_volume_df(5_000_000)
        result = _normalize_volume_relative(df, None, None)
        assert result["volume"].to_list() == [5_000_000, 5_000_000]

    def test_no_existing_large_volume_divided(self) -> None:
        """No reference + median > 20M → almost certainly 股 → divide."""
        from loguru import logger

        df = self._make_volume_df(100_000_000)
        result = _normalize_volume_relative(df, None, logger)
        assert result["volume"].to_list() == [1_000_000, 1_000_000]


class TestDataPipelineDemoShortCircuit:
    def test_demo_mode_never_writes_production(self) -> None:
        """Demo run returns success but must NOT touch daily_price_latest.parquet."""
        import hashlib

        from qp.data.adapter.demo_adapter import DemoAdapter

        out_path = Path("data/dataset/daily_price_latest.parquet")
        before_hash = None
        if out_path.exists():
            before_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()

        pipeline = DataPipeline()
        ctx = PipelineContext(
            pipeline_name="test_demo",
            parameters={
                "demo": True,
                "start_date": "2026-01-01",
                "end_date": "2026-01-10",
                "symbols": DemoAdapter.DEFAULT_SYMBOLS[:5],
            },
        )
        result = pipeline.run(ctx)

        assert result.status.value == "success"
        assert result.metadata.get("demo") is True
        assert "NOT written" in result.metadata.get("warning", "")

        if before_hash is not None:
            after_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
            assert after_hash == before_hash, "demo run must not modify production dataset"

    def test_demo_mode_records_source(self) -> None:
        from qp.data.adapter.demo_adapter import DemoAdapter

        pipeline = DataPipeline()
        ctx = PipelineContext(
            pipeline_name="test_demo_src",
            parameters={
                "demo": True,
                "symbols": DemoAdapter.DEFAULT_SYMBOLS[:3],
            },
        )
        result = pipeline.run(ctx)
        assert result.metadata.get("source") == "demo"
        assert result.metrics.get("raw_rows", 0) > 0
