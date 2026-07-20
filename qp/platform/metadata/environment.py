"""Environment metadata — OS, CPU, memory, disk info."""

from __future__ import annotations

import os
import shutil


class EnvironmentMeta:
    """Metadata about the host environment."""

    def __init__(self) -> None:
        self.cpu_count: int = os.cpu_count() or 0
        self.cwd: str = os.getcwd()

    @property
    def disk_free_gb(self) -> float:
        """Available disk space in GB."""
        usage = shutil.disk_usage(self.cwd)
        return usage.free / (1024**3)

    def to_dict(self) -> dict[str, object]:
        """Export environment metadata as a dict."""
        return {
            "cpu_count": self.cpu_count,
            "cwd": self.cwd,
            "disk_free_gb": round(self.disk_free_gb, 2),
        }
