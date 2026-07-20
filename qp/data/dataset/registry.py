"""DatasetRegistry — tracks and resolves Dataset versions.

Datasets are identified by name + version. The registry maps these to
physical storage locations.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any


class DatasetRegistry:
    """Registry of available Data Products (Datasets)."""

    def __init__(self, base_dir: str | Path = "data/dataset") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        version: str,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a new dataset version.

        Args:
            name: Dataset name (e.g. 'daily_price').
            version: Version string (e.g. '2026-07-20').
            path: Path to the dataset file.
            metadata: Optional metadata dict.
        """
        key = f"{name}@{version}"
        self._entries[key] = {
            "name": name,
            "version": version,
            "path": str(path),
            "metadata": metadata or {},
            "registered_at": date.today().isoformat(),
        }

    def resolve(self, name: str, version: str | None = None) -> dict[str, Any]:
        """Resolve a dataset by name and optional version.

        Args:
            name: Dataset name.
            version: Version string. If None, returns the latest version.

        Returns:
            Dataset entry dict with name, version, path, metadata.

        Raises:
            KeyError: If the dataset is not found.
        """
        if version:
            key = f"{name}@{version}"
            if key in self._entries:
                return self._entries[key]
            raise KeyError(f"Dataset not found: {key}")

        # Find latest version
        matching = [(k, v) for k, v in self._entries.items() if v["name"] == name]
        if not matching:
            raise KeyError(f"Dataset not found: {name}")
        matching.sort(key=lambda x: x[1]["version"], reverse=True)
        return matching[0][1]

    def list_datasets(self) -> list[str]:
        """List all registered dataset names."""
        return sorted({v["name"] for v in self._entries.values()})

    def list_versions(self, name: str) -> list[str]:
        """List all versions of a dataset."""
        return sorted(
            [v["version"] for v in self._entries.values() if v["name"] == name],
            reverse=True,
        )
