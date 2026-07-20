"""PipelineContext — execution context for a Pipeline run.

Contains everything a pipeline needs: runtime reference, parameters, metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class PipelineContext:
    """Execution context passed to every Pipeline.run() invocation.

    Pipelines access infrastructure only through this context (ADR-012).
    """

    def __init__(
        self,
        *,
        pipeline_name: str = "",
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.run_id: str = uuid.uuid4().hex[:12]
        self.pipeline_name: str = pipeline_name
        self.start_time: datetime = datetime.now(UTC)
        self.parameters: dict[str, Any] = parameters or {}
        # Allow attaching arbitrary attributes (logger, config, etc.)
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    @property
    def logger(self):
        """Shortcut to the runtime logger."""
        return object.__getattribute__(self, "_logger")

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
