"""Alert module — re-export bridge from ``qp.monitoring.alerts``.

This module exists to satisfy the Walking Skeleton architectural
specification that alert infrastructure be accessible from
``qp.platform.alert`` (Layer 1).  The canonical implementation lives
in ``qp.monitoring.alerts`` (Layer 9 — monitoring observes, never
decides).  Both import paths are equivalent.

Usage:
    from qp.platform.alert import AlertManager, AlertSeverity

    am = AlertManager()
    am.critical("System down")
"""

from qp.monitoring.alerts import (
    Alert,
    AlertManager,
    AlertSeverity,
    DingTalkAlert,
    EmailAlert,
    FileAlert,
    LogAlert,
    TelegramAlert,
    TerminalAlert,
    WeComAlert,
)

__all__ = [
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "DingTalkAlert",
    "EmailAlert",
    "FileAlert",
    "LogAlert",
    "TelegramAlert",
    "TerminalAlert",
    "WeComAlert",
]
