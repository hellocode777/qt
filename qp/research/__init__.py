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
    FeatureRegistry,
    Momentum20dFeature,
    Volatility20dFeature,
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
    # Feature
    "FeatureRegistry",
    "Momentum20dFeature",
    "Volatility20dFeature",
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
