"""BuildResult — output wrapper for DatasetBuilder.build()."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BuildResult:
    """Output of a DatasetBuilder.build() call.

    Attributes:
        success: True if the build completed without errors.
        dataset_name: Name of the built dataset.
        version: Version string assigned.
        path: Path to the output parquet file.
        metadata: DatasetMetadata serialized to dict at build time.
        rows: Number of rows in the output.
        symbols: Number of unique symbols.
        date_range: (min_date, max_date) tuple if derivable.
        errors: Accumulated error messages (empty on success).
        stats: Arbitrary build statistics for audit trail.
    """

    success: bool = False
    dataset_name: str = ""
    version: str = ""
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    rows: int = 0
    symbols: int = 0
    date_range: tuple[str, str] | None = None
    errors: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def summary(self) -> str:
        """Single-line summary for logging."""
        if self.success:
            return (
                f"✅ {self.dataset_name}@{self.version} "
                f"({self.rows} 行 × {self.symbols} 标的)"
            )
        return f"❌ {self.dataset_name}: {self.errors[0] if self.errors else 'unknown'}"
