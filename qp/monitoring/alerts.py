"""Alert Channels — multi-channel alerting for monitoring events.

Provides three alert channels (Terminal, Log, Telegram) and an AlertManager
that routes alerts by severity.

Rule: secrets (Telegram API keys) come from environment variables only.
See rule.md §10.1.

Usage:
    manager = AlertManager()
    manager.add_channel(TerminalAlert())
    manager.add_channel(LogAlert(logger))
    manager.send(Alert.severity.WARNING, "Model Decay", "OOS IC dropped to 0.012")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


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

    def format_short(self) -> str:
        """Short one-line format."""
        return f"[{self.severity.value.upper()}] {self.title}: {self.message}"

    def format_detailed(self) -> str:
        """Multi-line detailed format with metadata."""
        lines = [
            f"=== {self.severity.value.upper()} ALERT ===",
            f"Time: {self.timestamp}",
            f"Source: {self.source}",
            f"Title: {self.title}",
            f"Message: {self.message}",
        ]
        if self.metadata:
            lines.append("Metadata:")
            for k, v in self.metadata.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Alert channels
# ------------------------------------------------------------------


class _BaseAlertChannel(ABC):
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


class TerminalAlert(_BaseAlertChannel):
    """Sends alerts to terminal with ANSI color coding.

    Usage:
        channel = TerminalAlert(use_colors=True)
        channel.send(alert)
    """

    # ANSI color codes
    _COLORS = {
        AlertSeverity.INFO: "\033[34m",  # Blue
        AlertSeverity.WARNING: "\033[33m",  # Yellow
        AlertSeverity.CRITICAL: "\033[31m",  # Red
    }
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    def __init__(self, use_colors: bool = True) -> None:
        self._use_colors = use_colors

    def send(self, alert: Alert) -> bool:
        """Print alert to terminal with color."""
        if self._use_colors:
            color = self._COLORS.get(alert.severity, "")
            print(
                f"{color}{self._BOLD}[{alert.severity.value.upper()}]{self._RESET} "
                f"{alert.title}: {alert.message}"
            )
        else:
            print(alert.format_short())
        return True

    def test(self) -> bool:
        """Send test alert."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            title="Test Alert",
            message="Terminal alert channel is working.",
            source="alerts.test",
        )
        return self.send(alert)


