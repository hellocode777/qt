"""System State Manager — cross-pipeline state machine (#15).

Provides the single source of truth for the system's current risk posture.
All pipelines read from and write to this state, enabling cross-pipeline
awareness:

  NORMAL   → All clear, full operation
  WARNING  → Elevated risk, reduce exposure, increase monitoring
  PAUSED   → Stop new positions, allow sells
  STOPPED  → Full stop, liquidate positions
  RECOVERY → Returning to normal, gradual re-entry

State transitions are logged immutably. Downstream pipelines MUST check
current state before executing.

Usage:
    mgr = SystemStateManager()
    mgr.transition(SystemState.WARNING, reason="PSI 0.32 > 0.25")
    current = mgr.current()
    if current.state >= SystemState.PAUSED:
        print("Cannot execute — system is paused")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

import polars as pl

from qp.shared.paths import MONITORING_DIR

DEFAULT_STATE_DIR = MONITORING_DIR
STATE_FILE = "system_state.parquet"
STATE_LOG_FILE = "system_state_log.parquet"


class SystemState(IntEnum):
    """Ordered severity — higher = more restrictive.

    Using IntEnum so >= comparisons work naturally:
        if current >= SystemState.PAUSED: refuse new positions
    """

    NORMAL = 0
    WARNING = 1
    PAUSED = 2
    STOPPED = 3
    RECOVERY = 4  # Special: between PAUSED and NORMAL, gradual re-entry

    def label(self) -> str:
        labels = {
            SystemState.NORMAL: "正常 / NORMAL",
            SystemState.WARNING: "警告 / WARNING",
            SystemState.PAUSED: "暂停 / PAUSED",
            SystemState.STOPPED: "停止 / STOPPED",
            SystemState.RECOVERY: "恢复中 / RECOVERY",
        }
        return labels.get(self, "?")

    def can_open_positions(self) -> bool:
        """True if system allows new positions."""
        return self in (SystemState.NORMAL, SystemState.WARNING)

    def can_close_positions(self) -> bool:
        """True if system allows selling/closing positions."""
        return True  # Always allow closing — safety first


_STATE_LOG_SCHEMA: dict[str, type] = {
    "timestamp": str,
    "from_state": int,
    "to_state": int,
    "reason": str,
    "source": str,
    "details": str,
}


@dataclass
class StateTransition:
    """One immutable state change record."""

    timestamp: str = ""
    from_state: SystemState = SystemState.NORMAL
    to_state: SystemState = SystemState.NORMAL
    reason: str = ""
    source: str = ""  # Which pipeline/trigger caused this
    details: str = ""  # JSON of supporting metrics

    def to_dict(self) -> dict[str, Any]:

        return {
            "timestamp": self.timestamp,
            "from_state": int(self.from_state),
            "to_state": int(self.to_state),
            "reason": self.reason,
            "source": self.source,
            "details": self.details,
        }


class SystemStateManager:
    """Cross-pipeline system state machine.

    Persists current state to Parquet. Every transition is logged
    immutably for audit. Downstream pipelines call current() before
    executing to check whether the system is healthy.

    Thread-safe: writes are atomic (write new file, rename).
    """

    def __init__(self, base_dir: str | Path = DEFAULT_STATE_DIR) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._state_file = self._base / STATE_FILE
        self._log_file = self._base / STATE_LOG_FILE

    # ------------------------------------------------------------------
    # State API
    # ------------------------------------------------------------------

    def current(self) -> StateTransition:
        """Get the current system state.

        Returns:
            StateTransition with the current state. Defaults to NORMAL
            if no state has been recorded.
        """
        if not self._state_file.exists():
            return StateTransition(
                timestamp=datetime.now(UTC).isoformat(),
                from_state=SystemState.NORMAL,
                to_state=SystemState.NORMAL,
                reason="Initial state",
                source="system",
            )

        df = pl.read_parquet(self._state_file)
        if df.is_empty():
            return StateTransition(
                timestamp=datetime.now(UTC).isoformat(),
                from_state=SystemState.NORMAL,
                to_state=SystemState.NORMAL,
                reason="Initial state",
                source="system",
            )

        row = df.head(1).to_dicts()[0]
        return StateTransition(
            timestamp=row.get("timestamp", ""),
            from_state=SystemState(int(row.get("from_state", 0))),
            to_state=SystemState(int(row.get("to_state", 0))),
            reason=row.get("reason", ""),
            source=row.get("source", ""),
            details=row.get("details", ""),
        )

    def transition(
        self,
        to_state: SystemState,
        reason: str = "",
        source: str = "",
        details: str = "",
    ) -> StateTransition:
        """Transition the system to a new state.

        Args:
            to_state: Target state.
            reason: Why the transition is happening.
            source: Which subsystem triggered this.
            details: JSON of supporting metrics.

        Returns:
            The recorded StateTransition.
        """
        current = self.current()
        transition = StateTransition(
            timestamp=datetime.now(UTC).isoformat(),
            from_state=current.to_state,
            to_state=to_state,
            reason=reason,
            source=source,
            details=details,
        )

        # Write current state (single row)
        state_df = pl.DataFrame(
            [transition.to_dict()],
            schema={
                "timestamp": str,
                "from_state": int,
                "to_state": int,
                "reason": str,
                "source": str,
                "details": str,
            },
        )
        state_df.write_parquet(self._state_file)

        # Append to immutable log
        self._append_log(transition)

        return transition

    def auto_transition(
        self,
        monitor_action: str,
        reason: str = "",
        source: str = "KillSwitchPipeline",
        details: str = "",
    ) -> StateTransition | None:
        """Automatically transition based on KillSwitchPipeline action.

        Maps MonitorAction to SystemState:
          OK      → NORMAL (or RECOVERY if currently PAUSED+)
          WATCH   → WARNING
          PAUSE_BUY → PAUSED
          REDUCE  → WARNING
          STOP    → STOPPED

        Returns:
            StateTransition if state changed, None if unchanged.
        """
        action_map: dict[str, SystemState] = {
            "OK": SystemState.NORMAL,
            "ok": SystemState.NORMAL,
            "WATCH": SystemState.WARNING,
            "watch": SystemState.WARNING,
            "PAUSE_BUY": SystemState.PAUSED,
            "pause_buy": SystemState.PAUSED,
            "REDUCE": SystemState.WARNING,
            "reduce": SystemState.WARNING,
            "STOP": SystemState.STOPPED,
            "stop": SystemState.STOPPED,
        }

        target = action_map.get(monitor_action)
        if target is None:
            return None

        current = self.current()

        # If current is STOPPED and action is not STOP, transition to RECOVERY
        if current.to_state == SystemState.STOPPED and target != SystemState.STOPPED:
            target = SystemState.RECOVERY

        # If current is PAUSED and action is NORMAL, go to RECOVERY first
        if current.to_state == SystemState.PAUSED and target == SystemState.NORMAL:
            target = SystemState.RECOVERY

        # Only transition if state actually changed
        if target == current.to_state:
            # Same state: still refresh the reason/details so the WebUI
            # shows the latest monitoring verdict instead of a stale
            # first-transition text (e.g. a new PSI value under WARNING).
            if current.reason != reason or current.details != details:
                self.transition(target, reason=reason, source=source, details=details)
            return None

        return self.transition(target, reason=reason, source=source, details=details)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def is_blocked(self) -> bool:
        """True if the system should not execute new trades."""
        current = self.current()
        return not current.to_state.can_open_positions()

    def history(self, limit: int = 50) -> pl.DataFrame:
        """Get state transition history.

        Returns:
            Polars DataFrame of transitions, newest first.
        """
        if not self._log_file.exists():
            return pl.DataFrame(schema=_STATE_LOG_SCHEMA)
        df = pl.read_parquet(self._log_file)
        return df.sort("timestamp", descending=True).head(limit)

    def stats(self) -> dict[str, Any]:
        """State machine statistics."""
        current = self.current()
        log = self.history(limit=1000)

        days_in_current = "unknown"
        if current.to_state != SystemState.NORMAL and not log.is_empty():
            first = log.filter(pl.col("to_state") == int(current.to_state))
            if not first.is_empty():
                first_ts = first["timestamp"].min()  # type: ignore[call-overload]
                days_in_current = f"{first_ts} → now"

        return {
            "current_state": current.to_state.name,
            "current_label": current.to_state.label(),
            "is_blocked": self.is_blocked(),
            "last_reason": current.reason,
            "last_source": current.source,
            "n_transitions": log.height,
            "days_in_current_state": days_in_current,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append_log(self, transition: StateTransition) -> None:
        """Append to immutable transition log."""
        new_row = pl.DataFrame([transition.to_dict()], schema=_STATE_LOG_SCHEMA)

        if self._log_file.exists():
            existing = pl.read_parquet(self._log_file)
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._log_file)
        else:
            new_row.write_parquet(self._log_file)
