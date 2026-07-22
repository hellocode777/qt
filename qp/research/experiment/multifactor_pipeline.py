"""Backward-compatibility shim — re-exports from the canonical location.

MultiFactorPipeline was moved to qp/pipeline/ (composition root) to fix
a layer violation: research layer (3) cannot import from strategy (5)
or simulation (7).  Orchestration pipelines live in qp/pipeline/ where
cross-layer imports are permitted per ADR-003.
"""

from qp.pipeline.multifactor_pipeline import MultiFactorPipeline  # noqa: F401
