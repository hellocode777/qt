"""Runtime module — Application lifecycle and state management."""

from qp.platform.runtime.application import Application
from qp.platform.runtime.builder import build_runtime
from qp.platform.runtime.context import RuntimeContext
from qp.platform.runtime.lifecycle import LifecycleManager

__all__ = [
    "Application",
    "LifecycleManager",
    "RuntimeContext",
    "build_runtime",
]
