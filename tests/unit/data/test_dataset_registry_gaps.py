# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.dataset.registry — coverage gaps (prune/save/load/require_exists)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import polars as pl
import pytest

from qp.data.dataset.registry import DatasetRegistry, _resolve_file_path


def _make_registry(base: Path) -> DatasetRegistry:
    r = DatasetRegistry(base_dir=base)
    r.register("daily_price", "2026-07-01", path=str(base / "v1.parquet"))
    r.register("daily_price", "2026-07-02", path=str(base / "v2.parquet"))
    return r


class TestRequireExists:
    def test_resolve_latest_with_require_exists_skips_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            # Only v1 exists on disk
            pl.DataFrame({"a": [1]}).write_parquet(base / "v1.parquet")

            entry = r.resolve("daily_price", require_exists=True)
            assert entry["version"] == "2026-07-01"

    def test_resolve_specific_version_require_exists_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            with pytest.raises(KeyError, match="file not found"):
                r.resolve("daily_price", "2026-07-02", require_exists=True)

    def test_resolve_require_exists_no_valid_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)  # no files on disk
            with pytest.raises(KeyError, match="no version has a valid file"):
                r.resolve("daily_price", require_exists=True)


class TestPrune:
    def test_prune_removes_stale_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            pl.DataFrame({"a": [1]}).write_parquet(base / "v1.parquet")
            # v2 has no file → pruned
            removed = r.prune()
            assert removed == 1
            assert r.list_versions("daily_price") == ["2026-07-01"]

    def test_prune_no_stale_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            pl.DataFrame({"a": [1]}).write_parquet(base / "v1.parquet")
            pl.DataFrame({"a": [1]}).write_parquet(base / "v2.parquet")
            assert r.prune() == 0

    def test_prune_persists_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            pl.DataFrame({"a": [1]}).write_parquet(base / "v1.parquet")
            r.prune()
            # Reload from disk → v2 gone
            r2 = DatasetRegistry(base_dir=base)
            assert r2.list_versions("daily_price") == ["2026-07-01"]


class TestSaveLoad:
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            r = _make_registry(base)
            out = base / "backup.json"
            r.save(out)
            restored = DatasetRegistry.load(out)
            assert restored.count == 2
            assert restored.resolve("daily_price")["version"] == "2026-07-02"

    def test_load_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, pytest.raises(FileNotFoundError):
            DatasetRegistry.load(Path(tmp) / "nope.json")


class TestDunderAndCount:
    def test_count_and_len(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = _make_registry(Path(tmp))
            assert r.count == 2
            assert len(r) == 2

    def test_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = _make_registry(Path(tmp))
            assert "daily_price" in r
            assert "fundamentals" not in r

    def test_corrupt_registry_file_resets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "registry.json").write_text("{bad json", encoding="utf-8")
            r = DatasetRegistry(base_dir=base)
            assert r.count == 0


class TestResolveFilePath:
    def test_absolute_path_returned_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.parquet"
            p.write_bytes(b"x")
            assert _resolve_file_path({"path": str(p)}, Path(tmp)) == p

    def test_relative_existing_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            p = base / "data" / "x.parquet"
            p.parent.mkdir(parents=True)
            p.write_bytes(b"x")
            # Entry stores path relative to CWD, file exists as-is
            assert _resolve_file_path({"path": str(p)}, base) == p

    def test_fallback_prepends_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            joined = base / "x.parquet"
            joined.write_bytes(b"x")
            # Entry stores bare filename → prepend base_dir
            assert _resolve_file_path({"path": "x.parquet"}, base) == joined
