"""BaseCapitalAllocator — capital distribution engine interface.

See rule.md §7.5 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseCapitalAllocator(ABC):
    """Abstract base for capital allocation engines.

    Converts filtered signals into concrete target weights and amounts.
    Supports Equal Weight, Risk Parity, Kelly Criterion, etc.
    """

    @abstractmethod
    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute target weights and amounts for each candidate.

        Args:
            candidate_signals: Risk-filtered candidates.
            total_capital: Total available capital.

        Returns:
            DataFrame with columns [symbol, target_weight, target_amount].
        """
        ...
