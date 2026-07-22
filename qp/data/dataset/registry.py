"""DatasetRegistry — tracks and resolves Dataset versions.

Datasets are identified by name + version. The registry maps these to
physical storage locations.

Persistence: entries are automatically saved to <base_dir>/registry.json
on each register() call, and auto-loaded on init if the file exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DatasetRegistry:
    """Registry of available Data Products (Datasets).

    Usage:
        registry = DatasetRegistry()
        registry.register("daily_price", "v20260722", "/data/dp.parquet")
        entry = registry.resolve("daily_price")  # latest version

        # Persistence
        registry.save("backup.json")
        restored = DatasetRegistry.load("backup.json")
    """

    def __init__(self, base_dir: str | Path = "data/dataset") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, dict[str, Any]] = {}
        self._load_from_disk()

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
            "registered_at": datetime.now(UTC).isoformat(),
        }
        self._save_to_disk()

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

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @property
    def _registry_path(self) -> Path:
        """Path to the auto-save registry file."""
        return self._base_dir / "registry.json"

    def _save_to_disk(self) -> None:
        """Auto-persist entries to <base_dir>/registry.json."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "base_dir": str(self._base_dir),
            "entries": self._entries,
        }
        self._registry_path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_from_disk(self) -> None:
        """Load entries from <base_dir>/registry.json if it exists."""
        if not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            self._entries = data.get("entries", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            self._entries = {}

    def save(self, path: str | Path) -> None:
        """Persist the registry to a specific JSON file.

        Args:
            path: Destination file path.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "base_dir": str(self._base_dir),
            "entries": self._entries,
        }
        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> DatasetRegistry:
        """Load a registry from a JSON file.

        Args:
            path: Source file path.

        Returns:
            Restored DatasetRegistry instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        registry = cls(base_dir=data.get("base_dir", "data/dataset"))
        registry._entries = data.get("entries", {})
        return registry

    @property
    def count(self) -> int:
        """Number of registered dataset versions."""
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        matching = [v for v in self._entries.values() if v["name"] == name]
        return len(matching) > 0
