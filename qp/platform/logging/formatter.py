"""Log formatter — unified log message formatting."""

from __future__ import annotations


def format_log_context(module: str, **context: str) -> str:
    """Format context key-values into a log-friendly string.

    Args:
        module: Module or component name.
        **context: Additional context key-value pairs.

    Returns:
        Formatted context string.
    """
    parts = [f"module={module}"] if module else []
    parts.extend(f"{k}={v}" for k, v in sorted(context.items()))
    return " ".join(parts)
