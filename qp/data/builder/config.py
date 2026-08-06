"""BuildConfig and DatasetMetadata — configuration for Dataset assembly.

Implements dp.md §7.7: "No Contract, No Publication" — each published
Dataset must carry 12 metadata fields defining its provenance, schema,
and quality guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from qp.shared.types import DataTier


@dataclass
class DatasetMetadata:
    """12 metadata fields required for every Data Product (dp.md §7.7).

    Attributes:
        name: Dataset identifier (e.g. 'daily_price').
        owner: Responsible team or individual.
        source: Source adapter name (e.g. 'akshare', 'tencent').
        schema: Dict of column_name → dtype_string.
        frequency: Data frequency (e.g. 'daily', 'minute', 'quarterly').
        primary_key: List of columns forming the primary key.
        timezone: Timezone of the data.
        coverage_start: Earliest available date.
        coverage_end: Latest available date.
        pit_confidence: How reliable is PIT alignment ('high', 'medium', 'low').
        update_policy: How the dataset is refreshed (e.g. 'daily_append').
        validation_rules: List of rule names that must pass.
        version: Version string (ISO date or semver).
    """

    name: str
    owner: str
    source: str
    schema: dict[str, str]
    frequency: str
    primary_key: list[str]
    timezone: str = "Asia/Shanghai"
    coverage_start: date | None = None
    coverage_end: date | None = None
    pit_confidence: str = "high"
    update_policy: str = "daily_append"
    validation_rules: list[str] = field(default_factory=list)
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "name": self.name,
            "owner": self.owner,
            "source": self.source,
            "schema": self.schema,
            "frequency": self.frequency,
            "primary_key": self.primary_key,
            "timezone": self.timezone,
            "coverage_start": str(self.coverage_start) if self.coverage_start else None,
            "coverage_end": str(self.coverage_end) if self.coverage_end else None,
            "pit_confidence": self.pit_confidence,
            "update_policy": self.update_policy,
            "validation_rules": self.validation_rules,
            "version": self.version,
        }

    def validate(self) -> list[str]:
        """Check that all required metadata fields are present.

        Returns:
            List of validation error messages. Empty = valid.
        """
        errors: list[str] = []
        if not self.name:
            errors.append("name 不能为空")
        if not self.owner:
            errors.append("owner 不能为空")
        if not self.source:
            errors.append("source 不能为空")
        if not self.schema:
            errors.append("schema 不能为空（至少需要一个字段定义）")
        if not self.frequency:
            errors.append("frequency 不能为空")
        if not self.primary_key:
            errors.append("primary_key 不能为空（至少需要一个主键列）")
        if self.pit_confidence not in ("high", "medium", "low", ""):
            errors.append(
                f"pit_confidence 非法值 '{self.pit_confidence}'（期望: high/medium/low）"
            )
        return errors


@dataclass
class BuildConfig:
    """Configuration for the DatasetBuilder.

    Attributes:
        tier: Target DataTier for the output (SILVER or GOLD).
        output_dir: Directory for built dataset files.
        require_contract: If True, refuse builds without a registered contract.
        fail_on_validation_error: If True, halt on any contract validation failure.
        persist_metadata: Write a _metadata.json alongside the parquet file.
    """

    tier: DataTier = DataTier.GOLD
    output_dir: str = "data/dataset"
    require_contract: bool = True
    fail_on_validation_error: bool = True
    persist_metadata: bool = True
