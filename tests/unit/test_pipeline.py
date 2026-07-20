"""Tests for the Pipeline Engine."""

from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.platform.pipeline.runner import PipelineRunner
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus


class _SimplePipeline(BasePipeline):
    """A simple test pipeline."""

    @property
    def name(self) -> str:
        return "test_simple"

    def run(self, context: PipelineContext) -> PipelineResult:
        return PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )


class _FailingPipeline(BasePipeline):
    """A pipeline that raises an exception."""

    @property
    def name(self) -> str:
        return "test_failing"

    def run(self, context: PipelineContext) -> PipelineResult:
        raise RuntimeError("simulated failure")


class TestPipelineRunner:
    """Test PipelineRunner execution."""

    def test_successful_run(self) -> None:
        runner = PipelineRunner()
        result = runner.run(_SimplePipeline())
        assert result.status == PipelineStatus.SUCCESS
        assert result.pipeline_name == "test_simple"
        assert result.run_id != ""

    def test_failed_run(self) -> None:
        runner = PipelineRunner()
        result = runner.run(_FailingPipeline())
        assert result.status == PipelineStatus.FAILED
        assert len(result.errors) == 1
        assert "simulated failure" in result.errors[0]

    def test_duration_is_set(self) -> None:
        runner = PipelineRunner()
        result = runner.run(_SimplePipeline())
        assert result.start_time is not None
        assert result.duration_seconds >= 0


class TestPipelineResult:
    """Test PipelineResult object."""

    def test_default_status(self) -> None:
        result = PipelineResult()
        assert result.status == PipelineStatus.SUCCESS
        assert result.is_success is True

    def test_failed_status(self) -> None:
        result = PipelineResult(status=PipelineStatus.FAILED)
        assert result.is_success is False

    def test_errors_collection(self) -> None:
        result = PipelineResult(status=PipelineStatus.FAILED)
        result.errors.append("error 1")
        result.errors.append("error 2")
        assert len(result.errors) == 2
