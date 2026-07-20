"""BasePortfolioRiskManager — portfolio-level risk control interface.

See rule.md §7.5 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BasePortfolioRiskManager(ABC):
    """Abstract base for portfolio risk control engines.

    Enforces industry exposure limits, concentration limits, and correlation filters.
    """

    @abstractmethod
    def apply_risk_limits(
        self,
        raw_signals: pd.DataFrame,
        current_positions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply risk limits to raw strategy signals.

        Args:
            raw_signals: Strategy output signals.
            current_positions: Current portfolio holdings.

        Returns:
            Filtered target position candidates after risk checks.
        """
        ...
