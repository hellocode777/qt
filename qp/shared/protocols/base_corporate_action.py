"""CorporateActionEngine — adjusts portfolio for corporate actions.

See rule.md §7.7 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class CorporateActionEngine(ABC):
    """Abstract base for corporate action adjustment engines.

    Handles dividends, stock splits, rights issues, and spin-offs,
    adjusting position quantities and cost basis accordingly.
    """

    @abstractmethod
    def adjust_portfolio(
        self,
        portfolio: pd.DataFrame,
        actions_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply corporate actions to adjust portfolio holdings.

        Args:
            portfolio: Current portfolio state (DataFrame with holdings).
            actions_df: DataFrame of corporate actions (dividends, splits, etc.).

        Returns:
            Adjusted portfolio with updated quantities and cost basis.
        """
        ...
