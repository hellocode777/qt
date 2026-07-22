"""Research Trainer — model training, evaluation, and registry.

Exports LightGBMRankModel (default ML model, TDR-012),
CrossSectionalStandardizer, and ModelRegistry.
"""

from qp.research.trainer.auto_retrain import (
    MonthlyRetrainPipeline,
    RetrainResult,
)
from qp.research.trainer.lgb_rank import (
    DEFAULT_LGB_PARAMS,
    CrossSectionalStandardizer,
    LightGBMRankModel,
    build_monotone_constraints,
    build_monotone_constraints_dict,
)
from qp.research.trainer.registry import (
    ModelMetadata,
    ModelRegistry,
    copy_to_registry,
    hash_model,
)

__all__ = [
    "CrossSectionalStandardizer",
    "DEFAULT_LGB_PARAMS",
    "LightGBMRankModel",
    "ModelMetadata",
    "ModelRegistry",
    "MonthlyRetrainPipeline",
    "RetrainResult",
    "build_monotone_constraints",
    "build_monotone_constraints_dict",
    "copy_to_registry",
    "hash_model",
]
