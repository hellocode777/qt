# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.loader.full_pipeline (previously 20%)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import polars as pl

from qp.data.loader.full_pipeline import (
    FullDataPipeline,
    _normalize_volume_unit,
)
from qp.platform.pipeline.context import PipelineContext


def _sample_raw_pd() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600519", "600519", "000001"],
            "trade_date": ["2026-07-01", "2026-07-02", "2026-07-01"],
            "open": [100.0, 103.0, 10.0],
            "high": [105.0, 108.0, 10.5],
            "low": [99.0, 102.0, 9.9],
            "close": [103.0, 106.0, 10.2],
            "volume": [1_000_000, 1_200_000, 500_000],
        }
    )


class TestNormalizeVolumeUnit:
    def test_small_volume_unchanged(self) -> None:
        df = pl.DataFrame({"volume": [1_000_000, 2_000_000]})
        result = _normalize_volume_unit(df, None)
        assert result["volume"].to_list() == [1_000_000, 2_000_000]

    def test_large_volume_divided_by_100(self) -> None:
        from loguru import logger

        df = pl.DataFrame({"volume": [100_000_000, 200_000_000]})
        result = _normalize_volume_unit(df, logger)
        assert result["volume"].to_list() == [1_000_000, 2_000_000]

    def test_empty_df_unchanged(self) -> None:
        assert _normalize_volume_unit(pl.DataFrame(), None).height == 0


class TestFullDataPipelineRun:
    def test_full_run_success(self) -> None:
        """Full run with mocked adapter — verifies tier flow + registry."""
        from qp.data.dataset.registry import DatasetRegistry

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.loader.full_pipeline.TencentAdapter") as mock_adapt,
            patch(
                "qp.data.loader.full_pipeline.get_main_board_codes",
                return_value=["600519", "000001", "000002"],
            ),
            patch("qp.data.loader.full_pipeline.DIR_RAW", Path(tmp) / "raw"),
            patch("qp.data.loader.full_pipeline.DIR_BRONZE", Path(tmp) / "bronze"),
            patch("qp.data.loader.full_pipeline.DIR_SILVER", Path(tmp) / "silver"),
            patch("qp.data.loader.full_pipeline.DIR_GOLD", Path(tmp) / "gold"),
            patch("qp.data.loader.full_pipeline.ETLPipeline") as mock_etl,
            patch(
                "qp.data.loader.full_pipeline.repair_all",
                side_effect=lambda x, **kw: x,
            ),
            patch(
                "qp.data.loader.full_pipeline.annotate_timestamps_pl",
                side_effect=lambda x: x,
            ),
        ):
            adapter = mock_adapt.return_value
            adapter.fetch_raw.return_value = _sample_raw_pd()

            etl = mock_etl.return_value
            etl.run.return_value.df = pl.from_pandas(_sample_raw_pd())

            pipeline = FullDataPipeline()
            ctx = PipelineContext(
                pipeline_name="test_full",
                parameters={
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "batch_size": 1,
                },
            )
            result = pipeline.run(ctx)

            assert result.status.value == "success"
            assert result.metrics["n_stocks"] == 2
            assert result.metrics["n_rows"] == 3
            assert result.metadata["registry_key"].startswith("daily_price_main@")
            assert len(result.artifacts) == 4

            # Registry entry exists
            reg = DatasetRegistry(base_dir=str(Path(tmp) / "gold"))
            entry = reg.resolve("daily_price_main", result.metadata["version"])
            assert entry["name"] == "daily_price_main"

    def test_run_batches_by_batch_size(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.loader.full_pipeline.TencentAdapter") as mock_adapt,
            patch(
                "qp.data.loader.full_pipeline.get_main_board_codes",
                return_value=["600519", "000001", "000002"],
            ),
            patch("qp.data.loader.full_pipeline.DIR_RAW", Path(tmp) / "raw"),
            patch("qp.data.loader.full_pipeline.DIR_BRONZE", Path(tmp) / "bronze"),
            patch("qp.data.loader.full_pipeline.DIR_SILVER", Path(tmp) / "silver"),
            patch("qp.data.loader.full_pipeline.DIR_GOLD", Path(tmp) / "gold"),
            patch("qp.data.loader.full_pipeline.ETLPipeline") as mock_etl,
            patch(
                "qp.data.loader.full_pipeline.repair_all",
                side_effect=lambda x, **kw: x,
            ),
            patch(
                "qp.data.loader.full_pipeline.annotate_timestamps_pl",
                side_effect=lambda x: x,
            ),
        ):
            adapter = mock_adapt.return_value
            adapter.fetch_raw.return_value = _sample_raw_pd().head(1)

            etl = mock_etl.return_value
            etl.run.return_value.df = pl.from_pandas(_sample_raw_pd().head(1))

            pipeline = FullDataPipeline()
            ctx = PipelineContext(
                pipeline_name="test_batch",
                parameters={"start_date": "2026-07-01", "end_date": "2026-07-02", "batch_size": 2},
            )
            result = pipeline.run(ctx)
            assert result.status.value == "success"
            # 3 codes / batch 2 → 2 batches
            assert adapter.fetch_raw.call_count == 2

    def test_empty_codes_raises_concat_error(self) -> None:
        """No codes → pl.concat([]) raises ValueError (current behavior)."""
        import pytest

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.loader.full_pipeline.TencentAdapter") as mock_adapt,
            patch(
                "qp.data.loader.full_pipeline.get_main_board_codes",
                return_value=["600519", "000001", "000002"],
            ),
            patch("qp.data.loader.full_pipeline.DIR_RAW", Path(tmp) / "raw"),
            patch("qp.data.loader.full_pipeline.DIR_BRONZE", Path(tmp) / "bronze"),
            patch("qp.data.loader.full_pipeline.DIR_SILVER", Path(tmp) / "silver"),
            patch("qp.data.loader.full_pipeline.DIR_GOLD", Path(tmp) / "gold"),
            patch("qp.data.loader.full_pipeline.ETLPipeline") as mock_etl,
            patch(
                "qp.data.loader.full_pipeline.repair_all",
                side_effect=lambda x, **kw: x,
            ),
            patch(
                "qp.data.loader.full_pipeline.annotate_timestamps_pl",
                side_effect=lambda x: x,
            ),
        ):
            adapter = mock_adapt.return_value
            adapter.get_codes.return_value = []
            adapter.fetch_raw.return_value = pd.DataFrame()

            etl = mock_etl.return_value
            etl.run.return_value.df = pl.DataFrame()

            pipeline = FullDataPipeline()
            ctx = PipelineContext(
                pipeline_name="test_empty",
                parameters={"start_date": "2026-07-01", "end_date": "2026-07-02"},
            )
            with pytest.raises(ValueError, match="concat empty"):
                pipeline.run(ctx)
