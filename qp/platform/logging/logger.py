"""QPLogger — Structured logging wrapper around Loguru.

No module may use print() — all output must go through this logger.
Pipelines access the logger via runtime.logger (ADR-012).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger


class QPLogger:
    """Unified logging interface for the QP platform.

    Wraps Loguru with structured logging support and context binding.
    """

    def __init__(
        self,
        level: str = "INFO",
        log_dir: str = "logs",
        rotation: str = "10 MB",
        retention: str = "30 days",
        json_output: bool = False,
    ) -> None:
        self._logger = _loguru_logger
        self._configure(level, log_dir, rotation, retention, json_output)

    def _configure(
        self,
        level: str,
        log_dir: str,
        rotation: str,
        retention: str,
        json_output: bool,
    ) -> None:
        """Configure Loguru with the specified settings."""
        # Remove default handler
        self._logger.remove()

        # Console handler — colored or JSON
        if json_output:
            self._logger.add(
                sys.stderr,
                level=level,
                format='{"time":"{time:ISO8601}","level":"{level}","name":"{name}",'
                '"message":"{message}","extra":{extra}}',
                serialize=False,
            )
        else:
            self._logger.add(
                sys.stderr,
                level=level,
                format=(
                    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                    "<level>{level: <8}</level> | "
                    "<cyan>{extra[module]: <20}</cyan> | "
                    "<level>{message}</level> | "
                    "<dim>{extra}</dim>"
                ),
                colorize=True,
            )

        # File handler — always structured
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        self._logger.add(
            log_path / "qp_{time:YYYY-MM-DD}.log",
            level=level,
            format=(
                "{time:ISO8601} | {level: <8} | {extra[module]: <20} | "
                "{message} | {extra}"
            ),
            rotation=rotation,
            retention=retention,
            encoding="utf-8",
        )

    def _log(
        self,
        level: str,
        message: str,
        module: str = "",
        **context: Any,
    ) -> None:
        """Log a message with structured context."""
        extra = {"module": module, **context}
        self._logger.bind(**extra).log(level, message)

    def debug(self, message: str, *, module: str = "", **context: Any) -> None:
        """Log a DEBUG-level message."""
        self._log("DEBUG", message, module=module, **context)

    def info(self, message: str, *, module: str = "", **context: Any) -> None:
        """Log an INFO-level message."""
        self._log("INFO", message, module=module, **context)

    def warning(self, message: str, *, module: str = "", **context: Any) -> None:
        """Log a WARNING-level message."""
        self._log("WARNING", message, module=module, **context)

    def error(self, message: str, *, module: str = "", **context: Any) -> None:
        """Log an ERROR-level message."""
        self._log("ERROR", message, module=module, **context)

    def critical(self, message: str, *, module: str = "", **context: Any) -> None:
        """Log a CRITICAL-level message."""
        self._log("CRITICAL", message, module=module, **context)

    def bind(self, **context: Any) -> None:
        """Bind context to all subsequent log messages in this scope.

        Usage:
            logger.bind(run_id="run-001")
            logger.info("Pipeline started")  # includes run_id
        """
        self._logger.configure(extra=context)
