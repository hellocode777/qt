"""EqualWeightAllocator — simplest capital allocation (1/N).

Reserves a cash buffer (default 5%) and distributes the rest equally.
"""

from __future__ import annotations

import pandas as pd

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_CASH_BUFFER = 0.05  # 5%


class EqualWeightAllocator(BaseCapitalAllocator):
    """Equal-weight (1/N) allocation with cash buffer.

    Usage:
        alloc = EqualWeightAllocator(cash_buffer=0.05)
        weights = alloc.allocate_capital(signals, total_capital=1_000_000)
    """

    def __init__(self, cash_buffer: float = DEFAULT_CASH_BUFFER) -> None:
        self._cash_buffer = cash_buffer

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute equal weights for each candidate.

        Args:
            candidate_signals: DataFrame with at least [symbol].
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_amount].
        """
        if candidate_signals.empty:
            return pd.DataFrame(columns=["symbol", "target_weight", "target_amount"])

        n = len(candidate_signals)
        investable = total_capital * (1.0 - self._cash_buffer)
        weight = 1.0 / n

        result = candidate_signals[["symbol"]].copy()
        result["target_weight"] = weight * (1.0 - self._cash_buffer)
        result["target_amount"] = investable * weight

        return result.reset_index(drop=True)  # type: ignore[return-value]

    @property
    def cash_buffer(self) -> float:
        return self._cash_buffer