class LogAlert(_BaseAlertChannel):
    """Sends alerts via structured logging (Loguru).

    Usage:
        from qp.platform.logging import get_logger
        channel = LogAlert(logger_instance)
        channel.send(alert)
    """

    def __init__(self, logger: object | None = None) -> None:
        """Initialize with optional logger instance.

        Args:
            logger: A Loguru logger instance. If None, uses default loguru.
        """
        self._logger = logger

    def send(self, alert: Alert) -> bool:
        """Log alert as structured log entry."""
        try:
            log_func = self._get_log_function(alert.severity)

            log_func(  # type: ignore[operator]
                alert.format_short(),
                extra={
                    "alert_severity": alert.severity.value,
                    "alert_title": alert.title,
                    "alert_source": alert.source,
                    "alert_timestamp": alert.timestamp,
                    **alert.metadata,
                },
            )
            return True
        except Exception:
            # Fallback: print if logging fails
            print(f"[LOG FALLBACK] {alert.format_short()}")
            return False

    def test(self) -> bool:
        """Send test log alert."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            title="Test Alert",
            message="Log alert channel is working.",
            source="alerts.test",
        )
        return self.send(alert)

    def _get_log_function(self, severity: AlertSeverity):  # type: ignore[return-type]
        """Get the right log function for severity."""
        from loguru import logger

        log_map: dict[AlertSeverity, object] = {
            AlertSeverity.INFO: logger.info,
            AlertSeverity.WARNING: logger.warning,
            AlertSeverity.CRITICAL: logger.critical,
        }
        if self._logger:
            # Use provided logger's methods
            log_map = {
                AlertSeverity.INFO: self._logger.info,  # type: ignore[union-attr]
                AlertSeverity.WARNING: self._logger.warning,  # type: ignore[union-attr]
                AlertSeverity.CRITICAL: self._logger.critical,  # type: ignore[union-attr]
            }
        return log_map.get(severity, logger.info)


class TelegramAlert(_BaseAlertChannel):
    """Sends alerts via Telegram Bot API.

    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
    See rule.md: secrets come from environment variables only.

    Usage:
        # Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        channel = TelegramAlert()
        channel.send(alert)
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Initialize Telegram alert channel.

        Args:
            bot_token: Telegram Bot API token (or from env TELEGRAM_BOT_TOKEN).
            chat_id: Target chat ID (or from env TELEGRAM_CHAT_ID).
        """
        import os

        self._token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    def send(self, alert: Alert) -> bool:
        """Send alert as Telegram message."""
        if not self._token or not self._chat_id:
            # Silent fail — Telegram not configured
            return False

        # Format message with severity emoji
        emoji = {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🚨",
        }.get(alert.severity, "📢")

        text = (
            f"{emoji} *{alert.severity.value.upper()}*: {alert.title}\n"
            f"{alert.message}\n"
            f"_{alert.source} | {alert.timestamp[:19]}_"
        )

        try:
            import json as _json
            import urllib.request

            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            payload = _json.dumps({
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def test(self) -> bool:
        """Send a test message to verify Telegram configuration."""
        if not self._token or not self._chat_id:
            print("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
            return False

        alert = Alert(
            severity=AlertSeverity.INFO,
            title="Test Alert",
            message="Telegram alert channel is working. ✅",
            source="alerts.test",
        )
        success = self.send(alert)
        if success:
            print("Telegram test alert sent successfully.")
        else:
            print("Telegram test alert failed — check credentials and network.")
        return success

    @property
    def is_configured(self) -> bool:
        """True if Telegram credentials are available."""
        return bool(self._token and self._chat_id)


# ------------------------------------------------------------------
# Alert Manager
# ------------------------------------------------------------------


class AlertManager:
    """Routes alerts to multiple channels based on severity.

    Supports per-channel severity filtering: e.g., CRITICAL alerts
    go to all channels, INFO only to logs.

    Usage:
        manager = AlertManager()
        manager.add_channel(TerminalAlert(), min_severity=AlertSeverity.WARNING)
        manager.add_channel(LogAlert(logger))
        manager.add_channel(TelegramAlert(), min_severity=AlertSeverity.CRITICAL)

        manager.info("Daily check passed", "All systems normal")
        manager.warning("Model Decay", "OOS IC 0.012 < 0.010 threshold")
        manager.critical("Kill Switch", "Drawdown -22% exceeded limit")
    """

    def __init__(self) -> None:
        self._channels: list[tuple[_BaseAlertChannel, AlertSeverity | None]] = []

    def add_channel(
        self,
        channel: _BaseAlertChannel,
        min_severity: AlertSeverity | None = None,
    ) -> None:
        """Register an alert channel.

        Args:
            channel: The alert channel instance.
            min_severity: Minimum severity to route to this channel.
                None means all severities.
        """
        self._channels.append((channel, min_severity))

    def send(self, alert: Alert) -> dict[str, bool]:
        """Route an alert to all eligible channels.

        Returns:
            Dict mapping channel type to delivery success.
        """
        results: dict[str, bool] = {}
        for channel, min_sev in self._channels:
            if min_sev is None or self._severity_rank(alert.severity) >= self._severity_rank(min_sev):
                ch_name = type(channel).__name__
                results[ch_name] = channel.send(alert)
        return results

    # Convenience methods
    def info(self, title: str, message: str, source: str = "monitoring", **metadata: str) -> dict[str, bool]:
        """Send INFO alert."""
        return self.send(Alert(AlertSeverity.INFO, title, message, source, metadata=metadata))

    def warning(self, title: str, message: str, source: str = "monitoring", **metadata: str) -> dict[str, bool]:
        """Send WARNING alert."""
        return self.send(Alert(AlertSeverity.WARNING, title, message, source, metadata=metadata))

    def critical(self, title: str, message: str, source: str = "monitoring", **metadata: str) -> dict[str, bool]:
        """Send CRITICAL alert."""
        return self.send(Alert(AlertSeverity.CRITICAL, title, message, source, metadata=metadata))

    def test_all(self) -> dict[str, bool]:
        """Send test alerts to all channels."""
        results: dict[str, bool] = {}
        for channel, _ in self._channels:
            ch_name = type(channel).__name__
            results[ch_name] = channel.test()
        return results

    @staticmethod
    def _severity_rank(severity: AlertSeverity) -> int:
        return {AlertSeverity.INFO: 0, AlertSeverity.WARNING: 1, AlertSeverity.CRITICAL: 2}[severity]

    @property
    def channel_count(self) -> int:
        """Number of registered channels."""
        return len(self._channels)
