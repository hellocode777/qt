"""Tests for qp.data.dataset.registry — DatasetRegistry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from qp.data.dataset.registry import DatasetRegistry


class TestRegister:
    def test_register_new_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register(
                name="daily_price",
                version="2024-07-21",
                path=f"{tmpdir}/daily_price_2024-07-21.parquet",
            )
            entry = registry.resolve("daily_price", "2024-07-21")
            assert entry["name"] == "daily_price"
            assert entry["version"] == "2024-07-21"

    def test_register_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register(
                name="daily_price",
                version="2024-07-21",
                path=f"{tmpdir}/test.parquet",
                metadata={"rows": 5000, "stocks": 100},
            )
            entry = registry.resolve("daily_price", "2024-07-21")
            assert entry["metadata"]["rows"] == 5000
            assert entry["metadata"]["stocks"] == 100

    def test_register_sets_registered_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("test", "v1", path=f"{tmpdir}/test.parquet")
            entry = registry.resolve("test", "v1")
            assert "registered_at" in entry


class TestResolve:
    def test_resolve_latest_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("daily_price", "2024-07-19", path=f"{tmpdir}/v1.parquet")
            registry.register("daily_price", "2024-07-20", path=f"{tmpdir}/v2.parquet")
            registry.register("daily_price", "2024-07-21", path=f"{tmpdir}/v3.parquet")

            latest = registry.resolve("daily_price")
            assert latest["version"] == "2024-07-21"

    def test_resolve_specific_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("daily_price", "2024-07-19", path=f"{tmpdir}/v1.parquet")
            registry.register("daily_price", "2024-07-21", path=f"{tmpdir}/v2.parquet")

            entry = registry.resolve("daily_price", "2024-07-19")
            assert entry["version"] == "2024-07-19"

    def test_resolve_missing_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            with pytest.raises(KeyError, match="Dataset not found"):
                registry.resolve("nonexistent")

    def test_resolve_missing_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("daily_price", "2024-07-19", path=f"{tmpdir}/v1.parquet")
            with pytest.raises(KeyError, match="Dataset not found"):
                registry.resolve("daily_price", "2024-07-99")


class TestList:
    def test_list_datasets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("daily_price", "2024-07-21", path=f"{tmpdir}/dp.parquet")
            registry.register(
                "fundamentals", "2024-07-21", path=f"{tmpdir}/fund.parquet"
            )

            names = registry.list_datasets()
            assert "daily_price" in names
            assert "fundamentals" in names

    def test_list_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            registry.register("daily_price", "2024-07-19", path=f"{tmpdir}/v1.parquet")
            registry.register("daily_price", "2024-07-20", path=f"{tmpdir}/v2.parquet")
            registry.register("daily_price", "2024-07-21", path=f"{tmpdir}/v3.parquet")

            versions = registry.list_versions("daily_price")
            assert len(versions) == 3
            # Sorted reverse
            assert versions[0] == "2024-07-21"
            assert versions[-1] == "2024-07-19"

    def test_list_versions_unknown_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            versions = registry.list_versions("unknown")
            assert versions == []

    def test_list_datasets_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = DatasetRegistry(base_dir=tmpdir)
            assert registry.list_datasets() == []


class TestBaseDir:
    def test_default_base_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "data" / "dataset"
            DatasetRegistry(base_dir=base)
            assert base.exists()
