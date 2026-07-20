"""BaseModel — unified interface for all ML / statistical models.

See rule.md §7.3 and §7.9 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseModel(ABC):
    """Abstract base for all machine learning and statistical models.

    Concrete implementations include LightGBMRankModel (default), XGBoost, etc.
    See rule.md §7.9 for LightGBM-specific training specifications.
    """

    @abstractmethod
    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: pd.Series | None = None,
    ) -> None:
        """Train the model.

        Args:
            X: Feature matrix.
            y: Target labels.
            sample_weight: Optional sample weights.
        """
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate predictions or ranking scores.

        Args:
            X: Feature matrix.

        Returns:
            Series of prediction scores, indexed like X.
        """
        ...

    @abstractmethod
    def save_model(self, path: str) -> None:
        """Serialize the model to disk, recording hyperparameter metadata.

        Args:
            path: File path to save the model.
        """
        ...

    @abstractmethod
    def load_model(self, path: str) -> None:
        """Load a previously registered model version.

        Args:
            path: File path to the saved model.
        """
        ...
