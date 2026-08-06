"""Feature importance — gain, SHAP, and drift detection.

See rule.md §7.9.7.
"""

from qp.research.importance.feature_importance import (
    ImportanceDriftReport,
    ImportanceRecord,
    compare_importance_versions,
    compute_gain_importance,
    compute_shap_importance,
)

__all__ = [
    "ImportanceDriftReport",
    "ImportanceRecord",
    "compare_importance_versions",
    "compute_gain_importance",
    "compute_shap_importance",
]
