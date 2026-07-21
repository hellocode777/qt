"""Tests for qp.data.builder — DatasetBuilder, DatasetMetadata, BuildResult."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from qp.data.builder import (
    BuildConfig,
    BuildResult,
    DatasetBuilder,
    DatasetMetadata,
    build_dataset,
)
from qp.shared.types import DataTier

# ==================================================================
# Helpers
# ==================================================================


def _make_price_df(n_days: int = 30) -> pl.DataFrame:
    """Create a small OHLCV DataFrame with trade_date."""
    import numpy as np

    rng = np.random.default_rng(42)
    rows: list[dict] = []
    for sym in ["600519", "000001"]:
        close = 100.0 + rng.normal(0, 2, n_days).cumsum()
        for d_idx in range(n_days):
            rows.append({
                "symbol": sym,
                "trade_date": f"2024-01-{d_idx+1:02d}",
                "close": float(close[d_idx]),
                "volume": float(abs(rng.normal(1e6, 2e5))),
            })
    return pl.DataFrame(rows).with_columns(
        pl.col("trade_date").str.to_date(),
    )


def _make_valid_metadata() -> DatasetMetadata:
    """Return a fully valid DatasetMetadata instance."""
    return DatasetMetadata(
        name="daily_price",
        owner="data-layer",
        source="test_adapter",
        schema={
            "trade_date": "date",
            "symbol": "str",
            "close": "float64",
            "volume": "float64",
        },
        frequency="daily",
        primary_key=["trade_date", "symbol"],
    )


class _FakeContract:
    """Minimal contract class with validate() interface."""

    @classmethod
    def validate(cls, df: pl.DataFrame) -> list[str]:
        return []


class _FailingContract:
    """Contract class that always fails."""

    @classmethod
    def validate(cls, df: pl.DataFrame) -> list[str]:
        return ["mock validation failure"]


# ==================================================================
# Test DatasetMetadata
# ==================================================================


class TestDatasetMetadata:
    def test_valid_metadata(self):
        meta = _make_valid_metadata()
        assert meta.validate() == []

    def test_missing_name(self):
        meta = _make_valid_metadata()
        meta.name = ""
        errors = meta.validate()
        assert any("name" in e for e in errors)

    def test_missing_owner(self):
        meta = _make_valid_metadata()
        meta.owner = ""
        errors = meta.validate()
        assert any("owner" in e for e in errors)

    def test_missing_source(self):
        meta = _make_valid_metadata()
        meta.source = ""
        errors = meta.validate()
        assert any("source" in e for e in errors)

    def test_missing_schema(self):
        meta = _make_valid_metadata()
        meta.schema = {}
        errors = meta.validate()
        assert any("schema" in e for e in errors)

    def test_missing_frequency(self):
        meta = _make_valid_metadata()
        meta.frequency = ""
        errors = meta.validate()
        assert any("frequency" in e for e in errors)

    def test_missing_primary_key(self):
        meta = _make_valid_metadata()
        meta.primary_key = []
        errors = meta.validate()
        assert any("primary_key" in e for e in errors)

    def test_invalid_pit_confidence(self):
        meta = _make_valid_metadata()
        meta.pit_confidence = "impossible"
        errors = meta.validate()
        assert any("pit_confidence" in e for e in errors)

    def test_to_dict_roundtrip(self):
        meta = _make_valid_metadata()
        d = meta.to_dict()
        assert d["name"] == "daily_price"
        assert d["source"] == "test_adapter"
        assert d["frequency"] == "daily"

    def test_default_values(self):
        meta = DatasetMetadata(
            name="test",
            owner="me",
            source="demo",
            schema={"a": "int"},
            frequency="daily",
            primary_key=["a"],
        )
        assert meta.timezone == "Asia/Shanghai"
        assert meta.pit_confidence == "high"
        assert meta.update_policy == "daily_append"
        assert meta.version == ""


# ==================================================================
# Test BuildResult
# ==================================================================


class TestBuildResult:
    def test_success_summary(self):
        result = BuildResult(
            success=True,
            dataset_name="daily_price",
            version="2026-07-01",
            rows=100,
            symbols=5,
        )
        assert "✅" in result.summary()
        assert "2026-07-01" in result.summary()

    def test_failure_summary(self):
        result = BuildResult(
            success=False,
            dataset_name="daily_price",
            errors=["something went wrong"],
        )
        assert "❌" in result.summary()
        assert "something went wrong" in result.summary()

    def test_failure_summary_no_errors(self):
        result = BuildResult(success=False, dataset_name="test")
        assert "unknown" in result.summary()


# ==================================================================
# Test DatasetBuilder
# ==================================================================


class TestDatasetBuilder:
    def test_build_successful(self, tmp_path):
        builder = DatasetBuilder(
            BuildConfig(output_dir=str(tmp_path), require_contract=False)
        )
        df = _make_price_df(n_days=10)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert result.success
        assert result.rows == 20  # 10 days × 2 symbols
        assert result.symbols == 2
        assert result.version != ""
        assert Path(result.path).exists()

    def test_build_empty_df_rejected(self):
        builder = DatasetBuilder()
        df = pl.DataFrame()
        meta = _make_valid_metadata()
        result = builder.build(df, meta)
        assert not result.success
        assert "空" in result.errors[0]

    def test_build_invalid_metadata(self):
        builder = DatasetBuilder()
        df = _make_price_df(n_days=5)
        meta = DatasetMetadata(
            name="", owner="", source="", schema={},
            frequency="", primary_key=[],
        )
        result = builder.build(df, meta)
        assert not result.success
        assert len(result.errors) > 0

    def test_build_contract_validation_passes(self, tmp_path):
        builder = DatasetBuilder(BuildConfig(output_dir=str(tmp_path)))
        builder.register_source("test_adapter", _FakeContract)
        df = _make_price_df(n_days=10)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert result.success

    def test_build_contract_validation_fails_strict(self, tmp_path):
        builder = DatasetBuilder(
            BuildConfig(output_dir=str(tmp_path), fail_on_validation_error=True)
        )
        builder.register_source("test_adapter", _FailingContract)
        df = _make_price_df(n_days=10)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert not result.success
        assert any("mock validation failure" in e for e in result.errors)

    def test_build_no_contract_registered_strict(self, tmp_path):
        """With require_contract=True and no registered contract, build fails."""
        builder = DatasetBuilder(
            BuildConfig(output_dir=str(tmp_path), require_contract=True)
        )
        # NOT calling register_source()
        df = _make_price_df(n_days=5)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert not result.success
        assert any("未注册" in e for e in result.errors)

    def test_build_no_contract_but_not_required(self, tmp_path):
        """With require_contract=False, builds succeed without a contract."""
        builder = DatasetBuilder(
            BuildConfig(output_dir=str(tmp_path), require_contract=False)
        )
        df = _make_price_df(n_days=5)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert result.success

    def test_build_dataset_convenience(self, tmp_path):
        """build_dataset() module-level function."""
        df = _make_price_df(n_days=5)
        result = build_dataset(df, {
            "name": "test_ds",
            "owner": "me",
            "source": "demo",
            "schema": {"trade_date": "date", "symbol": "str"},
            "frequency": "daily",
            "primary_key": ["trade_date", "symbol"],
        })
        # build_dataset() convenience wrapper builds without contract requirement
        assert result.success

    def test_version_auto_assign(self, tmp_path):
        builder = DatasetBuilder(
            BuildConfig(output_dir=str(tmp_path), require_contract=False)
        )
        df = _make_price_df(n_days=5)
        meta = _make_valid_metadata()
        meta.version = ""  # empty → auto-assigned

        from datetime import date

        result = builder.build(df, meta)
        assert result.success
        assert result.version == date.today().isoformat()

    def test_derive_coverage(self):
        builder = DatasetBuilder()
        df = _make_price_df(n_days=10)
        start, end = builder._derive_coverage(df)
        assert start is not None
        assert end is not None
        assert str(start) == "2024-01-01"
        assert str(end) == "2024-01-10"

    def test_derive_coverage_no_date_col(self):
        builder = DatasetBuilder()
        df = pl.DataFrame({"x": [1, 2, 3]})
        start, end = builder._derive_coverage(df)
        assert start is None
        assert end is None

    def test_register_source(self):
        builder = DatasetBuilder()
        builder.register_source("my_source", _FakeContract)
        assert "my_source" in builder._source_contracts
        assert builder._source_contracts["my_source"] == _FakeContract

    def test_metadata_json_written(self, tmp_path):
        builder = DatasetBuilder(
            BuildConfig(
                output_dir=str(tmp_path),
                persist_metadata=True,
                require_contract=False,
            )
        )
        df = _make_price_df(n_days=5)
        meta = _make_valid_metadata()

        result = builder.build(df, meta)
        assert result.success

        # Check _metadata.json exists
        output_stem = Path(result.path).stem
        meta_path = Path(result.path).parent / f"{output_stem}_metadata.json"
        assert meta_path.exists()

        # Verify content
        data = json.loads(meta_path.read_text())
        assert data["name"] == "daily_price"
        assert data["rows"] == 10
        assert "columns" in data


# ==================================================================
# Test BuildConfig
# ==================================================================


class TestBuildConfig:
    def test_defaults(self):
        config = BuildConfig()
        assert config.tier == DataTier.GOLD
        assert config.output_dir == "data/dataset"
        assert config.require_contract is True
        assert config.fail_on_validation_error is True
        assert config.persist_metadata is True
