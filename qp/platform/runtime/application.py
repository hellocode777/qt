"""Application — the top-level QP Runtime container.

Aggregates RuntimeContext + LifecycleManager.
Provides start() / stop() for the entire system.
"""

from __future__ import annotations

from qp.platform.runtime.context import RuntimeContext
from qp.platform.runtime.lifecycle import LifecycleManager
from qp.shared.types import RuntimeState


class Application:
    """Top-level application object — the QP Runtime.

    Owns the runtime context and lifecycle. All layers run on top of this.
    """

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.lifecycle = LifecycleManager()

    @property
    def state(self) -> RuntimeState:
        """Current runtime state."""
        return self.lifecycle.state

    def start(self) -> None:
        """Start the runtime: CREATED → INITIALIZING → READY → RUNNING.

        Fail Fast: any initialization failure causes immediate exit.
        """
        self.lifecycle.transition_to(RuntimeState.INITIALIZING)
        self.context.logger.info("Runtime initializing...", module="runtime")

        # Initialize subsystems would happen here in future milestones

        self.lifecycle.transition_to(RuntimeState.READY)
        self.context.logger.info("Runtime ready", module="runtime")

        self.lifecycle.transition_to(RuntimeState.RUNNING)
        self.context.logger.info("Runtime running", module="runtime")

    def stop(self) -> None:
        """Gracefully stop the runtime: RUNNING → STOPPING → TERMINATED."""
        self.lifecycle.transition_to(RuntimeState.STOPPING)
        self.context.logger.info("Runtime stopping...", module="runtime")

        # Cleanup subsystems would happen here

        self.lifecycle.transition_to(RuntimeState.TERMINATED)
        self.context.logger.info("Runtime terminated", module="runtime")

    def fail(self, reason: str) -> None:
        """Mark the runtime as FAILED.

        Args:
            reason: The failure reason for logging.
        """
        self.context.logger.error(f"Runtime failed: {reason}", module="runtime")
        self.lifecycle.transition_to(RuntimeState.FAILED)
