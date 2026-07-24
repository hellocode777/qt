"""SchemaVersion & SchemaTracker — column definition version evolution.

Tracks every version of a dataset's schema: column names, types, primary key,
constraints. Provides historical lookups and diff capabilities.

Implements dp.md §7.7: "Everything Versioned: Dataset, Metadata, Contract, Validation"

Usage::

    from qp.data.metadata import SchemaTracker, SchemaVersion

    tracker = SchemaTracker()
    v1 = SchemaVersion(
        dataset_name="daily_price", version="2026-07-01",
        columns={"trade_date": "date", "symbol": "str", "close": "float64"},
        primary_key=["trade_date", "symbol"],
    )
    tracker.record(v1)
    history = tracker.get_history("daily_price")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class SchemaVersion:
    """A snapshot of a dataset's schema at a point in time.

    Attributes:
        dataset_name: Name of the dataset (e.g. 'daily_price').
        version: Version string (ISO date or semver).
        recorded_at: When this schema was recorded (ISO UTC).
        columns: Dict of column_name → dtype_string.
        primary_key: List of primary key columns.
        nullable_columns: Columns that may contain null values.
        constraints: Dict of column_name → constraint description.
        previous_version: Version string of the prior schema (for diff).
        changes: Human-readable list of changes from previous version.
    """

    dataset_name: str
    version: str
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    columns: dict[str, str] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)
    nullable_columns: list[str] = field(default_factory=list)
    constraints: dict[str, str] = field(default_factory=dict)
    previous_version: str = ""
    changes: list[str] = field(default_factory=list)

    # ── Diff ──

    def diff(self, other: SchemaVersion) -> list[str]:
        """Compute changes between this schema and another.

        Args:
            other: The schema to compare against.

        Returns:
            List of human-readable change descriptions.
        """
        changes: list[str] = []

        # Added columns
        added = set(self.columns.keys()) - set(other.columns.keys())
        for col in sorted(added):
            changes.append(f"新增列 '{col}' ({self.columns[col]})")

        # Removed columns
        removed = set(other.columns.keys()) - set(self.columns.keys())
        for col in sorted(removed):
            changes.append(f"移除列 '{col}' ({other.columns[col]})")

        # Type changes
        common = set(self.columns.keys()) & set(other.columns.keys())
        for col in sorted(common):
            if self.columns[col] != other.columns[col]:
                changes.append(f"列 '{col}' 类型变更: {other.columns[col]} → {self.columns[col]}")

        # Primary key changes
        if self.primary_key != other.primary_key:
            changes.append(f"主键变更: {other.primary_key} → {self.primary_key}")

        return changes

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "version": self.version,
            "recorded_at": self.recorded_at,
            "columns": self.columns,
            "primary_key": self.primary_key,
            "nullable_columns": self.nullable_columns,
            "constraints": self.constraints,
            "previous_version": self.previous_version,
            "changes": self.changes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaVersion:
        valid_keys = {f.name for f in __import__("dataclasses").fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class SchemaTracker:
    """Records and queries schema evolution for datasets.

    Tracks every time a dataset's schema changes: new columns, removed
    columns, type changes, constraint additions.

    Usage::

        tracker = SchemaTracker()
        tracker.record(SchemaVersion(
            dataset_name="daily_price", version="2026-07-01",
            columns={"trade_date": "date", "symbol": "str", "close": "float64"},
            primary_key=["trade_date", "symbol"],
        ))
        latest = tracker.get_latest("daily_price")
        history = tracker.get_history("daily_price")
    """

    def __init__(self, store_path: str | Path = "data/metadata/schemas.json") -> None:
        self._store_path = Path(store_path)
        self._schemas: dict[str, list[SchemaVersion]] = {}
        self._load_from_disk()

    # ── Record ──

    def record(self, schema: SchemaVersion) -> None:
        """Record a schema version. Auto-computes diff from latest previous version.

        Args:
            schema: SchemaVersion to record.
        """
        if schema.dataset_name not in self._schemas:
            self._schemas[schema.dataset_name] = []

        history = self._schemas[schema.dataset_name]
        if history:
            prev = history[-1]
            schema.previous_version = prev.version
            schema.changes = schema.diff(prev)

        history.append(schema)
        self._save_to_disk()
        logger.info(
            "Schema 已记录: {}@{} ({} 列, {} 变更)",
            schema.dataset_name,
            schema.version,
            len(schema.columns),
            len(schema.changes),
        )

    # ── Queries ──

    def get_latest(self, dataset_name: str) -> SchemaVersion | None:
        """Get the most recent schema version for a dataset."""
        history = self._schemas.get(dataset_name, [])
        return history[-1] if history else None

    def get_version(self, dataset_name: str, version: str) -> SchemaVersion | None:
        """Get a specific schema version by exact match."""
        for sv in self._schemas.get(dataset_name, []):
            if sv.version == version:
                return sv
        return None

    def get_history(self, dataset_name: str) -> list[SchemaVersion]:
        """Return all recorded schema versions for a dataset, oldest first."""
        return list(self._schemas.get(dataset_name, []))

    def diff_versions(self, dataset_name: str, version_a: str, version_b: str) -> list[str]:
        """Diff two specific schema versions of the same dataset.

        Returns:
            List of change descriptions, or empty if either version is not found.
        """
        sv_a = self.get_version(dataset_name, version_a)
        sv_b = self.get_version(dataset_name, version_b)
        if sv_a is None or sv_b is None:
            return []
        return sv_a.diff(sv_b)

    def list_datasets(self) -> list[str]:
        """Return sorted list of dataset names with recorded schemas."""
        return sorted(self._schemas.keys())

    # ── Persistence ──

    def _save_to_disk(self) -> None:
        """Persist all schemas to JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "datasets": {
                name: [sv.to_dict() for sv in versions] for name, versions in self._schemas.items()
            },
        }
        self._store_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_disk(self) -> None:
        """Load schemas from JSON file if it exists."""
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for name, versions in data.get("datasets", {}).items():
                self._schemas[name] = [SchemaVersion.from_dict(v) for v in versions]
            total = sum(len(v) for v in self._schemas.values())
            logger.debug("已从磁盘加载 {} 个 Schema 版本", total)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Schema 元数据加载失败 ({}), 使用空注册表", e)

    def __len__(self) -> int:
        return sum(len(v) for v in self._schemas.values())
