"""HealthService — read-only access to system health and state data.

Bridges the QP Monitoring layer (Layer 9) to the Web layer.
"""

from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger

from qp.monitoring.system_state import SystemStateManager


class HealthService:
    """Read-only service for system health and state.

    Usage:
        svc = HealthService()
        state = svc.system_state()
        health = svc.latest_health()
        history = svc.health_history(limit=30)
    """

    def __init__(self) -> None:
        self._state_manager = SystemStateManager()

    # ------------------------------------------------------------------
    # System State
    # ------------------------------------------------------------------

    def system_state(self) -> dict[str, Any]:
        """Get current system state for display.

        Returns:
            Dict with state, label, is_blocked, reason, can_open_positions.
        """
        try:
            current = self._state_manager.current()
            stats = self._state_manager.stats()
        except Exception as e:
            logger.warning("Failed to read system state: {}", e)
            return _default_system_state()

        to_state = current.to_state

        return {
            "state": to_state.name,
            "label": to_state.label(),
            "is_blocked": not to_state.can_open_positions(),
            "can_open_positions": to_state.can_open_positions(),
            "can_close_positions": to_state.can_close_positions(),
            "reason": current.reason,
            "source": current.source,
            "timestamp": current.timestamp,
            "badge_class": _state_badge_class(to_state.name),
            "icon": _state_icon(to_state.name),
            "n_transitions": stats.get("n_transitions", 0),
            "last_source": stats.get("last_source", ""),
        }

    # ------------------------------------------------------------------
    # Health Log
    # ------------------------------------------------------------------

    def latest_health(self) -> dict[str, Any] | None:
        """Get the most recent system health log entry."""
        try:
            df = pl.read_parquet("data/monitoring/system_health_log.parquet")
            if df.is_empty():
                return None

            # Get latest row
            latest = df.sort("timestamp", descending=True).head(1).to_dicts()[0]
            return self._health_row_to_dict(latest)
        except Exception as e:
            logger.warning("Failed to read health log: {}", e)
            return None

    def health_history(self, limit: int = 30) -> list[dict[str, Any]]:
        """Get recent health log entries."""
        try:
            df = pl.read_parquet("data/monitoring/system_health_log.parquet")
            if df.is_empty():
                return []

            recent = df.sort("timestamp", descending=True).head(limit)
            return [self._health_row_to_dict(row) for row in recent.to_dicts()]
        except Exception as e:
            logger.warning("Failed to read health history: {}", e)
            return []

    # ------------------------------------------------------------------
    # Strategy Health (P1.4)
    # ------------------------------------------------------------------

    def strategy_health_list(self) -> list[dict[str, Any]]:
        """Load per-strategy health data from monitoring storage.

        Returns:
            List of strategy health dicts sorted by score (worst first).
            Each entry carries the record date (``data_date``) so stale
            records are distinguishable from current ones, and the trend
            is computed from actual history (not always "unknown").
        """
        try:
            from qp.monitoring.strategy_health_logger import StrategyHealthLogger

            logger_obj = StrategyHealthLogger()
            latest = logger_obj.load_latest_with_date()
        except Exception as e:
            logger.warning("Failed to load strategy health: {}", e)
            return []

        results: list[dict[str, Any]] = []
        for sid, (data_date, health) in latest.items():
            from qp.monitoring.strategy_health_report import StrategyHealthReport

            history = logger_obj.load_health_history(sid)
            report = StrategyHealthReport.from_health(health, history=history)
            d = report.to_dict()
            d["health_score_pct"] = int(health.health_score)
            d["health_badge"] = _health_score_badge_class(health.health_score)
            d["health_label"] = _health_score_label(health.health_score)
            d["health_level_display"] = health.health_level.value.upper()
            d["n_alerts"] = len(health.alerts)
            d["data_date"] = data_date
            results.append(d)

        results.sort(key=lambda x: x["health_score"])
        return results

    @staticmethod
    def _health_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        """Convert a health log row to template-friendly dict."""
        kill_level = row.get("kill_switch_level", "NORMAL")
        kill_triggered = row.get("kill_switch_triggered", False)
        action = row.get("action", "ok")
        health_score = row.get("strategy_health_score", 100.0)

        return {
            "date": row.get("date", ""),
            "timestamp": row.get("timestamp", ""),
            "psi_value": row.get("psi_value", 0.0),
            "psi_available": row.get("psi_available", False),
            "rolling_ic": row.get("rolling_ic", 0.0),
            "rolling_ic_available": row.get("rolling_ic_available", False),
            "regime": row.get("regime", "unknown"),
            "kill_switch_level": kill_level,
            "kill_switch_triggered": kill_triggered,
            "model_decay_stage": row.get("model_decay_stage", "HEALTHY"),
            "strategy_health_score": health_score,
            "health_score_pct": int(health_score),
            "action": action,
            "n_alerts": row.get("n_alerts", 0),
            "alerts_summary": row.get("alerts_summary", ""),
            # Display helpers
            "kill_level_badge": _kill_level_badge_class(kill_level),
            "kill_level_label": _kill_level_label(kill_level),
            "health_badge": _health_score_badge_class(health_score),
            "health_label": _health_score_label(health_score),
        }


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _state_badge_class(state: str) -> str:
    classes = {
        "NORMAL": "badge-green",
        "WARNING": "badge-yellow",
        "PAUSED": "badge-orange",
        "STOPPED": "badge-red",
        "RECOVERY": "badge-blue",
    }
    return classes.get(state, "badge-gray")


def _state_icon(state: str) -> str:
    icons = {
        "NORMAL": "🟢",
        "WARNING": "🟡",
        "PAUSED": "🟠",
        "STOPPED": "🔴",
        "RECOVERY": "🔵",
    }
    return icons.get(state, "⚪")


def _kill_level_badge_class(level: str) -> str:
    classes = {
        "NORMAL": "badge-green",
        "WARNING": "badge-yellow",
        "HALT_BUY": "badge-orange",
        "FULL_STOP": "badge-red",
    }
    return classes.get(level, "badge-gray")


def _kill_level_label(level: str) -> str:
    labels = {
        "NORMAL": "正常 / NORMAL",
        "WARNING": "警告 / WARNING",
        "HALT_BUY": "暂停买入 / HALT BUY",
        "FULL_STOP": "紧急熔断 / FULL STOP",
    }
    return labels.get(level, level)


def _health_score_badge_class(score: float) -> str:
    if score >= 80:
        return "badge-green"
    if score >= 60:
        return "badge-yellow"
    if score >= 40:
        return "badge-orange"
    return "badge-red"


def _health_score_label(score: float) -> str:
    if score >= 80:
        return "HEALTHY"
    if score >= 60:
        return "WATCH"
    if score >= 40:
        return "WARNING"
    return "CRITICAL"


def _default_system_state() -> dict[str, Any]:
    """Fallback when system state can't be read."""
    return {
        "state": "NORMAL",
        "label": "正常 / NORMAL",
        "is_blocked": False,
        "can_open_positions": True,
        "can_close_positions": True,
        "reason": "Initial state (no state file)",
        "source": "system",
        "timestamp": "",
        "badge_class": "badge-green",
        "icon": "🟢",
        "n_transitions": 0,
        "last_source": "",
    }
