"""RuntimeContext — the single source of truth for all infrastructure.

Any Pipeline can only access infrastructure through RuntimeContext.
No component may create its own Logger, Config, or Storage (ADR-012).

See dp.md §6.6 for the Runtime Context specification.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qp.platform.config.models import Config
from qp.platform.logging.logger import QPLogger


class Clock:
    """Injectable clock for deterministic time access."""

    def now(self) -> datetime:
        """Return the current time in UTC."""
        return datetime.now(UTC)


class RuntimeContext:
    """Holds all infrastructure components for the running application.

    Every layer accesses infrastructure through this context.
    Pipelines use runtime.logger, never create their own.
    """

    def __init__(
        self,
        config: Config,
        logger: QPLogger,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.clock = clock or Clock()
        self._scheduler = None
        self._storage_factory = None

    @property
    def scheduler(self):
        """The scheduler instance (set after initialization)."""
        return self._scheduler

    @scheduler.setter
    def scheduler(self, value) -> None:
        self._scheduler = value

    @property
    def storage_factory(self):
        """The storage factory instance (set after initialization)."""
        return self._storage_factory

    @storage_factory.setter
    def storage_factory(self, value) -> None:
        self._storage_factory = value
