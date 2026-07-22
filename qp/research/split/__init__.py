"""Research Split — time-series cross-validation.

Exports:
  - PurgedKFold: Standalone purged CV splitter (ADR-021).
  - PurgedGroupTimeSeriesSplit: sklearn-compatible purged CV.
  - PurgedKFoldSklearn: Full _BaseKFold subclass (if sklearn installed).
"""

from qp.research.split.purged_cv import (
    PurgedFold,
    PurgedGroupTimeSeriesSplit,
    PurgedKFold,
    embargo_test_set,
    purge_train_set,
)

# Optional sklearn BaseKFold subclass
try:
    from qp.research.split.purged_cv import PurgedKFoldSklearn
except ImportError:
    PurgedKFoldSklearn = None  # type: ignore[assignment]

__all__ = [
    "PurgedKFold",
    "PurgedFold",
    "PurgedGroupTimeSeriesSplit",
    "PurgedKFoldSklearn",
    "purge_train_set",
    "embargo_test_set",
]
