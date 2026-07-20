"""LogContext — bindable context for structured logging.

Allows binding run_id, pipeline_name, experiment_id, etc. to all subsequent
log messages within a scope.
"""

from __future__ import annotations

from typing import Any


class LogContext:
    """Mutable context bag for structured logging metadata."""

    def __init__(self) -> None:
        self._context: dict[str, Any] = {}

    def set(self, **kwargs: Any) -> None:
        """Set context values."""
        self._context.update(kwargs)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        return self._context.get(key, default)

    def clear(self) -> None:
        """Clear all context."""
        self._context.clear()

    def as_dict(self) -> dict[str, Any]:
        """Return context as a dict."""
        return self._context.copy()
