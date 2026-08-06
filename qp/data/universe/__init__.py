"""Dynamic Universe — PIT-compliant tradable stock universe construction.

Implements data_layer.md §1.4: PIT & Universe（时点数据与动态标的池）.

Modules:
  - listing_dates.py: IPO/listing date registry with fallback chain
  - liquidity.py: Volume-based liquidity cutoff
  - restatement.py: Financial restatement multi-version tracking
  - universe_builder.py: Orchestrator — chains all filters into a tradeable universe

Quick start::

    from qp.data.universe import UniverseBuilder, UniverseConfig

    builder = UniverseBuilder(UniverseConfig())
    universe = builder.build(df, as_of_date="2024-06-30")
    # → pl.DataFrame filtered to tradeable stocks only
"""

from qp.data.universe.liquidity import (
    compute_median_volume,
    filter_by_liquidity,
    filter_by_percentile,
    get_liquidity_stats,
)
from qp.data.universe.listing_dates import (
    ListingDateRegistry,
    get_listing_date,
    is_listed_before,
)
from qp.data.universe.restatement import RestatementTracker
from qp.data.universe.universe_builder import UniverseBuilder, UniverseConfig

__all__ = [
    # Listing dates
    "ListingDateRegistry",
    # Restatement
    "RestatementTracker",
    # Builder
    "UniverseBuilder",
    "UniverseConfig",
    # Liquidity
    "compute_median_volume",
    "filter_by_liquidity",
    "filter_by_percentile",
    "get_liquidity_stats",
    "get_listing_date",
    "is_listed_before",
]
