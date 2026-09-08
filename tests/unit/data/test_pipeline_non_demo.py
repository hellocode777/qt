# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for DataPipeline non-demo path (run steps 4-7: gate/merge/write/registry).

Covers the production path that writes to data/dataset — previously uncovered.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pandas as pd
import polars as pl

from qp.data.cleaning.engine import CleaningEngine
from qp.data.pipeline import DataPipeline
from qp.data.timestamp import annotate_timestamps_pl
from qp.platform.pipeline.context import PipelineContext


def _real_clean_df() -> pl.DataFrame:
    """Real cleaned data via demo data + real annotate/clean (no network)."""
    from qp.data.adapter.demo_adapter import DemoAdapter

    raw = DemoAdapter().fetch_raw(date(2026, 1, 5), date(2026, 1, 9), symbols=["600519", "000001"])
    return CleaningEngine().clean(annotate_timestamps_pl(raw))


def _ctx(**params) -> PipelineContext:
    defaults = {"start_date": "2026-01-05", "end_date": "2026-01-09"}
    defaults.update(params)
    return PipelineContext(pipeline_name="test", parameters=defaults)


class TestNonDemoHappyPath:
    def test_full_run_writes_dataset_and_registry(self, tmp_path, monkeypatch) -> None:
        """Real gate/merge/atomic-write/registry with mocked adapter network."""
        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()

        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()

            pipeline = DataPipeline()
            result = pipeline.run(_ctx())

        assert result.status.value == "success"
        assert result.metrics["raw_rows"] > 0
        assert result.metrics["cleaned_rows"] > 0
        assert result.metadata["source"] == "tencent"  # 2026-08-14: 唯一数据源
        assert result.metadata["data_hash"]  # sha256 computed

        # Gold dataset written
        gold = tmp_path / "data" / "dataset" / "daily_price_latest.parquet"
        assert gold.exists()
        written = pl.read_parquet(gold)
        assert written.height > 0
        assert "symbol" in written.columns

        # Registry registered with hash metadata
        from qp.data.dataset.registry import DatasetRegistry

        reg = DatasetRegistry(base_dir=str(tmp_path / "data" / "dataset"))
        entry = reg.resolve("daily_price", "latest")
        assert entry["metadata"]["sha256"] == result.metadata["data_hash"]
        assert entry["metadata"]["status"] == "READY"

        # Quality report written
        from qp.shared.time import today_cn

        report = tmp_path / "data" / "reports" / f"data_quality_{today_cn().isoformat()}.json"
        assert report.exists()

    def test_merge_with_existing_dedupes(self, tmp_path, monkeypatch) -> None:
        """Existing dataset + new overlapping rows → merged, deduped, newest wins."""
        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()

        # Pre-seed existing dataset with one overlapping (older) row
        out_dir = tmp_path / "data" / "dataset"
        out_dir.mkdir(parents=True)
        existing = clean_df.with_columns(pl.lit(100.0).alias("close"))
        existing.write_parquet(out_dir / "daily_price_latest.parquet")

        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx())

        assert result.status.value == "success"
        assert result.metrics["existing_rows"] > 0
        assert result.metadata["data_hash"]

    def test_same_day_rerun_zero_increment_keeps_first_report(self, tmp_path, monkeypatch) -> None:
        """同日幂等重跑 (new_rows=0) 不得覆盖首份报告的真实增量。

        2026-08-18 事故回归: 18:50 的一次重跑把当天首跑 (new_rows=3027)
        的数据质量报告覆盖成 new_rows=0, 监控页当日柱显示"新增0"。
        """
        from qp.shared.time import today_cn

        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()

        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()
            pipeline = DataPipeline()
            first = pipeline.run(_ctx())
            report = tmp_path / "data" / "reports" / f"data_quality_{today_cn().isoformat()}.json"
            first_report_text = report.read_text(encoding="utf-8")
            # 第二次返回相同数据 → merge 全重复 → new_rows=0
            second = pipeline.run(_ctx())

        assert first.status.value == "success"
        assert second.status.value == "success"
        assert second.metrics["existing_rows"] > 0
        payload = json.loads(first_report_text)
        assert payload["new_rows"] == payload["rows_after"]  # 首跑为全量写入
        # 报告文件保持首份内容 (run_id/时间戳/new_rows 均未被重跑改写)
        assert report.read_text(encoding="utf-8") == first_report_text

    def test_same_day_rerun_larger_increment_overwrites_report(self, tmp_path, monkeypatch) -> None:
        """反向: 当日已有报告但本次追加更多 → 仍应覆盖 (重跑补数场景)。"""
        from qp.shared.time import today_cn

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "data" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / f"data_quality_{today_cn().isoformat()}.json"
        # 预置一份"增量极小"的假报告 (模拟首跑只追加了几行)
        report.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "pipeline_run_id": "seed",
                    "new_rows": 1,
                    "rows_after": 1,
                }
            ),
            encoding="utf-8",
        )
        clean_df = _real_clean_df()

        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()
            result = DataPipeline().run(_ctx())

        assert result.status.value == "success"
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["pipeline_run_id"] != "seed"  # 假报告被真实报告替换
        assert payload["new_rows"] == payload["rows_after"]
        assert payload["new_rows"] > 1

    def test_source_tencent(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()
        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx(source="tencent"))
        assert result.metadata["source"] == "tencent"
        assert result.status.value == "success"

    def test_source_sina_rejected(self, tmp_path, monkeypatch) -> None:
        """2026-08-14: 新浪路径已废弃 — 显式 --source=sina 必须 FAILED，绝不 fallback."""
        monkeypatch.chdir(tmp_path)
        pipeline = DataPipeline()
        result = pipeline.run(_ctx(source="sina"))
        assert result.status.value == "failed"
        assert any("唯一数据源" in e or "tencent" in e for e in result.errors)


