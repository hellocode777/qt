"""PipelineRunner — executes a Pipeline and records the result."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.types import PipelineStatus

if TYPE_CHECKING:
    from qp.shared.protocols.base_pipeline import BasePipeline


class PipelineRunner:
    """Executes a BasePipeline and records execution metadata."""

    def run(self, pipeline: BasePipeline) -> PipelineResult:
        """Execute a pipeline synchronously.

        Args:
            pipeline: The pipeline instance to execute.

        Returns:
            PipelineResult with status, metrics, and errors.
        """
        context = PipelineContext(pipeline_name=pipeline.name)
        context.start_time = datetime.now(UTC)

        try:
            result = pipeline.run(context)
            if not isinstance(result, PipelineResult):
                result = PipelineResult(
                    status=PipelineStatus.SUCCESS,
                    pipeline_name=pipeline.name,
                    run_id=context.run_id,
                )
        except Exception as e:
            result = PipelineResult(
                status=PipelineStatus.FAILED,
                pipeline_name=pipeline.name,
                run_id=context.run_id,
            )
            result.errors.append(f"{type(e).__name__}: {e}")

        result.start_time = context.start_time
        result.end_time = datetime.now(UTC)
        result.run_id = context.run_id
        result.pipeline_name = pipeline.name

        return result
