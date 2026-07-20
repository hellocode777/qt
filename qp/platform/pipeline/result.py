"""PipelineResult — outcome of a Pipeline execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from qp.shared.types import PipelineStatus


class PipelineResult:
    """Result of a single Pipeline execution (a Run)."""

    def __init__(
        self,
        status: PipelineStatus = PipelineStatus.SUCCESS,
        *,
        pipeline_name: str = "",
        run_id: str = "",
    ) -> None:
        self.status: PipelineStatus = status
        self.pipeline_name: str = pipeline_name
        self.run_id: str = run_id
        self.end_time: datetime = datetime.now(UTC)
        self.start_time: datetime | None = None
        self.metrics: dict[str, float] = {}
        self.artifacts: list[str] = []
        self.errors: list[str] = []
        self.metadata: dict[str, Any] = {}

    @property
    def duration_seconds(self) -> float:
        """Elapsed time in seconds."""
        if self.start_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    @property
    def is_success(self) -> bool:
        """Whether the pipeline completed successfully."""
        return self.status == PipelineStatus.SUCCESS