class TestNonDemoFailures:
    def test_all_adapters_return_empty_fails(self, tmp_path, monkeypatch) -> None:
        """No network data → FAILED with clear error (not silent)."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("qp.data.adapter.sina_adapter.SinaAdapter") as mock_sina,
            patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx,
        ):
            mock_sina.return_value.fetch_raw.return_value = pd.DataFrame()
            mock_tx.return_value.fetch_raw.return_value = pd.DataFrame()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx())
        assert result.status.value == "failed"
        assert any("network" in e for e in result.errors)

    def test_long_span_uses_tencent_directly(self, tmp_path, monkeypatch) -> None:
        """>5yr span → TencentAdapter chosen (source=tencent), no Sina fallback."""
        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()
        with (
            patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx,
            patch("qp.data.adapter.sina_adapter.SinaAdapter") as mock_sina,
        ):
            adapter = mock_tx.return_value
            adapter.fetch_raw.return_value = clean_df.to_pandas()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx(start_date="2018-01-01", end_date="2026-01-09"))
        assert result.metadata["source"] == "tencent"
        # Sina should not even be constructed
        mock_sina.assert_not_called()
        assert result.status.value == "success"

    def test_tencent_empty_fails_no_fallback(self, tmp_path, monkeypatch) -> None:
        """2026-08-14: 腾讯唯一源 — Tencent 返回空 → 直接 FAILED，无新浪兜底."""
        monkeypatch.chdir(tmp_path)
        with patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx:
            mock_tx.return_value.fetch_raw.return_value = pd.DataFrame()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx())
        assert result.status.value == "failed"
        assert any("0 rows" in e or "network" in e for e in result.errors)


class TestAtomicWrite:
    def test_tmp_file_verified_before_rename(self, tmp_path, monkeypatch) -> None:
        """Broken tmp write → FAILED, tmp cleaned up, production untouched."""
        monkeypatch.chdir(tmp_path)
        clean_df = _real_clean_df()

        # Pre-seed a valid production file that must NOT be replaced
        out_dir = tmp_path / "data" / "dataset"
        out_dir.mkdir(parents=True)
        sentinel = pl.DataFrame({"symbol": ["SENTINEL"], "trade_date": ["2026-01-01"]})
        sentinel.write_parquet(out_dir / "daily_price_latest.parquet")

        with (
            patch("qp.data.adapter.tencent_adapter.TencentAdapter") as mock_tx,
            # write_parquet becomes a no-op → tmp file never created → verify fails
            patch(
                "qp.data.pipeline.pl.DataFrame.write_parquet",
                return_value=None,
            ),
        ):
            mock_tx.return_value.fetch_raw.return_value = clean_df.to_pandas()
            pipeline = DataPipeline()
            result = pipeline.run(_ctx())

        assert result.status.value == "failed"
        assert any("Atomic write" in e for e in result.errors)
        # Production file untouched (tmp never renamed over it)
        after = pl.read_parquet(out_dir / "daily_price_latest.parquet")
        assert after["symbol"].to_list() == ["SENTINEL"]
        # tmp cleaned up
        assert not (out_dir / "daily_price_latest.tmp.parquet").exists()
