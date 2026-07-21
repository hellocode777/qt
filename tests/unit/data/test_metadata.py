"""Tests for qp.data.metadata — SourceMetadata, SchemaTracker, LineageTracker."""
from __future__ import annotations

import pytest

from qp.data.metadata import (
    DataLineage,
    LineageTracker,
    SchemaTracker,
    SchemaVersion,
    SourceMetadata,
    SourceMetadataStore,
)

# ==================================================================
# Helpers
# ==================================================================


def _make_schema_v1() -> SchemaVersion:
    return SchemaVersion(
        dataset_name="daily_price",
        version="2026-07-01",
        columns={
            "trade_date": "date",
            "symbol": "str",
            "close": "float64",
        },
        primary_key=["trade_date", "symbol"],
    )


def _make_schema_v2() -> SchemaVersion:
    return SchemaVersion(
        dataset_name="daily_price",
        version="2026-07-02",
        columns={
            "trade_date": "date",
            "symbol": "str",
            "close": "float64",
            "volume": "float64",  # Added column
        },
        primary_key=["trade_date", "symbol"],
    )


# ==================================================================
# Test SourceMetadata
# ==================================================================


class TestSourceMetadata:
    def test_record_fetch_success(self):
        meta = SourceMetadata(source_name="akshare")
        meta.record_fetch_success(latency_seconds=1.5)
        assert meta.consecutive_failures == 0
        assert meta.health_status == "healthy"
        assert meta.last_fetch_success != ""

    def test_record_fetch_failure(self):
        meta = SourceMetadata(source_name="akshare")
        meta.record_fetch_failure("timeout")
        assert meta.fetch_error_count == 1
        assert meta.consecutive_failures == 1
        assert meta.health_status == "degraded"

    def test_health_transitions_to_unhealthy(self):
        meta = SourceMetadata(source_name="akshare")
        for _ in range(3):
            meta.record_fetch_failure("err")
        assert meta.health_status == "unhealthy"
        assert not meta.is_healthy()
        assert meta.consecutive_failures == 3

    def test_health_recovers_after_success(self):
        meta = SourceMetadata(source_name="akshare")
        for _ in range(3):
            meta.record_fetch_failure("err")
        assert meta.health_status == "unhealthy"
        # Now succeed
        meta.record_fetch_success()
        assert meta.health_status == "healthy"
        assert meta.is_healthy()

    def test_is_healthy(self):
        meta = SourceMetadata(source_name="akshare")
        assert meta.is_healthy()
        meta.health_status = "degraded"
        assert meta.is_healthy()  # degraded still returns True
        meta.health_status = "unhealthy"
        assert not meta.is_healthy()

    def test_to_dict_roundtrip(self):
        meta = SourceMetadata(source_name="akshare", data_kind="daily_ohlcv")
        d = meta.to_dict()
        assert d["source_name"] == "akshare"
        assert d["data_kind"] == "daily_ohlcv"
        restored = SourceMetadata.from_dict(d)
        assert restored.source_name == meta.source_name
        assert restored.data_kind == meta.data_kind

    def test_record_failure_without_error_message(self):
        meta = SourceMetadata(source_name="demo")
        meta.record_fetch_failure()  # no error message
        assert meta.consecutive_failures == 1
        # health_notes should remain default (empty), not be None
        assert meta.health_notes == ""

    def test_avg_latency_ema(self):
        meta = SourceMetadata(source_name="demo")
        meta.record_fetch_success(latency_seconds=2.0)
        assert meta.avg_latency_seconds == 2.0
        meta.record_fetch_success(latency_seconds=4.0)
        # EMA: 0.8 * 2.0 + 0.2 * 4.0 = 1.6 + 0.8 = 2.4
        assert meta.avg_latency_seconds == pytest.approx(2.4)


# ==================================================================
# Test SourceMetadataStore
# ==================================================================


