"""EqualWeightAllocator — simplest capital allocation (1/N).

Per docs/8_Capital_Allocation_Layer.md §第一: Equal Weight:
  "最简单。也是我建议第一版默认。10只股票 → 10% 10% 10%..."

Reserves a cash buffer (default 5%) and distributes the rest equally.
Implements the standard allocate() interface for Layer 8.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_CASH_BUFFER = 0.05  # 5%


class EqualWeightAllocator(BaseCapitalAllocator):
    """Equal-weight (1/N) allocation with cash buffer.

    Usage:
        alloc = EqualWeightAllocator(cash_buffer=0.05)
        df = alloc.allocate(candidates, risk_report, total_capital=1_000_000)
    """

    def __init__(self, cash_buffer: float = DEFAULT_CASH_BUFFER) -> None:
        self._cash_buffer = cash_buffer

    # ------------------------------------------------------------------
    # Standard interface
    # ------------------------------------------------------------------

    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute equal weights for each Risk-Approved Candidate.

        Args:
            candidates: Risk-approved candidates with at least [symbol].
            risk_report: Layer 7 risk report (may be None — unused for equal weight).
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_capital].
        """
        if candidates.empty:
            return pd.DataFrame(columns=["symbol", "target_weight", "target_capital"])

        n = len(candidates)
        investable = total_capital * (1.0 - self._cash_buffer)
        weight = 1.0 / n

        result = candidates[["symbol"]].copy()
        result["target_weight"] = weight * (1.0 - self._cash_buffer)
        result["target_capital"] = investable * weight

        return cast("pd.DataFrame", result.reset_index(drop=True))

    # ------------------------------------------------------------------
    # Legacy interface
    # ------------------------------------------------------------------

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Legacy interface — delegates to allocate()."""
        return self.allocate(candidate_signals, None, total_capital)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def cash_buffer(self) -> float:
        return self._cash_buffer
