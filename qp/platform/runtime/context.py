"""RuntimeContext — the single source of truth for all infrastructure.

Any Pipeline can only access infrastructure through RuntimeContext.
No component may create its own Logger, Config, or Storage (ADR-012).

See dp.md §6.6 for the Runtime Context specification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qp.platform.config.models import Config
from qp.platform.logging.logger import QPLogger

if TYPE_CHECKING:
    from qp.platform.scheduler.scheduler import QPScheduler
    from qp.platform.storage.factory import StorageFactory


class Clock:
    """Injectable clock for deterministic time access."""

    def now(self) -> datetime:
        """Return the current time in UTC."""
        return datetime.now(UTC)


class RuntimeContext:
    """Holds all infrastructure components for the running application.

    Every layer accesses infrastructure through this context.
    Pipelines use runtime.logger, never create their own.

    Attributes:
        config: Frozen application configuration.
        logger: Unified logger (Loguru-backed).
        clock: Injectable clock for deterministic timestamps.
        scheduler: Job scheduler (set during Application.start()).
        storage_factory: Storage backend factory (set during Application.start()).
        version: Application version string.
        environment: Runtime environment (dev/prod/test).
        start_time: UTC timestamp when the runtime was created.
    """

    def __init__(
        self,
        config: Config,
        logger: QPLogger,
        clock: Clock | None = None,
        version: str = "0.0.1",
        environment: str = "dev",
    ) -> None:
        self.config = config
        self.logger = logger
        self.clock = clock or Clock()
        self.version = version
        self.environment = environment
        self.start_time: datetime = datetime.now(UTC)
        self._scheduler: QPScheduler | None = None
        self._storage_factory: StorageFactory | None = None

    @property
    def scheduler(self) -> QPScheduler | None:
        """The scheduler instance (set after initialization)."""
        return self._scheduler

    @scheduler.setter
    def scheduler(self, value: QPScheduler) -> None:
        self._scheduler = value

    @property
    def storage_factory(self) -> StorageFactory | None:
        """The storage factory instance (set after initialization)."""
        return self._storage_factory

    @storage_factory.setter
    def storage_factory(self, value: StorageFactory) -> None:
        self._storage_factory = value

    def uptime_seconds(self) -> float:
        """Return seconds since runtime was created."""
        return (datetime.now(UTC) - self.start_time).total_seconds()
