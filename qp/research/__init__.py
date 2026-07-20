"""Research Layer — reproducible experiments and feature engineering."""

from qp.research.experiment import (
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentRecord,
    ExperimentRunner,
    ExperimentTracker,
    LineageGraph,
)
from qp.research.feature import (
    ALL_FACTOR_DESCRIPTIONS,
    ALL_FACTOR_DIRECTIONS,
    PRICE_VOLUME_FACTORS,
    FeatureRegistry,
    Momentum1M,
    Momentum3M,
    Momentum6M,
    Momentum20dFeature,
    ShortTermReversal5D,
    Volatility20D,
    Volatility20dFeature,
    Volatility60D,
    compute_all_factors,
    get_default_factor_weights,
)
from qp.research.split import PurgedKFold, embargo_test_set, purge_train_set
from qp.research.trainer import (
    CrossSectionalStandardizer,
    LightGBMRankModel,
    ModelMetadata,
    ModelRegistry,
)

__all__ = [
    # Experiment
    "ExperimentConfig",
    "ExperimentMetrics",
    "ExperimentRecord",
    "ExperimentRunner",
    "ExperimentTracker",
    "LineageGraph",
    # Feature — classes
    "FeatureRegistry",
    "Momentum20dFeature",  # backward-compatible
    "Volatility20dFeature",  # backward-compatible
    "Momentum1M",
    "Momentum3M",
    "Momentum6M",
    "ShortTermReversal5D",
    "Volatility20D",
    "Volatility60D",
    # Feature — batch compute
    "compute_all_factors",
    "get_default_factor_weights",
    "ALL_FACTOR_DIRECTIONS",
    "ALL_FACTOR_DESCRIPTIONS",
    "PRICE_VOLUME_FACTORS",
    # Split
    "PurgedKFold",
    "embargo_test_set",
    "purge_train_set",
    # Trainer
    "CrossSectionalStandardizer",
    "LightGBMRankModel",
    "ModelMetadata",
    "ModelRegistry",
]
