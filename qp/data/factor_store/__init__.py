"""Factor Store — three-tier factor persistence (DP-002 §4.3).

Tiers:
  raw/     — raw factor outputs from compute_all_factors()
  refined/ — post-refinery (winsorize→normalize→neutralize)
  feature/ — versioned feature matrices for model training

Usage:
    from qp.data.factor_store import FactorStore, TierMetadata

    store = FactorStore()
    store.ensure_dirs()
    store.save_refined("momentum_v1", refined_df)
"""

from qp.data.factor_store.store import DEFAULT_STORE_ROOT, FactorStore, TierMetadata

__all__ = [
    "DEFAULT_STORE_ROOT",
    "FactorStore",
    "TierMetadata",
]
