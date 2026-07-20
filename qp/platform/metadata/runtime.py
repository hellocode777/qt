"""Runtime metadata — system info at startup time."""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime


class RuntimeMeta:
    """Metadata about the current runtime environment."""

    def __init__(self) -> None:
        self.start_time: datetime = datetime.now(UTC)
        self.python_version: str = sys.version
        self.platform: str = platform.platform()
        self.processor: str = platform.processor() or "unknown"

    def to_dict(self) -> dict[str, str]:
        """Export runtime metadata as a dict."""
        return {
            "start_time": self.start_time.isoformat(),
            "python_version": self.python_version,
            "platform": self.platform,
            "processor": self.processor,
        }
