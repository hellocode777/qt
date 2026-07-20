"""BaseRiskModel — multi-factor risk decomposition interface.

See rule.md §7.8 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseRiskModel(ABC):
    """Abstract base for portfolio risk factor attribution models.

    Decomposes total portfolio risk into systematic and idiosyncratic components.
    """

    @abstractmethod
    def decompose_risk(self, portfolio_holdings: pd.DataFrame) -> dict[str, float]:
        """Decompose total risk into factor components.

        Total Risk = Market Risk + Style Risk + Sector Risk + Idiosyncratic Risk.

        Args:
            portfolio_holdings: Current portfolio holdings with weights.

        Returns:
            Dictionary mapping risk component names to their values.
        """
        ...
