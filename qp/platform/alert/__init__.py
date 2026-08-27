"""Alert protocol — severity, alert event, and channel contract.

This module defines the alerting protocol at the platform layer (Layer 1).
Concrete alert channels (Terminal / Log / Telegram / Email / DingTalk /
WeCom / File) and the AlertManager live in ``qp.monitoring.alerts``
(Layer 9 — monitoring observes, never decides) and implement this contract.

Dependency direction: ``qp.platform.alert`` depends on nothing inside the
project; ``qp.monitoring.alerts`` imports from here (monitoring → platform
is a legal downward dependency). This inverts the historical bridge where
the platform layer re-exported from monitoring (an upward dependency).

Usage:
    from qp.platform.alert import Alert, AlertSeverity, AlertChannel

    class MyChannel(AlertChannel):
        def send(self, alert: Alert) -> bool:
            ...
            return True

        def test(self) -> bool:
            return True
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

# 北京时间 (UTC+8) — 所有面向用户的通道显示用本地时间
BEIJING_TZ = timezone(timedelta(hours=8))


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    INFO = "info"  # Routine notification
    WARNING = "warning"  # Needs attention
    CRITICAL = "critical"  # Immediate action required


@dataclass
class Alert:
    """A monitoring alert event.

    Attributes:
        severity: Alert severity level.
        title: Short alert title.
        message: Detailed message body.
        source: Which subsystem generated the alert.
        timestamp: ISO-format timestamp.
        metadata: Arbitrary extra context.
    """

    severity: AlertSeverity
    title: str
    message: str
    source: str = "monitoring"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def display_time(self) -> str:
        """Beijing time (UTC+8) display string for human-facing channels."""
        return (
            datetime.fromisoformat(self.timestamp)
            .astimezone(BEIJING_TZ)
            .strftime("%Y-%m-%d %H:%M:%S")
        )

    def format_short(self) -> str:
        """Short one-line format."""
        return f"[{self.severity.value.upper()}] {self.title}: {self.message}"

    def format_detailed(self) -> str:
        """Multi-line detailed format with metadata."""
        lines = [
            f"=== {self.severity.value.upper()} ALERT ===",
            f"Time: {self.display_time} (北京时间)",
            f"Source: {self.source}",
            f"Title: {self.title}",
            f"Message: {self.message}",
        ]
        if self.metadata:
            lines.append("Metadata:")
            for k, v in self.metadata.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


class AlertChannel(ABC):
    """Abstract alert channel — all channels implement send()."""

    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Send an alert through this channel.

        Returns:
            True if successfully delivered, False otherwise.
        """
        ...

    @abstractmethod
    def test(self) -> bool:
        """Send a test alert to verify channel is working."""
        ...


__all__ = [
    "Alert",
    "AlertChannel",
    "AlertSeverity",
]
