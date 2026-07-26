"""PipelineContext — execution context for a Pipeline run.

Contains everything a pipeline needs: runtime reference, parameters, metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qp.platform.runtime.context import RuntimeContext


class PipelineContext:
    """Execution context passed to every Pipeline.run() invocation.

    Pipelines access infrastructure only through this context (ADR-012).
    When a RuntimeContext is attached, pipelines use runtime.logger,
    runtime.config, and runtime.storage_factory — never create their own.
    """

    def __init__(
        self,
        *,
        pipeline_name: str = "",
        parameters: dict[str, Any] | None = None,
        runtime: RuntimeContext | None = None,
        **kwargs: Any,
    ) -> None:
        self.run_id: str = uuid.uuid4().hex[:12]
        self.pipeline_name: str = pipeline_name
        self.start_time: datetime = datetime.now(UTC)
        self.parameters: dict[str, Any] = parameters or {}
        self.runtime: RuntimeContext | None = runtime

        # Allow attaching arbitrary attributes (logger, config, etc.)
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    @property
    def logger(self) -> Any:
        """Shortcut to the runtime logger.

        Priority: runtime.logger → attached _logger → bare loguru fallback.
        """
        if self.runtime is not None:
            return self.runtime.logger
        try:
            return object.__getattribute__(self, "_logger")
        except AttributeError:
            from loguru import logger as _loguru

            return _loguru

    @property
    def has_runtime(self) -> bool:
        """Whether a RuntimeContext is attached."""
        return self.runtime is not None

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
