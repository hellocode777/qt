"""Research Split — time-series cross-validation.

Exports PurgedKFold for walk-forward purged cross-validation (ADR-021).
"""

from qp.research.split.purged_cv import (
    PurgedFold,
    PurgedKFold,
    embargo_test_set,
    purge_train_set,
)

__all__ = [
    "PurgedKFold",
    "PurgedFold",
    "purge_train_set",
    "embargo_test_set",
]
