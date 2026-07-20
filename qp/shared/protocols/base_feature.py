"""BaseFeature — unified interface for all factor/feature computations.

See rule.md §7.2 for the complete specification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseFeature(ABC):
    """Abstract base for all factor and feature computation logic.

    Every feature must be registered in the Feature Registry (ADR-019).
    Features must respect the PIT (Point-in-Time) principle — no future
    information leakage is allowed.

    Note: DataFrame types are left as Any to allow both pandas and polars
    implementations (TDR-010).
    """

    @property
    @abstractmethod
    def feature_name(self) -> str:
        """Unique feature identifier, registered in Feature Registry."""
        ...

    @property
    @abstractmethod
    def required_data(self) -> list[str]:
        """List of underlying Dataset names this feature depends on."""
        ...

    @abstractmethod
    def compute(self, data_map: dict[str, Any]) -> Any:
        """Compute the feature values.

        Args:
            data_map: Mapping of dataset_name → DataFrame for all required_data.

        Returns:
            DataFrame with columns [trade_date, symbol, feature_value].
            Must strictly respect the single-day cross-section principle.
        """
        ...
