"""Research Trainer — model training and evaluation.

Exports LightGBMRankModel (default ML model, TDR-012) and CrossSectionalStandardizer.
"""

from qp.research.trainer.lgb_rank import (
    DEFAULT_LGB_PARAMS,
    CrossSectionalStandardizer,
    LightGBMRankModel,
)

__all__ = [
    "LightGBMRankModel",
    "CrossSectionalStandardizer",
    "DEFAULT_LGB_PARAMS",
]
