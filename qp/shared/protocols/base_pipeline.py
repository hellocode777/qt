"""BasePipeline — the universal abstraction for all long-running work.

All business pipelines (DataPipeline, FeaturePipeline, TrainingPipeline,
BacktestPipeline, etc.) inherit from this class.

See ADR-006: Everything Is Pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BasePipeline(ABC):
    """Abstract base class for all pipelines in the system."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique pipeline identifier (e.g. 'daily_ingest', 'momentum_20d')."""
        ...

    @abstractmethod
    def run(self, context: Any) -> Any:
        """Execute the pipeline.

        Args:
            context: PipelineContext containing runtime, config, logger, and parameters.

        Returns:
            PipelineResult with status, metrics, artifacts, and errors.
        """
        ...