class TestSourceMetadataStore:
    def test_register_and_get(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="akshare", data_kind="daily"))
        m = store.get("akshare")
        assert m is not None
        assert m.data_kind == "daily"

    def test_duplicate_register_raises(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="akshare"))
        with pytest.raises(ValueError, match="已存在"):
            store.register(SourceMetadata(source_name="akshare"))

    def test_record_success_updates_health(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.record_failure("akshare", "oops")
        store.record_failure("akshare", "oops")
        assert store.get("akshare").health_status == "degraded"  # type: ignore[union-attr]
        store.record_success("akshare")
        assert store.get("akshare").health_status == "healthy"  # type: ignore[union-attr]

    def test_record_success_auto_creates(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.record_success("new_source")
        assert "new_source" in store
        assert store.get("new_source").health_status == "healthy"  # type: ignore[union-attr]

    def test_record_failure_auto_creates(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.record_failure("new_source", "error")
        assert "new_source" in store
        assert store.get("new_source").consecutive_failures == 1  # type: ignore[union-attr]

    def test_list_sources(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="b"))
        store.register(SourceMetadata(source_name="a"))
        assert store.list_sources() == ["a", "b"]

    def test_list_healthy(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="healthy"))
        store.register(SourceMetadata(source_name="sick"))
        for _ in range(3):
            store.record_failure("sick", "err")
        healthy = store.list_healthy()
        assert "healthy" in healthy
        assert "sick" not in healthy

    def test_health_summary(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="a"))
        store.record_failure("a", "err")
        assert store.health_summary() == {"a": "degraded"}

    def test_persistence_roundtrip(self, tmp_path):
        store_path = tmp_path / "sources.json"
        store = SourceMetadataStore(store_path=str(store_path))
        store.register(SourceMetadata(source_name="akshare", data_kind="daily"))
        store.record_success("akshare", latency_seconds=1.0)

        # Create a new instance against the same file
        store2 = SourceMetadataStore(store_path=str(store_path))
        assert len(store2) == 1
        m = store2.get("akshare")
        assert m is not None
        assert m.data_kind == "daily"
        assert m.health_status == "healthy"

    def test_contains(self, tmp_path):
        store = SourceMetadataStore(store_path=str(tmp_path / "sources.json"))
        store.register(SourceMetadata(source_name="akshare"))
        assert "akshare" in store
        assert "nonexistent" not in store


# ==================================================================
# Test SchemaVersion
# ==================================================================


class TestSchemaVersion:
    def test_diff_added_columns(self):
        v1 = _make_schema_v1()
        v2 = _make_schema_v2()
        changes = v2.diff(v1)
        assert any("volume" in c for c in changes)
        assert any("新增" in c for c in changes)

    def test_diff_removed_columns(self):
        v1 = _make_schema_v1()
        v2 = _make_schema_v2()
        # v1 has volume, v2 doesn't → from v2's perspective, volume was removed
        changes = v1.diff(v2)
        assert any("移除" in c and "volume" in c for c in changes)

    def test_diff_type_change(self):
        v1 = SchemaVersion(
            dataset_name="test", version="v1",
            columns={"a": "int64"}, primary_key=["a"],
        )
        v2 = SchemaVersion(
            dataset_name="test", version="v2",
            columns={"a": "float64"}, primary_key=["a"],
        )
        changes = v2.diff(v1)
        assert any("类型变更" in c for c in changes)

    def test_diff_no_changes(self):
        v1 = _make_schema_v1()
        v2 = _make_schema_v1()
        v2.version = "v2"
        changes = v2.diff(v1)
        assert changes == []

    def test_diff_primary_key_change(self):
        v1 = SchemaVersion(
            dataset_name="test", version="v1",
            columns={"a": "int64"}, primary_key=["a"],
        )
        v2 = SchemaVersion(
            dataset_name="test", version="v2",
            columns={"a": "int64"}, primary_key=["a", "b"],
        )
        changes = v2.diff(v1)
        assert any("主键变更" in c for c in changes)

    def test_to_dict(self):
        v1 = _make_schema_v1()
        d = v1.to_dict()
        assert d["dataset_name"] == "daily_price"
        assert d["columns"]["close"] == "float64"


# ==================================================================
# Test SchemaTracker
# ==================================================================


