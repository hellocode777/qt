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
    DEFAULT_DECAY_HORIZONS,
    ICRecord,
    compute_daily_ic_series,
    compute_daily_ic_series_from_forward,
    compute_ic_decay,
    compute_ic_decay_from_forward,
    compute_rank_ic,
    evaluate_factor_ic,
    evaluate_factor_ic_from_forward,
    prepare_forward_returns,
)

__all__ = [
    # Rank IC
    "DEFAULT_DECAY_HORIZONS",
    "ICRecord",
    # Layered test
    "LayeredTestResult",
    "compute_daily_ic_series",
    "compute_daily_ic_series_from_forward",
    "compute_ic_decay",
    "compute_ic_decay_from_forward",
    "compute_layered_returns",
    "compute_quantile_spread_series",
    "compute_rank_ic",
    "evaluate_factor_ic",
    "evaluate_factor_ic_from_forward",
    "prepare_forward_returns",
]
