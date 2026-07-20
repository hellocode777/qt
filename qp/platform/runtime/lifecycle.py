"""LifecycleManager — manages the Runtime state machine.

Valid transitions:
  CREATED → INITIALIZING → READY → RUNNING → STOPPING → TERMINATED
  Any → FAILED → STOPPING → TERMINATED

Fail Fast principle: config invalid, logger init fails, or storage init fails
→ immediate exit.
"""

from __future__ import annotations

from qp.shared.exceptions import RuntimeStateError
from qp.shared.types import RuntimeState

VALID_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.CREATED: {RuntimeState.INITIALIZING, RuntimeState.FAILED},
    RuntimeState.INITIALIZING: {RuntimeState.READY, RuntimeState.FAILED},
    RuntimeState.READY: {RuntimeState.RUNNING, RuntimeState.STOPPING, RuntimeState.FAILED},
    RuntimeState.RUNNING: {RuntimeState.STOPPING, RuntimeState.FAILED},
    RuntimeState.STOPPING: {RuntimeState.TERMINATED, RuntimeState.FAILED},
    RuntimeState.FAILED: {RuntimeState.STOPPING, RuntimeState.TERMINATED},
    RuntimeState.TERMINATED: set(),
}


class LifecycleManager:
    """Manages the Runtime state machine transitions."""

    def __init__(self) -> None:
        self._state = RuntimeState.CREATED

    @property
    def state(self) -> RuntimeState:
        """Current runtime state."""
        return self._state

    def can_transition_to(self, target: RuntimeState) -> bool:
        """Check if the transition to target is valid."""
        return target in VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, target: RuntimeState) -> None:
        """Transition to a new state.

        Args:
            target: The target RuntimeState.

        Raises:
            RuntimeStateError: If the transition is invalid.
        """
        if not self.can_transition_to(target):
            raise RuntimeStateError(
                f"Invalid state transition: {self._state.name} → {target.name}"
            )
        self._state = target

    def is_terminal(self) -> bool:
        """Whether the runtime is in a terminal state."""
        return self._state in (RuntimeState.TERMINATED,)
