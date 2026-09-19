"""DataLineage & LineageTracker — complete data provenance tracking.

Records the full chain from source adapter through cleaning, validation,
and PIT correction to the final published dataset.

Fills the gap identified in credibility_check.md §1:
  "日常 Pipeline 运行不记录数据版本"

Implements rule.md Rule 7:
  "所有决策、信号、策略与模型输出必须保持从数据源到最终 Order
   的完全可追溯数据血缘图谱。"

Usage::

    from qp.data.metadata import LineageTracker, DataLineage

    tracker = LineageTracker()
    lineage = DataLineage(
        source_name="akshare",
        dataset_name="daily_price",
        dataset_version="2026-07-20",
        pipeline_run_id="run_abc123",
    )
    tracker.record(lineage)

    # Trace backward from dataset to source
    chain = tracker.trace_backward("daily_price", "2026-07-20")
    print(chain.chain_str())  # akshare → ... → daily_price@2026-07-20
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from qp.shared.paths import LINEAGE_JSON
from qp.shared.time import fmt_ts, now_utc, utc_iso


@dataclass
class DataLineage:
    """Complete chain from source to final dataset.

    Attributes:
        lineage_id: Unique identifier for this lineage record.
        recorded_at: When this lineage was recorded (ISO UTC).
        source_name: Source adapter name (e.g. 'akshare').
        source_version: Version of the raw data fetched.
        cleaning_run_id: ID of the cleaning run (from audit).
        validation_report_id: ID of the validation report.
        pit_correction_applied: Whether PIT correction was applied.
        dataset_name: Final dataset name.
        dataset_version: Final dataset version.
        tier_chain: List of tiers the data passed through (RAW, BRONZE, SILVER, GOLD).
        pipeline_run_id: Pipeline run that produced this data.
        params: Arbitrary parameters used in the build (e.g. start_date, symbols).
        notes: Human-readable notes.
    """

    lineage_id: str = field(default_factory=lambda: fmt_ts(now_utc(), sep="T"))
    recorded_at: str = field(default_factory=utc_iso)
    source_name: str = ""
    source_version: str = ""
    cleaning_run_id: str = ""
    validation_report_id: str = ""
    pit_correction_applied: bool = False
    dataset_name: str = ""
    dataset_version: str = ""
    tier_chain: list[str] = field(default_factory=list)
    pipeline_run_id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def chain_str(self) -> str:
        """Human-readable lineage chain.

        Returns:
            String like 'akshare → cleaning(abc123) → validation(xyz) → daily_price@2026-07-20'
        """
        parts: list[str] = [self.source_name] if self.source_name else []
        if self.cleaning_run_id:
            parts.append(f"cleaning({self.cleaning_run_id[:8]})")
        if self.validation_report_id:
            parts.append(f"validation({self.validation_report_id[:8]})")
        if self.pit_correction_applied:
            parts.append("PIT")
        if self.dataset_name:
            version_suffix = f"@{self.dataset_version}" if self.dataset_version else ""
            parts.append(f"{self.dataset_name}{version_suffix}")
        return " → ".join(parts) if parts else "(empty)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "recorded_at": self.recorded_at,
            "source_name": self.source_name,
            "source_version": self.source_version,
            "cleaning_run_id": self.cleaning_run_id,
            "validation_report_id": self.validation_report_id,
            "pit_correction_applied": self.pit_correction_applied,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "tier_chain": self.tier_chain,
            "pipeline_run_id": self.pipeline_run_id,
            "params": self.params,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataLineage:
        valid_keys = {f.name for f in __import__("dataclasses").fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


class LineageTracker:
    """Records and queries data lineage chains.

    Answers: "Where did this dataset come from and what transformations
    were applied to it?"

    Every pipeline run should record a DataLineage entry so downstream
    consumers can trace their data back to its origin.
    """

    def __init__(self, store_path: str | Path = LINEAGE_JSON) -> None:
        self._store_path = Path(store_path)
        self._records: list[DataLineage] = []
        self._load_from_disk()

    # ── Record ──

    def record(self, lineage: DataLineage) -> None:
        """Record a data lineage entry.

        Args:
            lineage: DataLineage to record.
        """
        self._records.append(lineage)
        self._save_to_disk()
        logger.info("血缘记录已保存: {} (共 {} 条)", lineage.chain_str(), len(self._records))

    # ── Queries ──

    def find_by_dataset(self, dataset_name: str, version: str | None = None) -> list[DataLineage]:
        """Find all lineage records for a specific dataset.

        Args:
            dataset_name: Dataset name to search for.
            version: Optional version filter.

        Returns:
            Matching DataLineage records, most recent first.
        """
        results = [r for r in self._records if r.dataset_name == dataset_name]
        if version:
            results = [r for r in results if r.dataset_version == version]
        return sorted(results, key=lambda r: r.recorded_at, reverse=True)

    def find_by_source(self, source_name: str) -> list[DataLineage]:
        """Find all lineage records from a specific source adapter."""
        return sorted(
            [r for r in self._records if r.source_name == source_name],
            key=lambda r: r.recorded_at,
            reverse=True,
        )

    def find_by_pipeline(self, pipeline_run_id: str) -> list[DataLineage]:
        """Find all lineage records for a specific pipeline run."""
        return [r for r in self._records if r.pipeline_run_id == pipeline_run_id]

    def get_latest(self, dataset_name: str) -> DataLineage | None:
        """Get the most recent lineage record for a dataset."""
        matching = self.find_by_dataset(dataset_name)
        return matching[0] if matching else None

    def trace_backward(self, dataset_name: str, version: str) -> DataLineage | None:
        """Trace a dataset version back to its source.

        Args:
            dataset_name: Dataset name.
            version: Dataset version.

        Returns:
            DataLineage or None if not found.
        """
        matching = self.find_by_dataset(dataset_name, version=version)
        return matching[0] if matching else None

    def list_datasets(self) -> list[str]:
        """Return unique dataset names seen across all lineage records."""
        return sorted({r.dataset_name for r in self._records if r.dataset_name})

    def count(self) -> int:
        """Return total number of lineage records."""
        return len(self._records)

    def prune_older_than(self, days: int = 90) -> int:
        """Remove records older than N days.

        Args:
            days: Age threshold in days.

        Returns:
            Number of records removed.
        """
        before = len(self._records)
        threshold = datetime.now(UTC) - timedelta(days=days)
        threshold_str = threshold.isoformat()
        self._records = [r for r in self._records if r.recorded_at >= threshold_str]
        removed = before - len(self._records)
        if removed > 0:
            self._save_to_disk()
            logger.info("已清理 {} 条过期血缘记录 (>{} 天)", removed, days)
        return removed

    # ── Persistence ──

    def _save_to_disk(self) -> None:
        """Persist all lineage records to JSON file."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "records": [r.to_dict() for r in self._records],
        }
        self._store_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_disk(self) -> None:
        """Load lineage records from JSON file if it exists."""
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            self._records = [DataLineage.from_dict(r) for r in data.get("records", [])]
            logger.debug("已从磁盘加载 {} 条血缘记录", len(self._records))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("血缘数据加载失败 ({}), 使用空注册表", e)

    # ── Dunder ──

    def __len__(self) -> int:
        return len(self._records)
