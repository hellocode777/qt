"""Application — the top-level QP Runtime container.

Aggregates RuntimeContext + LifecycleManager.
Provides start() / stop() / run_forever() for the entire system.

Signal handling (SIGTERM/SIGINT) triggers graceful shutdown.
"""

from __future__ import annotations

import contextlib
import signal
from typing import Any

from qp.platform.runtime.context import RuntimeContext
from qp.platform.runtime.lifecycle import LifecycleManager
from qp.shared.types import RuntimeState


class Application:
    """Top-level application object — the QP Runtime.

    Owns the runtime context and lifecycle. All layers run on top of this.

    Usage:
        # Short-lived (CLI commands):
        app = build_runtime()
        app.start()
        try:
            result = run_something(app.context)
        finally:
            app.stop()

        # Long-running (scheduler):
        app = build_runtime()
        app.start()
        app.run_forever()  # blocks until SIGTERM/SIGINT
        app.stop()
    """

    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.lifecycle = LifecycleManager()
        self._scheduler_started = False

    @property
    def state(self) -> RuntimeState:
        """Current runtime state."""
        return self.lifecycle.state

    # ── Lifecycle ──────────────────────────────────────────

    def start(self) -> None:
        """Start the runtime: CREATED → INITIALIZING → READY → RUNNING.

        Fail Fast: any initialization failure causes immediate exit.
        """
        self.lifecycle.transition_to(RuntimeState.INITIALIZING)
        self.context.logger.info("Runtime initializing...", module="runtime")

        # Freeze config (idempotent — builder already calls this, but safe)
        with contextlib.suppress(Exception):
            self.context.config.freeze()

        self.lifecycle.transition_to(RuntimeState.READY)
        self.context.logger.info(
            f"Runtime ready (env={self.context.environment}, v{self.context.version})",
            module="runtime",
        )

        self.lifecycle.transition_to(RuntimeState.RUNNING)
        self.context.logger.info("Runtime running", module="runtime")

    def stop(self) -> None:
        """Gracefully stop the runtime: RUNNING → STOPPING → TERMINATED."""
        if self.lifecycle.state in (RuntimeState.TERMINATED, RuntimeState.FAILED):
            return

        self.lifecycle.transition_to(RuntimeState.STOPPING)
        self.context.logger.info("Runtime stopping...", module="runtime")

        # Shut down scheduler if started
        if self._scheduler_started and self.context.scheduler is not None:
            try:
                self.context.scheduler.stop()
                self.context.logger.info("Scheduler stopped", module="runtime")
            except Exception as e:
                self.context.logger.error(
                    f"Error stopping scheduler: {e}", module="runtime"
                )

        # Close storage if connected
        if self.context.storage_factory is not None:
            try:
                storage = self.context.storage_factory.get_storage()
                storage.close()
                self.context.logger.info("Storage closed", module="runtime")
            except Exception as e:
                self.context.logger.error(
                    f"Error closing storage: {e}", module="runtime"
                )

        self.lifecycle.transition_to(RuntimeState.TERMINATED)
        self.context.logger.info("Runtime terminated", module="runtime")

    def fail(self, reason: str) -> None:
        """Mark the runtime as FAILED.

        Args:
            reason: The failure reason for logging.
        """
        self.context.logger.error(f"Runtime failed: {reason}", module="runtime")
        self.lifecycle.transition_to(RuntimeState.FAILED)

    # ── Long-running mode ──────────────────────────────────

    def run_forever(self) -> None:
        """Block until a termination signal is received.

        Sets up SIGTERM/SIGINT handlers for graceful shutdown.
        Use this for long-running processes like the scheduler.
        """
        shutdown_flag: dict[str, bool] = {"done": False}

        def _handle_signal(signum: int, frame: Any) -> None:
            sig_name = signal.Signals(signum).name
            self.context.logger.info(
                f"Received {sig_name}, shutting down...", module="runtime"
            )
            shutdown_flag["done"] = True

        original_term = signal.signal(signal.SIGTERM, _handle_signal)
        original_int = signal.signal(signal.SIGINT, _handle_signal)

        self.context.logger.info(
            "Runtime running (press Ctrl+C to stop)", module="runtime"
        )

        try:
            while not shutdown_flag["done"]:
                signal.pause()
        except (KeyboardInterrupt, AttributeError):
            # signal.pause() not available on all platforms
            import time

            while not shutdown_flag["done"]:
                time.sleep(0.5)
        finally:
            # Restore original handlers
            signal.signal(signal.SIGTERM, original_term)
            signal.signal(signal.SIGINT, original_int)
