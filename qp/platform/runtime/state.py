"""Runtime state machine — lifecycle states.

CREATED → INITIALIZING → READY → RUNNING → STOPPING → TERMINATED
along with FAILED state.

See dp.md §6.5 for the complete state machine specification.
"""

from __future__ import annotations

from qp.shared.types import RuntimeState

__all__ = ["RuntimeState"]
