"""Factor evaluation — Rank IC, layered test, IC decay analysis.

Thresholds from rule.md §10.1:
  - Rank IC mean abs ≥ 0.02
  - IC_IR ≥ 0.3
  - IC t-stat ≥ 2.0
  - Layered monotonicity t-stat ≥ 2.0
"""

from qp.research.evaluation.layered_test import (
    LayeredTestResult,
    compute_layered_returns,
    compute_quantile_spread_series,
)
from qp.research.evaluation.rank_ic import (
    ICRecord,
    compute_daily_ic_series,
    compute_ic_decay,
    compute_rank_ic,
    evaluate_factor_ic,
)

__all__ = [
    # Rank IC
    "ICRecord",
    # Layered test
    "LayeredTestResult",
    "compute_daily_ic_series",
    "compute_ic_decay",
    "compute_layered_returns",
    "compute_quantile_spread_series",
    "compute_rank_ic",
    "evaluate_factor_ic",
]
