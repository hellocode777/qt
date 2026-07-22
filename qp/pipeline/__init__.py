"""Pipeline orchestration — composition root for cross-layer workflows.

Pipelines in this module orchestrate across all 10 layers per ADR-003
(explicit composition root). They are the ONLY place where cross-layer
imports are permitted — individual layers must not import from layers above them.
"""

from qp.pipeline.daily_pipeline import DailyPipeline
from qp.pipeline.multifactor_pipeline import MultiFactorPipeline

__all__ = ["DailyPipeline", "MultiFactorPipeline"]
