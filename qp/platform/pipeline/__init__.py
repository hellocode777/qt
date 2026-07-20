"""Pipeline Engine — universal abstraction for all long-running work.

See ADR-006: Everything Is Pipeline.
"""

from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.platform.pipeline.runner import PipelineRunner

__all__ = [
    "PipelineContext",
    "PipelineResult",
    "PipelineRunner",
]