class TestSchemaTracker:
    def test_record_and_get_latest(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        tracker.record(_make_schema_v2())
        latest = tracker.get_latest("daily_price")
        assert latest is not None
        assert latest.version == "2026-07-02"
        assert "volume" in latest.columns

    def test_get_version_exact(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        tracker.record(_make_schema_v2())
        sv = tracker.get_version("daily_price", "2026-07-01")
        assert sv is not None
        assert sv.version == "2026-07-01"

    def test_get_version_not_found(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        assert tracker.get_version("daily_price", "nonexistent") is None

    def test_get_history(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        tracker.record(_make_schema_v2())
        history = tracker.get_history("daily_price")
        assert len(history) == 2
        assert history[0].version == "2026-07-01"
        assert history[1].version == "2026-07-02"

    def test_auto_diff_on_record(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        tracker.record(_make_schema_v2())
        v2 = tracker.get_latest("daily_price")
        assert v2 is not None
        assert len(v2.changes) > 0  # Auto-computed diff
        assert v2.previous_version == "2026-07-01"

    def test_diff_versions(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        tracker.record(_make_schema_v2())
        changes = tracker.diff_versions("daily_price", "2026-07-02", "2026-07-01")
        assert len(changes) > 0

    def test_diff_versions_not_found(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        assert tracker.diff_versions("x", "v1", "v2") == []

    def test_list_datasets(self, tmp_path):
        tracker = SchemaTracker(store_path=str(tmp_path / "schemas.json"))
        tracker.record(_make_schema_v1())
        v = SchemaVersion(
            dataset_name="another", version="v1",
            columns={"a": "int64"}, primary_key=["a"],
        )
        tracker.record(v)
        assert tracker.list_datasets() == ["another", "daily_price"]

    def test_persistence(self, tmp_path):
        store_path = tmp_path / "schemas.json"
        tracker = SchemaTracker(store_path=str(store_path))
        tracker.record(_make_schema_v1())

        tracker2 = SchemaTracker(store_path=str(store_path))
        assert len(tracker2) == 1
        sv = tracker2.get_latest("daily_price")
        assert sv is not None
        assert sv.version == "2026-07-01"


# ==================================================================
# Test DataLineage
# ==================================================================


class TestDataLineage:
    def test_chain_str(self):
        lineage = DataLineage(
            source_name="akshare",
            cleaning_run_id="clean_1234567890",
            validation_report_id="val_abc123",
            pit_correction_applied=True,
            dataset_name="daily_price",
            dataset_version="2026-07-20",
        )
        chain = lineage.chain_str()
        assert "akshare" in chain
        assert "daily_price@2026-07-20" in chain
        assert "PIT" in chain

    def test_chain_str_minimal(self):
        lineage = DataLineage()
        assert lineage.chain_str() == "(empty)"

    def test_to_dict(self):
        lineage = DataLineage(
            source_name="demo",
            dataset_name="test_ds",
            dataset_version="v1",
            tier_chain=["RAW", "BRONZE", "SILVER", "GOLD"],
        )
        d = lineage.to_dict()
        assert d["source_name"] == "demo"
        assert d["dataset_name"] == "test_ds"
        assert d["tier_chain"] == ["RAW", "BRONZE", "SILVER", "GOLD"]

    def test_from_dict(self):
        d = {
            "source_name": "akshare",
            "dataset_name": "daily_price",
            "dataset_version": "v1",
            "tier_chain": ["RAW", "GOLD"],
        }
        lineage = DataLineage.from_dict(d)
        assert lineage.source_name == "akshare"
        assert lineage.dataset_name == "daily_price"


# ==================================================================
# Test LineageTracker
# ==================================================================


class TestLineageTracker:
    def test_record_and_find_by_dataset(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        lineage = DataLineage(
            source_name="akshare",
            dataset_name="daily_price",
            dataset_version="2026-07-20",
        )
        tracker.record(lineage)
        results = tracker.find_by_dataset("daily_price")
        assert len(results) == 1
        assert results[0].source_name == "akshare"

    def test_find_by_dataset_with_version(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        v1 = DataLineage(dataset_name="ds", dataset_version="v1")
        v2 = DataLineage(dataset_name="ds", dataset_version="v2")
        tracker.record(v1)
        tracker.record(v2)

        assert len(tracker.find_by_dataset("ds", version="v1")) == 1
        assert len(tracker.find_by_dataset("ds")) == 2

    def test_find_by_source(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        tracker.record(DataLineage(source_name="akshare", dataset_name="a"))
        tracker.record(DataLineage(source_name="tencent", dataset_name="b"))

        assert len(tracker.find_by_source("akshare")) == 1
        assert tracker.find_by_source("akshare")[0].dataset_name == "a"

    def test_find_by_pipeline(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        tracker.record(DataLineage(
            pipeline_run_id="run_abc", dataset_name="ds",
        ))
        tracker.record(DataLineage(
            pipeline_run_id="run_xyz", dataset_name="ds",
        ))

        assert len(tracker.find_by_pipeline("run_abc")) == 1

    def test_trace_backward(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        lineage = DataLineage(
            source_name="akshare",
            dataset_name="daily_price",
            dataset_version="2026-07-20",
        )
        tracker.record(lineage)
        result = tracker.trace_backward("daily_price", "2026-07-20")
        assert result is not None
        assert result.source_name == "akshare"

    def test_trace_backward_not_found(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        assert tracker.trace_backward("nonexistent", "v1") is None

    def test_get_latest(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        tracker.record(DataLineage(
            dataset_name="ds", dataset_version="old",
        ))
        tracker.record(DataLineage(
            dataset_name="ds", dataset_version="new",
        ))
        latest = tracker.get_latest("ds")
        assert latest is not None
        assert latest.dataset_version == "new"

    def test_prune_older_than(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        # Add a recent record
        tracker.record(DataLineage(
            dataset_name="ds", dataset_version="v1",
        ))
        # Prune with very large days (should keep everything)
        removed = tracker.prune_older_than(days=9999)
        assert removed == 0
        assert tracker.count() == 1

    def test_persistence(self, tmp_path):
        store_path = tmp_path / "lineage.json"
        tracker = LineageTracker(store_path=str(store_path))
        tracker.record(DataLineage(
            source_name="akshare",
            dataset_name="daily_price",
            dataset_version="2026-07-20",
        ))

        tracker2 = LineageTracker(store_path=str(store_path))
        assert tracker2.count() == 1
        result = tracker2.find_by_dataset("daily_price")
        assert len(result) == 1
        assert result[0].source_name == "akshare"

    def test_list_datasets(self, tmp_path):
        tracker = LineageTracker(store_path=str(tmp_path / "lineage.json"))
        tracker.record(DataLineage(dataset_name="b"))
        tracker.record(DataLineage(dataset_name="a"))
        tracker.record(DataLineage(dataset_name="a"))
        assert tracker.list_datasets() == ["a", "b"]
