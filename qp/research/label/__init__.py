"""Label construction — forward returns and industry-neutralized ranking labels.

See rule.md §7.9.1 and research_layer.md §3.
"""

from qp.research.label.forward_returns import (
    build_forward_returns,
    build_industry_neutral_labels,
    build_labels,
)
from qp.research.label.label_utils import (
    check_label_coverage,
    detect_label_overlap,
    validate_label_rebalance_consistency,
)

__all__ = [
    "build_forward_returns",
    "build_industry_neutral_labels",
    "build_labels",
    "detect_label_overlap",
    "validate_label_rebalance_consistency",
    "check_label_coverage",
]
